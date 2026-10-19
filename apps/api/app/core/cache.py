"""Cache + rate limiting: Redis when REDIS_URL is set, in-process memory otherwise.

Used for (1) the dashboard aggregate (heavy-ish SQL, short TTL, invalidated on writes) and (2) per-user
rate limits on endpoints that spend LLM tokens. Cache failures never fail a request: a broken Redis
degrades to "cache miss" / "allow".
"""

from __future__ import annotations

import abc
import json
import logging
import time
from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode

logger = logging.getLogger(__name__)


class Cache(abc.ABC):
    backend: str

    @abc.abstractmethod
    async def get(self, key: str) -> Any | None: ...

    @abc.abstractmethod
    async def set(self, key: str, value: Any, ttl: int) -> None: ...

    @abc.abstractmethod
    async def delete_prefix(self, prefix: str) -> None: ...

    @abc.abstractmethod
    async def incr_window(self, key: str, window_seconds: int) -> int:
        """Increment a fixed-window counter and return the new count."""


class MemoryCache(Cache):
    backend = "memory"

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}

    async def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None or item[0] < time.monotonic():
            self._data.pop(key, None)
            return None
        return item[1]

    async def set(self, key: str, value: Any, ttl: int) -> None:
        self._data[key] = (time.monotonic() + ttl, value)

    async def delete_prefix(self, prefix: str) -> None:
        for k in [k for k in self._data if k.startswith(prefix)]:
            self._data.pop(k, None)

    async def incr_window(self, key: str, window_seconds: int) -> int:
        bucket = f"{key}:{int(time.time() // window_seconds)}"
        count = int(await self.get(bucket) or 0) + 1
        await self.set(bucket, count, window_seconds)
        return count


class RedisCache(Cache):
    backend = "redis"

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # noqa: PLC0415

        self._r = redis.from_url(url, decode_responses=True, socket_timeout=1.0, socket_connect_timeout=1.0)

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._r.get(key)
            return json.loads(raw) if raw is not None else None
        except Exception:  # noqa: BLE001
            logger.warning("redis get failed", exc_info=True)
            return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        try:
            await self._r.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception:  # noqa: BLE001
            logger.warning("redis set failed", exc_info=True)

    async def delete_prefix(self, prefix: str) -> None:
        try:
            async for key in self._r.scan_iter(match=f"{prefix}*", count=200):
                await self._r.delete(key)
        except Exception:  # noqa: BLE001
            logger.warning("redis delete failed", exc_info=True)

    async def incr_window(self, key: str, window_seconds: int) -> int:
        bucket = f"{key}:{int(time.time() // window_seconds)}"
        try:
            async with self._r.pipeline(transaction=True) as pipe:
                count, _ = await pipe.incr(bucket).expire(bucket, window_seconds).execute()
            return int(count)
        except Exception:  # noqa: BLE001 - fail open: rate limiting is protection, not correctness
            logger.warning("redis incr failed", exc_info=True)
            return 0


@lru_cache
def get_cache() -> Cache:
    url = get_settings().redis_url
    return RedisCache(url) if url else MemoryCache()


async def rate_limit(user_key: str, bucket: str, *, limit: int, window_seconds: int = 60) -> None:
    """Raise LLM_RATE_LIMITED (429) when a user exceeds `limit` calls per window for `bucket`."""
    count = await get_cache().incr_window(f"rl:{bucket}:{user_key}", window_seconds)
    if count > limit:
        raise AppError(
            ErrorCode.LLM_RATE_LIMITED,
            f"Too many {bucket} requests: limit is {limit} per {window_seconds}s",
            remediation="Wait a minute and try again.",
        )


def dashboard_key(company_id: object) -> str:
    return f"dash:{company_id}"


async def invalidate_company(company_id: object) -> None:
    await get_cache().delete_prefix(dashboard_key(company_id))
