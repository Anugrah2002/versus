"""
High-Scale Asynchronous RSS Feed Ingestion Source.
Implements ETag / If-Modified-Since HTTP conditional caching, URL hash deduplication,
and concurrency control across 100-500+ feeds.
"""

import asyncio
import hashlib
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from pathlib import Path

from config.settings import settings
from src.sources.base_source import BaseFeedSource
from src.storage.models import RawCandidate, FeedDefinition
from src.extractors.rate_limiter import domain_limiter
from src.utils.user_agents import get_random_headers
from src.utils.logger import logger


class RSSFeedSource(BaseFeedSource):
    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="RSSMasterSource", source_type="rss")
        self.config_path = config_path or settings.FEEDS_CONFIG_PATH
        self.feeds: List[FeedDefinition] = self._load_feeds()
        self.feeds_with_304 = 0

    def _load_feeds(self) -> List[FeedDefinition]:
        path = Path(self.config_path)
        if not path.exists():
            logger.warning(f"Feeds config file not found at {path}. Using empty feed list.")
            return []

        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                feed_list = data.get("feeds", [])
                loaded = [FeedDefinition(**f) for f in feed_list]
                logger.info(f"Loaded {len(loaded)} RSS feeds from {path}")
                return loaded
        except Exception:
            return []

    def _normalize_url(self, raw_url: str) -> str:
        try:
            from yarl import URL
            parsed = URL(raw_url)
            clean_query = {
                k: v for k, v in parsed.query.items()
                if not k.startswith("utm_") and k not in ("fbclid", "ref", "source", "feed", "rss")
            }
            return str(parsed.with_query(clean_query))
        except Exception:
            return raw_url.strip().split("?")[0]

    def _generate_url_hash(self, canonical_url: str) -> str:
        return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:16]

    async def _fetch_single_feed(
        self,
        session: Any,
        feed: FeedDefinition,
        state_manager: Any,
        semaphore: asyncio.Semaphore
    ) -> List[RawCandidate]:
        async with semaphore:
            domain = await domain_limiter.acquire(feed.url)
            candidates: List[RawCandidate] = []

            try:
                import aiohttp
                import feedparser
                headers = get_random_headers(referer="https://news.google.com/")
                
                cached_state = state_manager.get_feed_state(feed.url)
                if cached_state:
                    if cached_state.get("etag"):
                        headers["If-None-Match"] = cached_state["etag"]
                    if cached_state.get("last_modified"):
                        headers["If-Modified-Since"] = cached_state["last_modified"]

                async with session.get(
                    feed.url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=settings.SCRAPE_TIMEOUT_SECONDS),
                    allow_redirects=True
                ) as response:
                    if response.status == 304:
                        self.feeds_with_304 += 1
                        return []

                    if response.status != 200:
                        logger.debug(f"Feed {feed.name} returned status {response.status}")
                        return []

                    new_etag = response.headers.get("ETag")
                    new_last_modified = response.headers.get("Last-Modified")
                    if new_etag or new_last_modified:
                        state_manager.update_feed_state(
                            feed.url,
                            etag=new_etag,
                            last_modified=new_last_modified
                        )

                    body_bytes = await response.read()
                    parsed = feedparser.parse(body_bytes)

                    for entry in parsed.entries[:15]:
                        link = entry.get("link")
                        if not link:
                            continue

                        canonical_url = self._normalize_url(link)
                        url_hash = self._generate_url_hash(canonical_url)

                        if state_manager.is_url_seen(url_hash):
                            continue

                        title = entry.get("title", "").strip()
                        if not title:
                            continue

                        published_at = None
                        if hasattr(entry, "published_parsed") and entry.published_parsed:
                            published_at = datetime.fromtimestamp(
                                time.mktime(entry.published_parsed),
                                tz=timezone.utc
                            )
                        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                            published_at = datetime.fromtimestamp(
                                time.mktime(entry.updated_parsed),
                                tz=timezone.utc
                            )
                        else:
                            published_at = datetime.now(timezone.utc)

                        raw_summary = entry.get("summary", entry.get("description", ""))

                        # Extract image from RSS media_content, media_thumbnail, enclosures, or img tags
                        rss_image_url = None
                        if entry.get("media_content"):
                            rss_image_url = entry.get("media_content", [{}])[0].get("url")
                        elif entry.get("media_thumbnail"):
                            rss_image_url = entry.get("media_thumbnail", [{}])[0].get("url")
                        elif entry.get("enclosures"):
                            for enc in entry.get("enclosures", []):
                                if "image" in enc.get("type", "").lower() or enc.get("href", "").lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                                    rss_image_url = enc.get("href")
                                    break

                        if not rss_image_url and raw_summary:
                            img_match = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', raw_summary, re.IGNORECASE)
                            if img_match:
                                rss_image_url = img_match.group(1)

                        candidates.append(
                            RawCandidate(
                                url=link,
                                canonical_url=canonical_url,
                                url_hash=url_hash,
                                title=title,
                                feed_name=feed.name,
                                domain=feed.domain,
                                category=feed.category,
                                credibility=feed.credibility,
                                default_bias=feed.defaultBias,
                                published_at=published_at,
                                raw_summary=raw_summary,
                                image_url=rss_image_url
                            )
                        )

            except Exception as e:
                logger.debug(f"Error fetching feed {feed.name}: {e}")
            finally:
                domain_limiter.release(domain)

            return candidates

    async def fetch_candidates(self, state_manager: Any, max_feeds: Optional[int] = None) -> List[RawCandidate]:
        self.feeds_with_304 = 0
        feeds_to_fetch = self.feeds[:max_feeds] if max_feeds else self.feeds
        if not feeds_to_fetch:
            return []

        try:
            import aiohttp
            semaphore = asyncio.Semaphore(settings.MAX_FEEDS_CONCURRENT)
            timeout = aiohttp.ClientTimeout(total=settings.SCRAPE_TIMEOUT_SECONDS * 2)
            connector = aiohttp.TCPConnector(limit=settings.MAX_FEEDS_CONCURRENT, ssl=False)

            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                tasks = [
                    self._fetch_single_feed(session, feed, state_manager, semaphore)
                    for feed in feeds_to_fetch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

            all_candidates: List[RawCandidate] = []
            for res in results:
                if isinstance(res, list):
                    all_candidates.extend(res)

            logger.info(
                f"RSS Ingestion complete: Checked {len(feeds_to_fetch)} feeds ({self.feeds_with_304} 304-cached). "
                f"Found {len(all_candidates)} new candidate articles."
            )
            return all_candidates
        except Exception as e:
            logger.warning(f"Live RSS fetching skipped (aiohttp/feedparser not installed): {e}")
            return []
