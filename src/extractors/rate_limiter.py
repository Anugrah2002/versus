"""
Per-Domain Concurrency and Rate Limiter.
Ensures we do not exceed safe request limits on any single news publisher domain.
"""

import asyncio
import random
import time
from typing import Dict
from urllib.parse import urlparse


class DomainRateLimiter:
    def __init__(self, max_concurrent: int = 2, min_delay_ms: int = 200):
        self.max_concurrent = max_concurrent
        self.min_delay_ms = min_delay_ms
        self._domain_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._last_request_time: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _get_domain(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain or "unknown"
        except Exception:
            return "unknown"

    async def acquire(self, url: str) -> str:
        domain = self._get_domain(url)
        async with self._lock:
            if domain not in self._domain_semaphores:
                self._domain_semaphores[domain] = asyncio.Semaphore(self.max_concurrent)

        semaphore = self._domain_semaphores[domain]
        await semaphore.acquire()

        # Enforce polite delay between requests to same domain with randomized jitter
        async with self._lock:
            last_time = self._last_request_time.get(domain, 0)
            now = time.time()
            elapsed_ms = (now - last_time) * 1000.0
            jitter = random.randint(50, 150)
            target_delay_ms = self.min_delay_ms + jitter

            if elapsed_ms < target_delay_ms:
                wait_time_sec = (target_delay_ms - elapsed_ms) / 1000.0
                await asyncio.sleep(wait_time_sec)

            self._last_request_time[domain] = time.time()

        return domain

    def release(self, domain: str):
        if domain in self._domain_semaphores:
            self._domain_semaphores[domain].release()


# Global domain rate limiter instance
domain_limiter = DomainRateLimiter()
