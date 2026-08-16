"""
Abstract Base Source interface for multi-source news and social media ingestion.
Enables pluggable addition of RSS feeds, Twitter/X, Threads, Reddit, Bluesky, etc.
"""

from abc import ABC, abstractmethod
from typing import List, Any, Optional
from src.storage.models import RawCandidate


class BaseFeedSource(ABC):
    def __init__(self, name: str, source_type: str = "rss"):
        self.name = name
        self.source_type = source_type

    @abstractmethod
    async def fetch_candidates(self, state_manager: Any, max_feeds: Optional[int] = None) -> List[RawCandidate]:
        pass
