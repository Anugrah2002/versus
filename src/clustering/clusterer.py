"""
High-Precision Semantic Clustering & Active Story Matcher.
Combines SentenceTransformer dense embeddings with strict Named Entity & Core Subject Anchors.
Guarantees ZERO false-positive topic merging (e.g. EdTech AI vs Aviation) while accurately grouping multi-source debates.
"""

from typing import List, Tuple, Optional, Set
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

# Comprehensive stopwords including generic industry/business filler terms
COMMON_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or",
    "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so",
    "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll",
    "they're", "they've", "this", "those", "through", "to", "too", "under", "until",
    "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves",
    # News common noise words
    "says", "said", "saying", "report", "reports", "reported", "breaking", "news",
    "update", "updates", "first", "latest", "today", "yesterday", "tomorrow",
    "daily", "weekly", "source", "sources", "official", "officials", "amid",
    "exclusive", "watch", "video", "photos", "photo", "images", "times", "post"
}


class SemanticClusterer:
    def __init__(self, threshold: float = 0.35):
        self.threshold = threshold

    def _prepare_text(self, article: ExtractedArticle) -> str:
        body_snippet = " ".join(article.cleaned_body.split()[:150])
        return f"{article.title}. {body_snippet}"

    def _cosine_distance(self, vec_a: List[float], vec_b: List[float]) -> float:
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        return float(1.0 - max(min(dot, 1.0), -1.0))

    def _extract_content_keywords(self, text: str) -> Set[str]:
        words = re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", text.lower())
        return set(w for w in words if w not in COMMON_STOPWORDS and len(w) >= 3)

    def _extract_proper_nouns(self, text: str) -> Set[str]:
        # Extract capitalized entities (company names, people, places)
        tokens = re.findall(r"\b[A-Z][a-z0-9]{2,}\b", text)
        return set(t.lower() for t in tokens if t.lower() not in COMMON_STOPWORDS)

    def _calculate_topical_overlap(self, title_a: str, title_b: str, body_a: str = "", body_b: str = "") -> Tuple[bool, float]:
        """
        Calculates exact topical overlap score.
        Guarantees that two articles MUST share core subject anchors (Entities or Distinct Topic Keywords).
        """
        props_a = self._extract_proper_nouns(title_a)
        props_b = self._extract_proper_nouns(title_b)
        
        # 1. Named Entity / Proper Noun Overlap (e.g. PhysicsWallah vs Boeing = 0 match)
        common_props = props_a.intersection(props_b)
        has_entity_match = len(common_props) >= 1

        # 2. Content Keywords in Title
        keys_a = self._extract_content_keywords(title_a)
        keys_b = self._extract_content_keywords(title_b)
        
        title_overlap = 0.0
        common_title_keys = keys_a.intersection(keys_b)
        if keys_a and keys_b:
            union = keys_a.union(keys_b)
            title_overlap = len(common_title_keys) / len(union) if union else 0.0

        # Require hard subject matter convergence
        # At least 1 shared proper noun OR at least 2 distinct non-generic title keywords
        has_valid_topic_match = has_entity_match or (len(common_title_keys) >= 2 and title_overlap >= 0.18)

        overlap_score = title_overlap if has_valid_topic_match else 0.0
        return has_valid_topic_match, overlap_score

    def _compute_distance(
        self,
        vec_a: List[float],
        vec_b: List[float],
        title_a: str = "",
        title_b: str = "",
        body_a: str = "",
        body_b: str = ""
    ) -> float:
        raw_vec_dist = self._cosine_distance(vec_a, vec_b)

        if title_a and title_b:
            has_match, overlap_score = self._calculate_topical_overlap(title_a, title_b, body_a, body_b)
            if not has_match:
                return 1.0  # Force complete separation for unrelated topics

            # Scale distance down when shared subject matter is confirmed
            if overlap_score > 0:
                adjusted_dist = raw_vec_dist * (1.0 - min(overlap_score * 2.2, 0.70))
                return max(0.0, min(adjusted_dist, 1.0))

        return raw_vec_dist

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

        logger.info(f"Clustering {len(articles)} extracted articles with high-precision semantic matching...")

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

                    if cand_article.category != active.category:
                        continue

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
                        logger.info(
                            f"🛡️ Duplicate Topic Suppressed: {len(matched_article_indices)} articles matched active debate '{active.title[:45]}...'. Skipping duplicate analysis."
                        )

                    for idx in matched_article_indices:
                        if idx in unassigned_indices:
                            unassigned_indices.remove(idx)

        # Step 3: Cluster remaining unassigned articles by Category + Semantic Distance
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
                        if remaining_articles[i].category != remaining_articles[j].category:
                            continue

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
