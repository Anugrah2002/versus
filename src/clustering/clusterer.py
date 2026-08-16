"""
Local Semantic Clustering & Active Story Matcher.
Groups raw articles into cohesive story clusters, resolves delayed second perspectives,
and prevents duplicate analysis of topics already covered in active debates.
"""

from typing import List, Tuple, Optional
from datetime import datetime, timezone
import hashlib
import math
import re

from config.settings import settings
from src.clustering.embedder import embedder
from src.storage.models import (
    ExtractedArticle,
    StoryCluster,
    ClusterClassification,
    ActiveStoryState
)
from src.utils.logger import logger


class SemanticClusterer:
    def __init__(self, threshold: float = settings.SIMILARITY_DISTANCE_THRESHOLD):
        self.threshold = threshold

    def _prepare_text(self, article: ExtractedArticle) -> str:
        body_snippet = " ".join(article.cleaned_body.split()[:200])
        return f"{article.title} — {body_snippet}"

    def _cosine_distance(self, vec_a: List[float], vec_b: List[float]) -> float:
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        return float(1.0 - max(min(dot, 1.0), -1.0))

    def _stem_set(self, text: str) -> set:
        words = re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", text.lower())
        return set(w[:4] for w in words if len(w) >= 3)

    def _text_overlap_similarity(self, title_a: str, title_b: str, body_a: str = "", body_b: str = "") -> float:
        stems_t_a = self._stem_set(title_a)
        stems_t_b = self._stem_set(title_b)
        title_overlap = 0.0
        if stems_t_a and stems_t_b:
            inter = len(stems_t_a.intersection(stems_t_b))
            union = len(stems_t_a.union(stems_t_b))
            title_overlap = inter / union if union > 0 else 0.0

        body_overlap = 0.0
        if body_a and body_b:
            stems_b_a = self._stem_set(body_a)
            stems_b_b = self._stem_set(body_b)
            if stems_b_a and stems_b_b:
                inter = len(stems_b_a.intersection(stems_b_b))
                union = len(stems_b_a.union(stems_b_b))
                body_overlap = inter / union if union > 0 else 0.0

        return max(title_overlap, (title_overlap * 0.7 + body_overlap * 0.3))

    def _compute_distance(
        self,
        vec_a: List[float],
        vec_b: List[float],
        title_a: str = "",
        title_b: str = "",
        body_a: str = "",
        body_b: str = ""
    ) -> float:
        vec_dist = self._cosine_distance(vec_a, vec_b)
        if title_a and title_b:
            overlap = self._text_overlap_similarity(title_a, title_b, body_a, body_b)
            if overlap >= 0.09:
                overlap_dist = max(0.0, 1.0 - (overlap * 6.5))
                vec_dist = min(vec_dist, overlap_dist)
        return max(0.0, min(vec_dist, 1.0))

    def _compute_centroid(self, vectors: List[List[float]]) -> List[float]:
        dim = len(vectors[0])
        centroid = [0.0] * dim
        for v in vectors:
            for i in range(dim):
                centroid[i] += v[i]
        n = len(vectors)
        centroid = [c / n for c in centroid]
        norm = math.sqrt(sum(x * x for x in centroid))
        if norm > 0:
            centroid = [x / norm for x in centroid]
        return centroid

    def cluster_articles(
        self,
        articles: List[ExtractedArticle],
        active_stories: List[ActiveStoryState]
    ) -> List[StoryCluster]:
        if not articles:
            return []

        logger.info(f"Clustering {len(articles)} extracted articles...")

        texts = [self._prepare_text(a) for a in articles]
        embeddings = embedder.embed_texts(texts)

        clusters: List[StoryCluster] = []
        unassigned_indices = list(range(len(articles)))

        # Step 2: Match against active rolling 48-hour story centroids
        if active_stories:
            logger.info(f"Checking against {len(active_stories)} active 48h story centroids for upgrades and duplicate topic suppression...")
            for active in active_stories:
                active_centroid = active.centroid_vector
                if not active_centroid:
                    continue

                matched_article_indices = []

                for idx in list(unassigned_indices):
                    cand_vec = embeddings[idx]
                    cand_article = articles[idx]
                    dist = self._compute_distance(
                        active_centroid,
                        cand_vec,
                        title_a=active.title,
                        title_b=cand_article.title,
                        body_a="",
                        body_b=cand_article.cleaned_body
                    )

                    if dist < self.threshold:
                        matched_article_indices.append(idx)

                if matched_article_indices:
                    # Case A: If active story is single perspective, upgrade it in-place
                    if active.is_single_perspective:
                        new_domain_articles = [
                            articles[i] for i in matched_article_indices
                            if articles[i].domain not in active.domains
                        ]
                        if new_domain_articles:
                            cluster_id = f"upg_{active.article_id}_{int(datetime.now(timezone.utc).timestamp())}"
                            clusters.append(
                                StoryCluster(
                                    cluster_id=cluster_id,
                                    classification=ClusterClassification.UPGRADE_STORY,
                                    category=active.category,
                                    articles=new_domain_articles,
                                    centroid_vector=active_centroid,
                                    matched_existing_article_id=active.article_id
                                )
                            )
                            logger.info(
                                f"✨ Delayed Perspective Match: Story '{active.title[:45]}...' "
                                f"matched {len(new_domain_articles)} new perspective from {[a.domain for a in new_domain_articles]}!"
                            )
                    else:
                        # Case B: Topic is already an active dual-perspective debate. Suppress duplicate re-analysis.
                        logger.info(
                            f"🛡️ Duplicate Topic Suppressed: {len(matched_article_indices)} articles matched active debate '{active.title[:45]}...'. Skipping duplicate analysis."
                        )

                    for idx in matched_article_indices:
                        if idx in unassigned_indices:
                            unassigned_indices.remove(idx)

        # Step 3: Cluster remaining unassigned articles
        if unassigned_indices:
            remaining_articles = [articles[i] for i in unassigned_indices]
            remaining_embeddings = [embeddings[i] for i in unassigned_indices]

            groups = {}
            used = set()
            gid = 0
            for i in range(len(remaining_articles)):
                if i in used:
                    continue
                groups[gid] = [i]
                used.add(i)
                for j in range(i + 1, len(remaining_articles)):
                    if j not in used:
                        d = self._compute_distance(
                            remaining_embeddings[i],
                            remaining_embeddings[j],
                            title_a=remaining_articles[i].title,
                            title_b=remaining_articles[j].title,
                            body_a=remaining_articles[i].cleaned_body,
                            body_b=remaining_articles[j].cleaned_body
                        )
                        if d < self.threshold:
                            groups[gid].append(j)
                            used.add(j)
                gid += 1

            for label, member_indices in groups.items():
                cluster_articles = [remaining_articles[i] for i in member_indices]
                cluster_vecs = [remaining_embeddings[i] for i in member_indices]
                centroid = self._compute_centroid(cluster_vecs)

                domains = set(a.domain for a in cluster_articles)
                cid_hash = hashlib.sha256(
                    "".join(sorted(a.url_hash for a in cluster_articles)).encode()
                ).hexdigest()[:12]
                cluster_id = f"cluster_{cid_hash}"

                if len(cluster_articles) >= 2 and len(domains) >= 2:
                    classification = ClusterClassification.NEW_DEBATE
                else:
                    classification = ClusterClassification.SINGLE_REPORT

                categories = [a.category for a in cluster_articles]
                dominant_category = max(set(categories), key=categories.count)

                clusters.append(
                    StoryCluster(
                        cluster_id=cluster_id,
                        classification=classification,
                        category=dominant_category,
                        articles=cluster_articles,
                        centroid_vector=centroid
                    )
                )

        logger.info(
            f"Clustering complete: Formed {len(clusters)} story clusters "
            f"({sum(1 for c in clusters if c.classification == ClusterClassification.NEW_DEBATE)} debates, "
            f"{sum(1 for c in clusters if c.classification == ClusterClassification.UPGRADE_STORY)} upgrades, "
            f"{sum(1 for c in clusters if c.classification == ClusterClassification.SINGLE_REPORT)} single reports)."
        )
        return clusters


clusterer = SemanticClusterer()
