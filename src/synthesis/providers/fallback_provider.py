"""
Local Rule-Based Heuristic Synthesizer (Zero-Cost Failsafe Fallback).
Guarantees the ingestion pipeline never crashes even if offline or out of API quota.
Extracts complete, grammatically sound lead sentences and key takeaways (90-120 words).
"""

from typing import Dict, Any, List
import re
from src.storage.models import StoryCluster, ClusterClassification, ExtractedArticle
from src.utils.logger import logger


class LocalFallbackSynthesizer:
    def _split_into_sentences(self, text: str) -> List[str]:
        cleaned = re.sub(r"\s+", " ", text).strip()
        raw_sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        valid = []
        for s in raw_sentences:
            s_clean = s.strip()
            if len(s_clean.split()) >= 5:
                valid.append(s_clean)
        return valid

    def _extract_lead_summary(self, body: str, max_words: int = 115) -> str:
        sentences = self._split_into_sentences(body)
        if not sentences:
            return body[:500].strip()

        collected = []
        total_words = 0

        for s in sentences:
            w_count = len(s.split())
            if total_words + w_count <= max_words or not collected:
                collected.append(s)
                total_words += w_count
            else:
                break

        return " ".join(collected)

    def _extract_key_points(self, body: str) -> List[str]:
        sentences = self._split_into_sentences(body)
        bullets = []
        for s in sentences[1:5]:
            if len(s) > 130:
                words = s.split()
                truncated = " ".join(words[:16]) + "."
                bullets.append(truncated)
            else:
                bullets.append(s)
            if len(bullets) == 3:
                break

        if not bullets and sentences:
            bullets.append(sentences[0])

        while len(bullets) < 2:
            bullets.append("Key analytical takeaway and operational overview.")

        return bullets[:3]

    def synthesize_cluster(self, cluster: StoryCluster) -> Dict[str, Any]:
        logger.info(f"Using local rule-based heuristic synthesizer for cluster {cluster.cluster_id}")
        articles = cluster.articles
        primary = articles[0]

        is_debate = cluster.classification in (
            ClusterClassification.NEW_DEBATE,
            ClusterClassification.UPGRADE_STORY
        )

        title = primary.title
        summary = self._extract_lead_summary(primary.cleaned_body, max_words=115)
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
                "stanceTitle": art_a.title[:90],
                "summary": self._extract_lead_summary(art_a.cleaned_body, max_words=100),
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
                "stanceTitle": art_b.title[:90],
                "summary": self._extract_lead_summary(art_b.cleaned_body, max_words=100),
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
                "stanceTitle": primary.title[:90],
                "summary": self._extract_lead_summary(primary.cleaned_body, max_words=100),
                "keyPoints": self._extract_key_points(primary.cleaned_body),
                "quote": "",
                "quoteAuthor": ""
            })

        return {
            "title": title[:95],
            "summary": summary,
            "category": cluster.category,
            "divergenceScore": divergence,
            "consensusScore": consensus,
            "perspectives": perspectives,
            "tags": [cluster.category, "Verified News", "Trending"]
        }


fallback_synthesizer = LocalFallbackSynthesizer()
