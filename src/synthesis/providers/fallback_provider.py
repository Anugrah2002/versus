"""
Local Rule-Based Heuristic Synthesizer (Zero-Cost Failsafe Fallback).
Guarantees the ingestion pipeline never crashes even if offline or out of API quota.
"""

from typing import Dict, Any, List
from src.storage.models import StoryCluster, ClusterClassification, ExtractedArticle
from src.utils.logger import logger


class LocalFallbackSynthesizer:
    def _extract_lead_summary(self, body: str, max_words: int = 70) -> str:
        words = body.split()
        if len(words) <= max_words:
            return body
        return " ".join(words[:max_words]) + "."

    def _extract_key_points(self, body: str) -> List[str]:
        sentences = [s.strip() for s in body.replace("\n", " ").split(".") if len(s.strip().split()) >= 6]
        bullets = []
        for s in sentences[:2]:
            clean_bullet = s[:75].strip()
            if not clean_bullet.endswith("."):
                clean_bullet += "."
            bullets.append(clean_bullet)

        while len(bullets) < 2:
            bullets.append("Key analytical takeaway and operational overview.")
        return bullets[:2]

    def synthesize_cluster(self, cluster: StoryCluster) -> Dict[str, Any]:
        logger.info(f"Using local rule-based heuristic synthesizer for cluster {cluster.cluster_id}")
        articles = cluster.articles
        primary = articles[0]

        is_debate = cluster.classification in (
            ClusterClassification.NEW_DEBATE,
            ClusterClassification.UPGRADE_STORY
        )

        title = primary.title
        summary = self._extract_lead_summary(primary.cleaned_body, max_words=25)
        divergence = 88 if is_debate else 0
        consensus = 12 if is_debate else 100

        perspectives = []

        if is_debate and len(articles) >= 2:
            art_a = articles[0]
            art_b = articles[1]

            perspectives.append({
                "type": "viewpoint1",
                "sourceName": art_a.feed_name,
                "sourceDomain": art_a.domain,
                "biasTag": art_a.default_bias,
                "sourceCredibility": art_a.credibility,
                "stanceTitle": art_a.title[:85],
                "summary": self._extract_lead_summary(art_a.cleaned_body, max_words=65),
                "keyPoints": self._extract_key_points(art_a.cleaned_body),
                "quote": "",
                "quoteAuthor": ""
            })

            perspectives.append({
                "type": "viewpoint2",
                "sourceName": art_b.feed_name,
                "sourceDomain": art_b.domain,
                "biasTag": art_b.default_bias,
                "sourceCredibility": art_b.credibility,
                "stanceTitle": art_b.title[:85],
                "summary": self._extract_lead_summary(art_b.cleaned_body, max_words=65),
                "keyPoints": self._extract_key_points(art_b.cleaned_body),
                "quote": "",
                "quoteAuthor": ""
            })
        else:
            perspectives.append({
                "type": "directReport",
                "sourceName": primary.feed_name,
                "sourceDomain": primary.domain,
                "biasTag": primary.default_bias,
                "sourceCredibility": primary.credibility,
                "stanceTitle": primary.title[:85],
                "summary": self._extract_lead_summary(primary.cleaned_body, max_words=65),
                "keyPoints": self._extract_key_points(primary.cleaned_body),
                "quote": "",
                "quoteAuthor": ""
            })

        tags = [cluster.category.split("&")[0].strip(), "News", "Analysis"]

        return {
            "title": title,
            "summary": summary,
            "category": cluster.category,
            "divergenceScore": divergence,
            "consensusScore": consensus,
            "tags": tags,
            "perspectives": perspectives
        }


local_fallback_synthesizer = LocalFallbackSynthesizer()
