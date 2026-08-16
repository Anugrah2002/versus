"""
Firebase Firestore Synchronization Engine.
Performs immediate single-document writes as stories complete synthesis,
atomic batch commits, delayed perspective upgrades, and rolling 30-day TTL data retention cleanup.
"""

from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime, timezone, timedelta
from config.settings import settings
from src.storage.models import ArticleModel, StoryCluster, ClusterClassification
from src.utils.logger import logger


class FirestoreSyncEngine:
    def __init__(self):
        self._db = None
        self._initialized = False

    def initialize(self) -> bool:
        if self._initialized:
            return True

        credentials_dict = settings.get_firebase_credentials_dict()
        if not credentials_dict:
            logger.warning("Firebase credentials not provided. Running in Local Offline / Dry-Run mode.")
            return False

        try:
            import firebase_admin
            from firebase_admin import credentials, firestore

            if not firebase_admin._apps:
                cred = credentials.Certificate(credentials_dict)
                firebase_admin.initialize_app(cred, {
                    "projectId": settings.FIRESTORE_PROJECT_ID
                })

            self._db = firestore.client()
            self._initialized = True
            logger.info("Connected to Firebase Firestore successfully.")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Firebase Admin SDK: {e}")
            return False

    @property
    def db(self):
        return self._db

    def commit_single_article(self, article: ArticleModel, cluster: StoryCluster) -> bool:
        """Immediately publishes a synthesized story to Firestore."""
        if settings.DRY_RUN or not self._db:
            logger.info(f"[DRY RUN -> FIRESTORE] Published article '{article.title[:55]}...' ({article.category} | Divergence: {article.divergenceScore}%)")
            return True

        try:
            col_ref = self._db.collection(settings.FIRESTORE_COLLECTION_ARTICLES)
            doc_ref = col_ref.document(article.id)

            if cluster.classification == ClusterClassification.UPGRADE_STORY:
                # Update existing single-perspective document in-place to dual perspectives
                doc_ref.update({
                    "title": article.title,
                    "summary": article.summary,
                    "divergenceScore": article.divergenceScore,
                    "consensusScore": article.consensusScore,
                    "isSinglePerspective": False,
                    "perspectives": [p.model_dump() for p in article.perspectives],
                    "tags": article.tags,
                    "lastUpgradedAt": datetime.now(timezone.utc).isoformat()
                })
                logger.info(f"✨ [FIRESTORE UPGRADE] Story '{article.title[:45]}...' upgraded in-place to dual perspectives.")
            else:
                # Insert or overwrite new article document
                doc_data = article.to_firestore_dict()
                doc_ref.set(doc_data)
                logger.info(f"🚀 [FIRESTORE PUBLISH] Published story '{article.title[:45]}...' ({article.category} | Divergence: {article.divergenceScore}%)")

            return True
        except Exception as e:
            logger.error(f"Failed to publish single article {article.id} to Firestore: {e}")
            return False

    def commit_batch(
        self,
        articles: List[Tuple[ArticleModel, StoryCluster]]
    ) -> int:
        if not articles:
            return 0

        if settings.DRY_RUN or not self._db:
            logger.info(f"[DRY RUN] Would write {len(articles)} articles to Firestore collection '{settings.FIRESTORE_COLLECTION_ARTICLES}'.")
            return len(articles)

        try:
            batch = self._db.batch()
            col_ref = self._db.collection(settings.FIRESTORE_COLLECTION_ARTICLES)

            for article, cluster in articles:
                doc_ref = col_ref.document(article.id)
                doc_data = article.to_firestore_dict()

                if cluster.classification == ClusterClassification.UPGRADE_STORY:
                    batch.update(doc_ref, {
                        "title": article.title,
                        "summary": article.summary,
                        "divergenceScore": article.divergenceScore,
                        "consensusScore": article.consensusScore,
                        "isSinglePerspective": False,
                        "perspectives": [p.model_dump() for p in article.perspectives],
                        "tags": article.tags,
                        "lastUpgradedAt": datetime.now(timezone.utc).isoformat()
                    })
                else:
                    batch.set(doc_ref, doc_data)

            batch.commit()
            logger.info(f"Committed {len(articles)} articles to Firestore in 1 atomic batch.")
            return len(articles)

        except Exception as e:
            logger.error(f"Firestore batch commit failed: {e}")
            return 0

    def cleanup_expired_articles(self) -> int:
        if settings.DRY_RUN or not self._db:
            return 0

        try:
            cutoff_date = (
                datetime.now(timezone.utc) - timedelta(days=settings.DATA_RETENTION_DAYS)
            ).isoformat()

            col_ref = self._db.collection(settings.FIRESTORE_COLLECTION_ARTICLES)
            old_docs = col_ref.where("publishedAt", "<", cutoff_date).limit(50).stream()

            deleted_count = 0
            batch = self._db.batch()
            for doc in old_docs:
                batch.delete(doc.reference)
                deleted_count += 1

            if deleted_count > 0:
                batch.commit()
                logger.info(f"TTL Cleanup: Deleted {deleted_count} articles older than {settings.DATA_RETENTION_DAYS} days.")

            return deleted_count

        except Exception as e:
            logger.debug(f"TTL cleanup skipped or failed: {e}")
            return 0


firestore_sync = FirestoreSyncEngine()
