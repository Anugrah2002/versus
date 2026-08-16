"""
Multi-Provider LLM Orchestrator for Versus Dual-Perspective Synthesis.
Executes cascading failover: Cloudflare AI -> Groq -> Gemini -> Local Fallback.
Supports immediate streaming publication to Firestore upon topic completion and duplicate topic suppression.
"""

from typing import Optional, List, Tuple, Callable
from datetime import datetime, timezone
import hashlib

from config.settings import settings
from src.synthesis.providers.cloudflare_ai import CloudflareAIProvider
from src.synthesis.providers.groq_provider import GroqAIProvider
from src.synthesis.providers.gemini_provider import GeminiAIProvider
from src.synthesis.providers.fallback_provider import local_fallback_synthesizer
from src.storage.firestore_sync import firestore_sync
from src.storage.models import (
    StoryCluster,
    ArticleModel,
    PerspectiveModel,
    PerspectiveType,
    ClusterClassification,
    ActiveStoryState
)
from src.utils.logger import logger


class LLMSynthesisEngine:
    def __init__(self):
        self.cloudflare = CloudflareAIProvider()
        self.groq = GroqAIProvider()
        self.gemini = GeminiAIProvider()
        self.fallback = local_fallback_synthesizer
        self.total_ai_calls = 0
        self.last_provider_used = "none"

    def _generate_article_id(self, cluster: StoryCluster) -> str:
        if cluster.matched_existing_article_id:
            return cluster.matched_existing_article_id

        key = "_".join(sorted(a.url_hash for a in cluster.articles))
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
        return f"art_{h}"

    def synthesize(self, cluster: StoryCluster) -> Optional[ArticleModel]:
        raw_json = None
        provider_name = "none"

        # 1. Primary: Cloudflare Workers AI
        if self.cloudflare.is_configured:
            logger.info(f"Synthesizing cluster {cluster.cluster_id} with Cloudflare Workers AI...")
            raw_json = self.cloudflare.synthesize_cluster(cluster)
            if raw_json:
                provider_name = "Cloudflare Workers AI"
                self.total_ai_calls += 1

        # 2. Secondary: Groq Llama-3.3-70B
        if not raw_json and self.groq.is_configured:
            logger.info(f"Failing over to Groq Llama-3.3-70B for cluster {cluster.cluster_id}...")
            raw_json = self.groq.synthesize_cluster(cluster)
            if raw_json:
                provider_name = "Groq Llama-3.3-70B"
                self.total_ai_calls += 1

        # 3. Tertiary: Google Gemini Flash
        if not raw_json and self.gemini.is_configured:
            logger.info(f"Failing over to Google Gemini Flash for cluster {cluster.cluster_id}...")
            raw_json = self.gemini.synthesize_cluster(cluster)
            if raw_json:
                provider_name = "Google Gemini Flash"
                self.total_ai_calls += 1

        # 4. Failsafe Fallback: Local Rule-Based Synthesizer
        if not raw_json and settings.ENABLE_LOCAL_FALLBACK:
            raw_json = self.fallback.synthesize_cluster(cluster)
            provider_name = "Local Heuristic Fallback"

        if not raw_json:
            logger.error(f"Failed to synthesize cluster {cluster.cluster_id} through all providers.")
            return None

        self.last_provider_used = provider_name

        article_id = self._generate_article_id(cluster)
        now_iso = datetime.now(timezone.utc).isoformat()

        sorted_articles = sorted(cluster.articles, key=lambda a: a.credibility, reverse=True)
        hero_image = getattr(sorted_articles[0], "hero_image_url", None) or "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1080&q=80"

        perspectives_data = raw_json.get("perspectives", [])
        validated_perspectives: List[PerspectiveModel] = []

        for idx, p in enumerate(perspectives_data):
            p_type = p.get("type", "viewpoint1" if idx == 0 else "viewpoint2")
            if cluster.classification == ClusterClassification.SINGLE_REPORT:
                p_type = "directReport"

            p_id = f"p_{article_id}_{idx + 1}"
            validated_perspectives.append(
                PerspectiveModel(
                    id=p_id,
                    type=p_type,
                    sourceName=p.get("sourceName", sorted_articles[min(idx, len(sorted_articles)-1)].feed_name),
                    sourceDomain=p.get("sourceDomain", sorted_articles[min(idx, len(sorted_articles)-1)].domain),
                    biasTag=p.get("biasTag", sorted_articles[min(idx, len(sorted_articles)-1)].default_bias),
                    sourceCredibility=int(p.get("sourceCredibility", 92)),
                    stanceTitle=p.get("stanceTitle", "")[:100],
                    summary=p.get("summary", ""),
                    keyPoints=p.get("keyPoints", [])[:2],
                    quote=p.get("quote", ""),
                    quoteAuthor=p.get("quoteAuthor", ""),
                    fullMarkdownContent=p.get("fullMarkdownContent", "")
                )
            )

        divergence = int(raw_json.get("divergenceScore", 85 if len(validated_perspectives) > 1 else 0))
        consensus = int(raw_json.get("consensusScore", 100 - divergence))
        is_single = len(validated_perspectives) <= 1 or divergence == 0

        article = ArticleModel(
            id=article_id,
            title=raw_json.get("title", cluster.articles[0].title)[:120],
            summary=raw_json.get("summary", "")[:1200],
            category=raw_json.get("category", cluster.category),
            publishedAt=now_iso,
            divergenceScore=divergence,
            consensusScore=consensus,
            heroImageUrl=hero_image,
            videoUrl="",
            videoDuration="02:45",
            perspectives=validated_perspectives,
            likesCount=0,
            commentsCount=0,
            sharesCount=0,
            bookmarksCount=0,
            readTimeMinutes=2,
            isSinglePerspective=is_single,
            tags=raw_json.get("tags", [cluster.category])
        )

        return article

    def synthesize_and_publish_single(
        self,
        cluster: StoryCluster,
        on_published: Optional[Callable[[ArticleModel, StoryCluster], None]] = None
    ) -> Optional[ArticleModel]:
        """Synthesizes a cluster and immediately writes it to Firestore."""
        article = self.synthesize(cluster)
        if article:
            # Publish immediately to Firestore as each topic finishes
            firestore_sync.commit_single_article(article, cluster)
            if on_published:
                on_published(article, cluster)
        return article

    def synthesize_batch(
        self,
        clusters: List[StoryCluster],
        max_concurrent: int = 8,
        on_published: Optional[Callable[[ArticleModel, StoryCluster], None]] = None
    ) -> List[Tuple[ArticleModel, StoryCluster]]:
        if not clusters:
            return []

        # Prioritize debates and upgrades first
        def cluster_priority(c: StoryCluster) -> int:
            if c.classification == ClusterClassification.NEW_DEBATE:
                return 0
            if c.classification == ClusterClassification.UPGRADE_STORY:
                return 1
            return 2

        sorted_clusters = sorted(clusters, key=cluster_priority)
        logger.info(f"Synthesizing and streaming {len(sorted_clusters)} story clusters with {max_concurrent} parallel workers...")

        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: List[Tuple[ArticleModel, StoryCluster]] = []

        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            future_to_cluster = {
                executor.submit(self.synthesize_and_publish_single, c, on_published): c
                for c in sorted_clusters
            }
            for future in as_completed(future_to_cluster):
                c = future_to_cluster[future]
                try:
                    art = future.result()
                    if art:
                        results.append((art, c))
                except Exception as e:
                    logger.warning(f"Synthesis failed for cluster {c.cluster_id}: {e}")

        return results


synthesis_engine = LLMSynthesisEngine()
