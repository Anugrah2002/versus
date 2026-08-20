"""
Multi-Provider LLM Orchestrator for Versus Dual-Perspective Synthesis.
Executes cascading failover: Cloudflare AI -> Groq -> Gemini -> Local Fallback.
Supports immediate streaming publication to Firestore upon topic completion and duplicate topic suppression.
"""

from typing import Optional, List, Tuple, Callable
from datetime import datetime, timezone
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

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

        # 4. Quaternary: Local Ollama Qwen (qwen2.5:1.5b / qwen2.5:3b)
        if not raw_json:
            from src.synthesis.providers.ollama_provider import ollama_qwen_provider
            if ollama_qwen_provider.is_configured:
                raw_json = ollama_qwen_provider.synthesize_cluster(cluster)
                if raw_json:
                    provider_name = f"Local Ollama ({ollama_qwen_provider.model_name})"
                    self.total_ai_calls += 1

        # 5. Quinary: Local Llama.cpp GGUF
        if not raw_json:
            from src.synthesis.providers.llamacpp_provider import llamacpp_provider
            raw_json = llamacpp_provider.synthesize_cluster(cluster)
            if raw_json:
                provider_name = "Local Llama.cpp CPU (Qwen-2.5-3B)"
                self.total_ai_calls += 1

        # 6. Failsafe Fallback: Enhanced Rule-Based Editorial NLP Synthesizer
        if not raw_json and settings.ENABLE_LOCAL_FALLBACK:
            raw_json = self.fallback.synthesize_cluster(cluster)
            provider_name = "Enhanced Heuristic Editorial Fallback"

        if not raw_json:
            logger.error(f"Failed to synthesize cluster {cluster.cluster_id} through all providers.")
            return None

        self.last_provider_used = provider_name

        article_id = self._generate_article_id(cluster)
        now_iso = datetime.now(timezone.utc).isoformat()

        sorted_articles = sorted(cluster.articles, key=lambda a: a.credibility, reverse=True)
        first_img = getattr(sorted_articles[0], "hero_image_url", None)
        if first_img and isinstance(first_img, str) and first_img.strip().startswith("http"):
            hero_image = first_img.strip()
        else:
            from src.extractors.article_extractor import article_extractor
            hero_image = article_extractor._get_category_fallback_image(cluster.category, article_id)

        perspectives_data = raw_json.get("perspectives", [])
        validated_perspectives: List[PerspectiveModel] = []

        def _trim_summary(text: str, max_words: int = 55) -> str:
            if not text:
                return ""
            words = text.split()
            if len(words) <= max_words:
                return text.strip()
            truncated = " ".join(words[:max_words])
            last_dot = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
            if last_dot > len(truncated) * 0.6:
                return truncated[:last_dot + 1].strip()
            return truncated.strip() + "."

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
                    stanceTitle=(p.get("stanceTitle") or sorted_articles[min(idx, len(sorted_articles)-1)].title)[:250],
                    summary=_trim_summary(p.get("summary", "")),
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
            summary=_trim_summary(raw_json.get("summary", "") or validated_perspectives[0].summary),
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

        # Quality Gatekeeper: Enforce 25-word minimum summary threshold
        summary_words = len(article.summary.split())
        if summary_words < 25:
            # Fallback to extracting lead from primary source
            extracted_lead = self.fallback._extract_lead_summary(cluster.articles[0].cleaned_body, max_words=55)
            if len(extracted_lead.split()) >= 25:
                article.summary = extracted_lead
                for p in article.perspectives:
                    if len(p.summary.split()) < 25:
                        p.summary = extracted_lead
            else:
                logger.warning(f"Discarding cluster {cluster.cluster_id}: Summary has only {summary_words} words (min threshold: 25 words)")
                return None

        for p in article.perspectives:
            if len(p.summary.split()) < 25:
                p.summary = article.summary

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

        batch_start = time.time()
        max_batch_seconds = 420  # 7 minutes watchdog ceiling
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

                # Watchdog check to prevent GitHub Action runner timeouts
                if (time.time() - batch_start) > max_batch_seconds:
                    logger.warning(
                        f"⏱️ [WATCHDOG TIMEOUT GUARD] Synthesis reached 7m limit. "
                        f"Gracefully concluding batch with {len(results)} completed stories to preserve runner state."
                    )
                    break

        return results


synthesis_engine = LLMSynthesisEngine()
