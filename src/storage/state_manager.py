"""
State Manager for Seen URLs, ETags, and Active Story Centroids.
Uses Partitioned Sliding-Window Architecture across dedicated Firestore documents in `_system`.
Guarantees constant <25 KB document sizes and zero risk of hitting Firestore 1MB limits.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta

from config.settings import settings
from src.storage.models import ActiveStoryState, ArticleModel, StoryCluster
from src.utils.logger import logger


class StateManager:
    def __init__(self, local_path: Optional[str] = None):
        self.local_path = Path(local_path or settings.LOCAL_STATE_CACHE_PATH)
        self.seen_url_hashes: set = set()
        self.feed_states: Dict[str, Dict[str, str]] = {}  # url -> {etag, last_modified}
        self.active_stories: Dict[str, ActiveStoryState] = {}  # article_id -> ActiveStoryState
        self._firestore_db = None
        self._load_local_state()

    def set_firestore_client(self, db_client: Any):
        self._firestore_db = db_client
        self.load_from_firestore()

    def _load_local_state(self):
        if self.local_path.exists():
            try:
                with open(self.local_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.seen_url_hashes = set(data.get("seen_hashes", []))
                    self.feed_states = data.get("feed_states", {})
                    stories_data = data.get("active_stories", {})
                    self.active_stories = {
                        k: ActiveStoryState(**v) for k, v in stories_data.items()
                    }
                    logger.info(
                        f"Loaded state from local cache: {len(self.seen_url_hashes)} seen URLs, "
                        f"{len(self.active_stories)} active story centroids."
                    )
            except Exception as e:
                logger.warning(f"Failed to read local state cache ({e}). Starting fresh.")

    def save_local_state(self):
        try:
            self.local_path.parent.mkdir(parents=True, exist_ok=True)
            self._prune_expired_state()
            data = {
                "seen_hashes": list(self.seen_url_hashes)[-5000:],
                "feed_states": self.feed_states,
                "active_stories": {k: v.model_dump() for k, v in self.active_stories.items()},
                "last_saved_at": datetime.now(timezone.utc).isoformat()
            }
            with open(self.local_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved pipeline state to {self.local_path}")
        except Exception as e:
            logger.error(f"Failed to save local state: {e}")

    def load_from_firestore(self):
        """Loads state from partitioned documents in _system with fallback to legacy single doc."""
        if not self._firestore_db:
            return
        try:
            system_col = self._firestore_db.collection(settings.FIRESTORE_COLLECTION_SYSTEM)

            # 1. Load Feed ETags
            doc_etags = system_col.document("feed_etags").get()
            if doc_etags.exists:
                data = doc_etags.to_dict() or {}
                if "feed_states_json" in data:
                    try:
                        self.feed_states.update(json.loads(data["feed_states_json"]))
                    except Exception:
                        pass

            # 2. Load Active Centroids (48h debates)
            doc_centroids = system_col.document("active_centroids").get()
            if doc_centroids.exists:
                data = doc_centroids.to_dict() or {}
                if "active_stories_json" in data:
                    try:
                        stories_data = json.loads(data["active_stories_json"])
                        for k, v in stories_data.items():
                            self.active_stories[k] = ActiveStoryState(**v)
                    except Exception:
                        pass

            # 3. Load Seen Hashes (14-day sliding window)
            doc_hashes = system_col.document("seen_hashes").get()
            if doc_hashes.exists:
                data = doc_hashes.to_dict() or {}
                if "seen_hashes_json" in data:
                    try:
                        self.seen_url_hashes.update(json.loads(data["seen_hashes_json"]))
                    except Exception:
                        pass

            # 4. Migration fallback: If partitioned docs were empty, check legacy pipeline_state
            if not self.seen_url_hashes:
                doc_legacy = system_col.document("pipeline_state").get()
                if doc_legacy.exists:
                    data = doc_legacy.to_dict() or {}
                    if "seen_hashes_json" in data:
                        try:
                            self.seen_url_hashes.update(json.loads(data["seen_hashes_json"]))
                        except Exception:
                            pass
                    if not self.feed_states and "feed_states_json" in data:
                        try:
                            self.feed_states.update(json.loads(data["feed_states_json"]))
                        except Exception:
                            pass
                    if not self.active_stories and "active_stories_json" in data:
                        try:
                            stories_data = json.loads(data["active_stories_json"])
                            for k, v in stories_data.items():
                                self.active_stories[k] = ActiveStoryState(**v)
                        except Exception:
                            pass

            logger.info(
                f"Synced partitioned state from Firestore: {len(self.seen_url_hashes)} seen hashes, "
                f"{len(self.feed_states)} feed ETags, {len(self.active_stories)} active 48h centroids."
            )
        except Exception as e:
            logger.warning(f"Could not load partitioned state from Firestore ({e}). Using local state.")

    def save_to_firestore(self):
        """Saves partitioned sliding-window state across 3 discrete documents in _system."""
        if not self._firestore_db or settings.DRY_RUN:
            return
        try:
            self._prune_expired_state()
            system_col = self._firestore_db.collection(settings.FIRESTORE_COLLECTION_SYSTEM)
            now_iso = datetime.now(timezone.utc).isoformat()

            # 1. Save Feed ETags (~10 KB)
            system_col.document("feed_etags").set({
                "feed_states_json": json.dumps(self.feed_states),
                "feed_count": len(self.feed_states),
                "last_synced_at": now_iso
            })

            # 2. Save Active 48-Hour Centroids (~30 KB)
            compact_active_stories = {}
            sorted_stories = sorted(
                self.active_stories.items(),
                key=lambda item: item[1].published_at,
                reverse=True
            )[:75]

            for k, v in sorted_stories:
                story_dict = v.model_dump()
                if story_dict.get("centroid_vector"):
                    story_dict["centroid_vector"] = [round(x, 4) for x in story_dict["centroid_vector"]]
                compact_active_stories[k] = story_dict

            system_col.document("active_centroids").set({
                "active_stories_json": json.dumps(compact_active_stories),
                "active_stories_count": len(compact_active_stories),
                "last_synced_at": now_iso
            })

            # 3. Save Seen URL Hashes (Sliding Window: Most Recent 4,000 hashes ~65 KB)
            recent_hashes = list(self.seen_url_hashes)[-4000:]
            system_col.document("seen_hashes").set({
                "seen_hashes_json": json.dumps(recent_hashes),
                "seen_hashes_count": len(self.seen_url_hashes),
                "last_synced_at": now_iso
            })

            logger.info(
                f"Saved partitioned pipeline state to Firestore (_system/feed_etags, active_centroids, seen_hashes) "
                f"[{len(recent_hashes)} hashes, {len(compact_active_stories)} active 48h debates]."
            )
        except Exception as e:
            logger.error(f"Failed to save partitioned state to Firestore: {e}")

    def _prune_expired_state(self):
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=settings.ACTIVE_STORY_WINDOW_HOURS)
        expired_keys = []
        for k, v in self.active_stories.items():
            try:
                dt = datetime.fromisoformat(v.published_at)
                if dt < cutoff:
                    expired_keys.append(k)
            except Exception:
                pass
        for k in expired_keys:
            del self.active_stories[k]

        if len(self.active_stories) > 100:
            sorted_keys = sorted(
                self.active_stories.keys(),
                key=lambda k: self.active_stories[k].published_at,
                reverse=True
            )
            for k in sorted_keys[100:]:
                del self.active_stories[k]

        # Bound in-memory seen hashes to recent 10,000 entries
        if len(self.seen_url_hashes) > 10000:
            self.seen_url_hashes = set(list(self.seen_url_hashes)[-10000:])

    def is_url_seen(self, url_hash: str) -> bool:
        return url_hash in self.seen_url_hashes

    def mark_url_seen(self, url_hash: str):
        self.seen_url_hashes.add(url_hash)

    def get_feed_state(self, feed_url: str) -> Optional[Dict[str, str]]:
        return self.feed_states.get(feed_url)

    def get_feed_etag(self, feed_url: str) -> Optional[str]:
        return self.feed_states.get(feed_url, {}).get("etag")

    def get_feed_last_modified(self, feed_url: str) -> Optional[str]:
        return self.feed_states.get(feed_url, {}).get("last_modified")

    def update_feed_state(self, feed_url: str, etag: Optional[str], last_modified: Optional[str]):
        if feed_url not in self.feed_states:
            self.feed_states[feed_url] = {}
        if etag:
            self.feed_states[feed_url]["etag"] = etag
        if last_modified:
            self.feed_states[feed_url]["last_modified"] = last_modified

    def register_article_story(self, article: ArticleModel, cluster: StoryCluster):
        self.active_stories[article.id] = ActiveStoryState(
            article_id=article.id,
            title=article.title,
            category=article.category,
            centroid_vector=cluster.centroid_vector,
            domains=list(set(p.sourceDomain for p in article.perspectives)),
            is_single_perspective=article.isSinglePerspective,
            published_at=article.publishedAt.isoformat()
        )

    def register_active_story(self, article: ArticleModel, cluster: StoryCluster):
        self.register_article_story(article, cluster)

    def get_active_stories(self) -> List[ActiveStoryState]:
        self._prune_expired_state()
        return list(self.active_stories.values())

    def get_active_stories_list(self) -> List[ActiveStoryState]:
        return self.get_active_stories()


state_manager = StateManager()
