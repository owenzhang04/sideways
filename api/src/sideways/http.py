"""Shared HTTP plumbing: per-host rate limits, retries with backoff, cached GETs."""

import asyncio
import logging
import random
import time
from typing import Any

import httpx

from sideways.cache import Cache

log = logging.getLogger(__name__)


class UpstreamError(Exception):
    """An upstream service failed after retries."""


class RateLimiter:
    """Spaces request starts so one process stays under a requests-per-second budget."""

    def __init__(self, per_second: float) -> None:
        self.interval = 1.0 / per_second
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            await asyncio.sleep(delay)


RETRY_STATUSES = {429, 500, 502, 503, 504}


class Upstream:
    """One external service: base URL, rate limit, retries, and an optional response cache."""

    def __init__(
        self,
        name: str,
        client: httpx.AsyncClient,
        cache: Cache | None,
        per_second: float,
        attempts: int = 3,
    ) -> None:
        self.name = name
        self.client = client
        self.cache = cache
        self.limiter = RateLimiter(per_second)
        self.attempts = attempts

    async def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        ttl: float = 0,
        headers: dict | None = None,
    ) -> Any:
        key = f"{self.name}:{url}?{sorted((params or {}).items())}"
        if ttl and self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return hit
        data = await self.request("GET", url, params=params, headers=headers)
        if ttl and self.cache is not None:
            self.cache.set(key, data, ttl)
        return data

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        last: Exception | None = None
        for attempt in range(self.attempts):
            await self.limiter.wait()
            try:
                resp = await self.client.request(method, url, **kwargs)
            except httpx.TransportError as e:
                last = e
            else:
                if resp.status_code not in RETRY_STATUSES:
                    if resp.status_code >= 400:
                        raise UpstreamError(f"{self.name} {resp.status_code}: {resp.text[:200]}")
                    return resp.json() if resp.content else None
                last = UpstreamError(f"{self.name} {resp.status_code}")
                retry_after = resp.headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    await asyncio.sleep(min(int(retry_after), 10))
                    continue
            await asyncio.sleep(0.5 * 2**attempt + random.random() * 0.25)
        log.warning("%s failed after %d attempts: %s", self.name, self.attempts, last)
        raise UpstreamError(f"{self.name} unavailable: {last}")
