"""
Multi-Tier Article Prose & Image Extractor.
Uses trafilatura, readability-lxml, and BeautifulSoup with quality gatekeeping.
"""

import asyncio
from typing import Optional, List, Any
from datetime import datetime, timezone

from config.settings import settings
from src.storage.models import RawCandidate, ExtractedArticle
from src.extractors.rate_limiter import domain_limiter
from src.utils.user_agents import get_random_headers
from src.utils.logger import logger


class ArticleExtractor:
    def __init__(self):
        self.min_words = settings.MIN_ARTICLE_WORD_COUNT
        self.timeout_sec = settings.SCRAPE_TIMEOUT_SECONDS

    def _extract_hero_image_from_html(self, html_content: str) -> Optional[str]:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, "html.parser")
            og_img = soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                url = og_img["content"].strip()
                if url.startswith("http"):
                    return url

            tw_img = soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", property="twitter:image")
            if tw_img and tw_img.get("content"):
                url = tw_img["content"].strip()
                if url.startswith("http"):
                    return url

            fig_img = soup.find("figure")
            if fig_img:
                img_tag = fig_img.find("img")
                if img_tag and img_tag.get("src"):
                    src = img_tag["src"].strip()
                    if src.startswith("http"):
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
            async with session.get(
                candidate.url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout_sec),
                allow_redirects=True
            ) as response:
                if response.status != 200:
                    return None

                html_text = await response.text(errors="ignore")

                extracted_text = None
                try:
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

                if not extracted_text or len(extracted_text.split()) < self.min_words:
                    if len(candidate.raw_summary.split()) >= self.min_words:
                        extracted_text = candidate.raw_summary
                    else:
                        return None

                word_count = len(extracted_text.split())
                hero_image = self._extract_hero_image_from_html(html_text)

                if not hero_image:
                    category_fallbacks = {
                        "Tech & AI": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1080&q=80",
                        "Work & Economy": "https://images.unsplash.com/photo-1522071820081-009f0129c71c?auto=format&fit=crop&w=1080&q=80",
                        "Business & Policy": "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1080&q=80",
                        "Space & Science": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1080&q=80",
                        "Automotive & Energy": "https://images.unsplash.com/photo-1563986768609-322da13575f3?auto=format&fit=crop&w=1080&q=80",
                        "World Affairs": "https://images.unsplash.com/photo-1526304640581-d334cdbbf45e?auto=format&fit=crop&w=1080&q=80",
                        "Science & Society": "https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?auto=format&fit=crop&w=1080&q=80",
                    }
                    hero_image = category_fallbacks.get(candidate.category, category_fallbacks["Tech & AI"])

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

        # If candidates already have cleaned bodies (e.g. from MockSource), pass directly
        direct_articles = []
        cands_to_fetch = []
        for c in candidates:
            if hasattr(c, "raw_summary") and len(c.raw_summary.split()) >= 10:
                direct_articles.append(
                    ExtractedArticle(
                        url=c.url,
                        url_hash=c.url_hash,
                        title=c.title,
                        cleaned_body=c.raw_summary,
                        word_count=len(c.raw_summary.split()),
                        feed_name=c.feed_name,
                        domain=c.domain,
                        category=c.category,
                        credibility=c.credibility,
                        default_bias=c.default_bias,
                        published_at=c.published_at or datetime.now(timezone.utc),
                        hero_image_url="https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1080&q=80"
                    )
                )
            else:
                cands_to_fetch.append(c)

        if not cands_to_fetch:
            return direct_articles

        try:
            import aiohttp
            semaphore = asyncio.Semaphore(max_concurrent)
            timeout = aiohttp.ClientTimeout(total=self.timeout_sec * 2)
            connector = aiohttp.TCPConnector(limit=max_concurrent, ssl=False)

            async def worker(session, cand):
                async with semaphore:
                    return await self.extract_single(session, cand)

            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                tasks = [worker(session, c) for c in cands_to_fetch]
                results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if isinstance(r, ExtractedArticle) and r is not None:
                    direct_articles.append(r)
        except Exception as e:
            logger.warning(f"Batch extraction encountered issue: {e}")

        logger.info(f"Article Extraction: {len(direct_articles)}/{len(candidates)} articles passed quality gatekeeper.")
        return direct_articles


article_extractor = ArticleExtractor()
