"""
Mock News Feed Source for Local Testing & Unit Tests.
Generates realistic multi-source debate clusters and single verified updates.
"""

from typing import List, Any, Optional
from datetime import datetime, timezone, timedelta
import hashlib
from src.sources.base_source import BaseFeedSource
from src.storage.models import RawCandidate


class MockFeedSource(BaseFeedSource):
    def __init__(self):
        super().__init__(name="MockSource", source_type="mock")

    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    async def fetch_candidates(self, state_manager: Any, max_feeds: Optional[int] = None) -> List[RawCandidate]:
        now = datetime.now(timezone.utc)
        candidates = [
            RawCandidate(
                url="https://techcrunch.com/2026/08/ai-data-center-boom",
                canonical_url="https://techcrunch.com/2026/08/ai-data-center-boom",
                url_hash=self._hash("https://techcrunch.com/2026/08/ai-data-center-boom"),
                title="Tech Giants Invest $100B in AI Data Centers for Next-Gen Model Training",
                feed_name="TechCrunch",
                domain="techcrunch.com",
                category="Tech & AI",
                credibility=96,
                default_bias="Innovation & Growth",
                published_at=now - timedelta(minutes=40),
                raw_summary="Major technology companies are accelerating capital expenditure on massive AI compute clusters to train foundation models."
            ),
            RawCandidate(
                url="https://reuters.com/business/energy/ai-power-grid-strain-2026",
                canonical_url="https://reuters.com/business/energy/ai-power-grid-strain-2026",
                url_hash=self._hash("https://reuters.com/business/energy/ai-power-grid-strain-2026"),
                title="Surging AI Data Center Electricity Consumption Threatens Urban Power Grids",
                feed_name="Reuters",
                domain="reuters.com",
                category="Tech & AI",
                credibility=94,
                default_bias="Costs & Resources",
                published_at=now - timedelta(minutes=25),
                raw_summary="Utility regulators and energy economists warn that mega data centers could drive up consumer power bills during peak summer."
            ),
            RawCandidate(
                url="https://isro.gov.in/press-release/nisar-launch-success",
                canonical_url="https://isro.gov.in/press-release/nisar-launch-success",
                url_hash=self._hash("https://isro.gov.in/press-release/nisar-launch-success"),
                title="ISRO and NASA Successfully Place NISAR Earth Observation Satellite into Orbit",
                feed_name="ISRO Official",
                domain="isro.gov.in",
                category="Space & Science",
                credibility=99,
                default_bias="Official Update",
                published_at=now - timedelta(hours=2),
                raw_summary="The joint radar observatory will map changes in land and ice surfaces globally twice every 12 days."
            ),
            RawCandidate(
                url="https://livemint.com/news/four-day-work-week-trials-2026",
                canonical_url="https://livemint.com/news/four-day-work-week-trials-2026",
                url_hash=self._hash("https://livemint.com/news/four-day-work-week-trials-2026"),
                title="Global 4-Day Work Week Trials Show 35% Reduction in Employee Burnout",
                feed_name="LiveMint",
                domain="livemint.com",
                category="Work & Economy",
                credibility=93,
                default_bias="Wellbeing & Focus",
                published_at=now - timedelta(minutes=55),
                raw_summary="Extensive workplace trials demonstrate enhanced focus and retention without sacrificing enterprise revenue."
            ),
            RawCandidate(
                url="https://economictimes.indiatimes.com/work/4-day-week-unviable-for-factories",
                canonical_url="https://economictimes.indiatimes.com/work/4-day-week-unviable-for-factories",
                url_hash=self._hash("https://economictimes.indiatimes.com/work/4-day-week-unviable-for-factories"),
                title="Industry Leaders Warn 4-Day Week Is Unviable for 24/7 Manufacturing and Fast-Growing Startups",
                feed_name="Economic Times",
                domain="economictimes.indiatimes.com",
                category="Work & Economy",
                credibility=91,
                default_bias="Operational Reality",
                published_at=now - timedelta(minutes=15),
                raw_summary="Founders and industrial plant managers state that mandatory 4-day schedules will raise shift payrolls and reduce export output."
            )
        ]

        if max_feeds:
            candidates = candidates[:max_feeds]

        return [c for c in candidates if not state_manager.is_url_seen(c.url_hash)]
