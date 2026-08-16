"""
State Manager for Seen URLs, ETags, and Active Story Centroids.
Syncs with Firestore _system collection in production or local JSON file in development.
Enables GitHub Actions stateless runners to retain state across 30-minute cron executions.
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
                "seen_hashes": list(self.seen_url_hashes),
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
        if not self._firestore_db:
            return
        try:
            doc_ref = self._firestore_db.collection(settings.FIRESTORE_COLLECTION_SYSTEM).document("pipeline_state")
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict() or {}
                # Load seen_hashes (supports both JSON string and legacy array)
                if "seen_hashes_json" in data:
                    try:
                        self.seen_url_hashes.update(json.loads(data["seen_hashes_json"]))
                    except Exception:
                        pass
                elif "seen_hashes" in data:
                    self.seen_url_hashes.update(data.get("seen_hashes", []))

                # Load feed_states
                if "feed_states_json" in data:
                    try:
                        self.feed_states.update(json.loads(data["feed_states_json"]))
                    except Exception:
                        pass
                else:
                    self.feed_states.update(data.get("feed_states", {}))

                # Load active_stories
                if "active_stories_json" in data:
                    try:
                        stories_data = json.loads(data["active_stories_json"])
                        for k, v in stories_data.items():
                            self.active_stories[k] = ActiveStoryState(**v)
                    except Exception:
                        pass
                elif "active_stories" in data:
                    stories_data = data.get("active_stories", {})
                    for k, v in stories_data.items():
                        self.active_stories[k] = ActiveStoryState(**v)

                logger.info(
                    f"Synced pipeline state from Firestore: {len(self.seen_url_hashes)} seen hashes, "
                    f"{len(self.active_stories)} active stories."
                )
        except Exception as e:
            logger.warning(f"Could not load state from Firestore ({e}). Using local state.")

    def save_to_firestore(self):
        if not self._firestore_db or settings.DRY_RUN:
            return
        try:
            self._prune_expired_state()
            doc_ref = self._firestore_db.collection(settings.FIRESTORE_COLLECTION_SYSTEM).document("pipeline_state")
            recent_hashes = list(self.seen_url_hashes)[-3000:]
            
            # Compact active stories: round centroid vector floats to 4 decimals and cap to most recent 75
            compact_active_stories = {}
            # Sort active stories by published_at desc
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

            # Store state as compact JSON strings (< 200 KB total, far below Firestore 1MB document limit)
            payload = {
                "seen_hashes_json": json.dumps(recent_hashes),
                "feed_states_json": json.dumps(self.feed_states),
                "active_stories_json": json.dumps(compact_active_stories),
                "seen_hashes_count": len(self.seen_url_hashes),
                "active_stories_count": len(compact_active_stories),
                "last_synced_at": datetime.now(timezone.utc).isoformat()
            }
            doc_ref.set(payload)
            logger.info(
                f"Saved pipeline state to Firestore _system/pipeline_state "
                f"({len(recent_hashes)} hashes, {len(compact_active_stories)} active stories, ~{len(json.dumps(payload)) // 1024} KB)."
            )
        except Exception as e:
            logger.error(f"Failed to save state to Firestore: {e}")

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

        # Ensure active_stories memory footprint is bounded
        if len(self.active_stories) > 100:
            sorted_keys = sorted(
                self.active_stories.keys(),
                key=lambda k: self.active_stories[k].published_at,
                reverse=True
            )
            for k in sorted_keys[100:]:
                del self.active_stories[k]

    def is_url_seen(self, url_hash: str) -> bool:
        return url_hash in self.seen_url_hashes

    def mark_url_seen(self, url_hash: str):
        self.seen_url_hashes.add(url_hash)

    def get_feed_state(self, feed_url: str) -> Optional[Dict[str, str]]:
        return self.feed_states.get(feed_url)

    def update_feed_state(self, feed_url: str, etag: Optional[str] = None, last_modified: Optional[str] = None):
        state = self.feed_states.setdefault(feed_url, {})
        if etag:
            state["etag"] = etag
        if last_modified:
            state["last_modified"] = last_modified

    def register_active_story(self, article: ArticleModel, cluster: StoryCluster):
        if not cluster.centroid_vector:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        domains = list(set(a.domain for a in cluster.articles))
        self.active_stories[article.id] = ActiveStoryState(
            article_id=article.id,
            title=article.title,
            category=article.category,
            divergence_score=article.divergenceScore,
            is_single_perspective=article.isSinglePerspective,
            centroid_vector=cluster.centroid_vector,
            published_at=article.publishedAt,
            domains=domains,
            last_updated_at=now_iso
        )

    def get_active_stories_list(self) -> List[ActiveStoryState]:
        self._prune_expired_state()
        return list(self.active_stories.values())


state_manager = StateManager()
