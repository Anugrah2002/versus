"""
Threads / Bluesky Ingestion Source (Extensible Plugin Stub).
Ready for integration with Meta Threads API / AT Protocol for Bluesky.
"""

from typing import List, Any
from .base_source import BaseFeedSource
from ..storage.models import RawCandidate
from ..utils.logger import logger


class ThreadsFeedSource(BaseFeedSource):
    def __init__(self, api_token: str = ""):
        super().__init__(name="ThreadsSource", source_type="threads")
        self.api_token = api_token

    async def fetch_candidates(self, state_manager: Any) -> List[RawCandidate]:
        """
        Fetches trending posts or curated topic threads from Meta Threads / Bluesky.
        """
        if not self.api_token:
            logger.debug("Threads source skipped (no API token provided).")
            return []

        # Future implementation: Query Threads API / Bluesky firehose
        return []
