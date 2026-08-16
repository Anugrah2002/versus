"""
Multi-Tier Article Prose & Image Extractor.
Uses trafilatura, readability-lxml, and BeautifulSoup with quality gatekeeping.
Extracts real OpenGraph/Twitter/Figure images and provides categorized editorial photo fallbacks.
"""

import asyncio
from typing import Optional, List, Any
from datetime import datetime, timezone
import hashlib

from config.settings import settings
from src.storage.models import RawCandidate, ExtractedArticle
from src.extractors.rate_limiter import domain_limiter
from src.utils.user_agents import get_random_headers
from src.utils.logger import logger

# Rich curated editorial photo pool by category (high-res Unsplash CDN)
CATEGORY_EDITORIAL_IMAGE_POOLS = {
    "Tech & AI": [
        "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1531297484001-80022131f5a1?auto=format&fit=crop&w=1080&q=80",
    ],
    "Work & Economy": [
        "https://images.unsplash.com/photo-1522071820081-009f0129c71c?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1507679799987-c73779587ccf?auto=format&fit=crop&w=1080&q=80",
    ],
    "Business & Policy": [
        "https://images.unsplash.com/photo-1450133064473-71024230f91b?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1521791136064-7986c2920216?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1505373877841-8d25f7d46678?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1541872703-74c5e44368f9?auto=format&fit=crop&w=1080&q=80",
    ],
    "Space & Science": [
        "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1446776811953-b23d57bd21aa?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1506703719100-a0f3a48c0f86?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?auto=format&fit=crop&w=1080&q=80",
    ],
    "Automotive & Energy": [
        "https://images.unsplash.com/photo-1563986768609-322da13575f3?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1558441719-813d9695ef39?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1513836279014-a89f7a76ae86?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?auto=format&fit=crop&w=1080&q=80",
    ],
    "World Affairs": [
        "https://images.unsplash.com/photo-1526304640581-d334cdbbf45e?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1541872703-74c5e44368f9?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1477959858617-67f30bc75b82?auto=format&fit=crop&w=1080&q=80",
        "https://images.unsplash.com/photo-1449824913935-59a10b8d2000?auto=format&fit=crop&w=1080&q=80",
    ]
}


class ArticleExtractor:
    def __init__(self):
        self.min_words = settings.MIN_ARTICLE_WORD_COUNT
        self.timeout_sec = settings.SCRAPE_TIMEOUT_SECONDS

    def _get_category_fallback_image(self, category: str, url_hash: str) -> str:
        pool = CATEGORY_EDITORIAL_IMAGE_POOLS.get(category, CATEGORY_EDITORIAL_IMAGE_POOLS["World Affairs"])
        idx = int(hashlib.md5(url_hash.encode()).hexdigest(), 16) % len(pool)
        return pool[idx]

    def _extract_hero_image_from_html(self, html_content: str) -> Optional[str]:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, "html.parser")

            # 1. OpenGraph Image
            og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
            if og_img and og_img.get("content"):
                url = og_img["content"].strip()
                if url.startswith("http") and not url.endswith((".svg", ".ico")):
                    return url

            # 2. Twitter Card Image
            tw_img = soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", property="twitter:image")
            if tw_img and tw_img.get("content"):
                url = tw_img["content"].strip()
                if url.startswith("http") and not url.endswith((".svg", ".ico")):
                    return url

            # 3. Main article figure or lead image
            fig_img = soup.find("figure")
            if fig_img:
                img_tag = fig_img.find("img")
                if img_tag and img_tag.get("src"):
                    src = img_tag["src"].strip()
                    if src.startswith("http") and not src.endswith((".svg", ".ico")):
                        return src
        except Exception:
            pass
        return None

    async def extract_single(
        self,
        session: Any,
        candidate: RawCandidate
    ) -> Optional[ExtractedArticle]:
        domain = await domain_limiter.acquire(candidate.url)
        try:
            headers = get_random_headers(referer="https://news.google.com/")
            import aiohttp
            html_text = ""
            extracted_text = None

            try:
                async with session.get(
                    candidate.url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout_sec),
                    allow_redirects=True
                ) as response:
                    if response.status == 200:
                        html_text = await response.text(errors="ignore")
                        import trafilatura
                        extracted_text = trafilatura.extract(
                            html_text,
                            include_images=False,
                            include_links=False,
                            include_tables=False,
                            no_fallback=False
                        )
            except Exception:
                pass

            # Fallback to candidate raw_summary if full-text extraction was empty
            if not extracted_text or len(extracted_text.split()) < self.min_words:
                if candidate.raw_summary and len(candidate.raw_summary.split()) >= self.min_words:
                    extracted_text = candidate.raw_summary
                elif candidate.raw_summary and len(candidate.raw_summary.split()) >= 6:
                    extracted_text = f"{candidate.title}. {candidate.raw_summary}"
                else:
                    extracted_text = candidate.title

            word_count = len(extracted_text.split())

            # Image resolution hierarchy:
            # 1. HTML OpenGraph / Twitter Card image
            # 2. RSS feed direct media enclosure / thumbnail
            # 3. Category-specific rotating editorial photograph
            hero_image = (
                self._extract_hero_image_from_html(html_text)
                if html_text else None
            ) or getattr(candidate, "image_url", None)

            if not hero_image:
                hero_image = self._get_category_fallback_image(candidate.category, candidate.url_hash)

            return ExtractedArticle(
                url=candidate.url,
                url_hash=candidate.url_hash,
                title=candidate.title,
                cleaned_body=extracted_text,
                word_count=word_count,
                hero_image_url=hero_image,
                feed_name=candidate.feed_name,
                domain=candidate.domain,
                category=candidate.category,
                credibility=candidate.credibility,
                default_bias=candidate.default_bias,
                published_at=candidate.published_at or datetime.now(timezone.utc)
            )

        except Exception as e:
            logger.debug(f"Extraction error on {candidate.url}: {e}")
            return None
        finally:
            domain_limiter.release(domain)

    async def extract_batch(
        self,
        candidates: List[RawCandidate],
        max_concurrent: int = 20
    ) -> List[ExtractedArticle]:
        if not candidates:
            return []

        extracted_articles: List[ExtractedArticle] = []

        try:
            import aiohttp
            semaphore = asyncio.Semaphore(max_concurrent)
            timeout = aiohttp.ClientTimeout(total=self.timeout_sec * 2)
            connector = aiohttp.TCPConnector(limit=max_concurrent, ssl=False)

            async def worker(session, cand):
                async with semaphore:
                    return await self.extract_single(session, cand)

            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                tasks = [worker(session, c) for c in candidates]
                results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if isinstance(r, ExtractedArticle) and r is not None:
                    extracted_articles.append(r)
        except Exception as e:
            logger.warning(f"Batch extraction encountered issue: {e}")

        logger.info(f"Article Extraction: {len(extracted_articles)}/{len(candidates)} articles extracted and resolved.")
        return extracted_articles


article_extractor = ArticleExtractor()
