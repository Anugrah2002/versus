"""
Twitter / X Ingestion Source (Extensible Plugin Stub).
Ready for integration with Twitter API v2, syndication endpoints, or RapidAPI/Nitter.
"""

from typing import List, Any
from .base_source import BaseFeedSource
from ..storage.models import RawCandidate
from ..utils.logger import logger


class TwitterFeedSource(BaseFeedSource):
    def __init__(self, bearer_token: str = ""):
        super().__init__(name="TwitterSource", source_type="twitter")
        self.bearer_token = bearer_token

    async def fetch_candidates(self, state_manager: Any) -> List[RawCandidate]:
        """
        Fetches curated lists or keyword queries from Twitter/X.
        Returns candidates formatted as RawCandidate for the clustering engine.
        """
        if not self.bearer_token:
            logger.debug("Twitter source skipped (no BEARER_TOKEN provided).")
            return []

        # Future implementation: Query Twitter API / Lists
        return []
