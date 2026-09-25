"""Rate-limited, retrying HTTP client shared by source adapters (FR-SRC-009, Section 19 resilience).

* Token-bucket throttling per connector. When Redis is reachable the bucket is shared by all
  worker replicas (horizontal scaling must not multiply the upstream request rate).
* Exponential backoff with jitter on 429/5xx/timeouts; honours ``Retry-After``.
* Every response is returned as raw bytes so the ingest pipeline can retain it immutably.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import CONNECTOR_HTTP_REQUESTS

log = get_logger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class ConnectorHTTPError(Exception):
    def __init__(self, message: str, status: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.url = url


class _LocalBucket:
    def __init__(self, rate: float, burst: float):
        self.rate, self.capacity = rate, burst
        self.tokens = burst
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> float:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens >= 1:
                self.tokens -= 1
                return 0.0
            wait = (1 - self.tokens) / self.rate
            self.tokens = 0
            self.updated = now + wait
            return wait


_LUA_BUCKET = """
local key = KEYS[1]
local rate = tonumber(ARGV[1]); local cap = tonumber(ARGV[2]); local now = tonumber(ARGV[3])
local s = redis.call('HMGET', key, 't', 'u')
local tokens = tonumber(s[1]) or cap; local upd = tonumber(s[2]) or now
tokens = math.min(cap, tokens + (now - upd) * rate)
local wait = 0
if tokens >= 1 then tokens = tokens - 1 else wait = (1 - tokens) / rate; tokens = 0; now = now + wait end
redis.call('HSET', key, 't', tokens, 'u', now); redis.call('EXPIRE', key, 3600)
return tostring(wait)
"""


class RateLimiter:
    _local: dict[str, _LocalBucket] = {}
    _redis: Any = None
    _redis_checked = False

    def __init__(self, name: str, rate_per_sec: float, burst: float | None = None):
        self.name = name
        self.rate = max(rate_per_sec, 0.01)
        self.burst = burst or max(1.0, self.rate)

    @classmethod
    def _get_redis(cls) -> Any:
        if not cls._redis_checked:
            cls._redis_checked = True
            try:
                import redis

                r = redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.5)
                r.ping()
                cls._redis = r
            except Exception:  # noqa: BLE001 - fall back to per-process limiter
                cls._redis = None
        return cls._redis

    def wait(self) -> float:
        r = self._get_redis()
        if r is not None:
            try:
                wait = float(r.eval(_LUA_BUCKET, 1, f"xdata:rl:{self.name}", self.rate, self.burst, time.time()))
            except Exception:  # noqa: BLE001
                wait = self._local_wait()
        else:
            wait = self._local_wait()
        if wait > 0:
            time.sleep(wait)
        return wait

    def _local_wait(self) -> float:
        bucket = self._local.setdefault(self.name, _LocalBucket(self.rate, self.burst))
        return bucket.acquire()


@dataclass
class HttpResult:
    url: str
    status: int
    content: bytes
    content_type: str
    headers: dict[str, str]
    retrieved_at: datetime

    def json(self) -> Any:
        import json

        return json.loads(self.content)


class SourceHttpClient:
    def __init__(
        self,
        connector_key: str,
        rate_per_sec: float,
        *,
        headers: dict[str, str] | None = None,
        max_attempts: int = 5,
        base_backoff: float = 1.0,
        max_backoff: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ):
        s = get_settings()
        self.connector_key = connector_key
        self.limiter = RateLimiter(connector_key, rate_per_sec)
        self.max_attempts = max_attempts
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self.client = httpx.Client(
            timeout=s.connector_http_timeout,
            headers={"User-Agent": s.connector_user_agent, **(headers or {})},
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def _retry_after(self, resp: httpx.Response) -> float | None:
        ra = resp.headers.get("Retry-After")
        if not ra:
            return None
        try:
            return float(ra)
        except ValueError:
            try:
                return max(0.0, (parsedate_to_datetime(ra) - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError):
                return None

    def get(self, url: str, params: dict[str, Any] | None = None, *, allow_404: bool = False) -> HttpResult:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self.limiter.wait()
            try:
                resp = self.client.get(url, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                CONNECTOR_HTTP_REQUESTS.labels(self.connector_key, "transport_error").inc()
                last_exc = e
                delay = min(self.max_backoff, self.base_backoff * 2 ** (attempt - 1)) + random.uniform(0, 0.5)
                log.warning("connector_http_retry", connector=self.connector_key, url=url, attempt=attempt, error=str(e))
                time.sleep(delay)
                continue
            CONNECTOR_HTTP_REQUESTS.labels(self.connector_key, str(resp.status_code)).inc()
            if resp.status_code in RETRYABLE_STATUS and attempt < self.max_attempts:
                delay = self._retry_after(resp) or min(self.max_backoff, self.base_backoff * 2 ** (attempt - 1))
                delay += random.uniform(0, 0.5)
                log.warning(
                    "connector_http_backoff", connector=self.connector_key, status=resp.status_code, delay=round(delay, 2)
                )
                time.sleep(delay)
                continue
            if resp.status_code == 404 and allow_404:
                return HttpResult(str(resp.url), 404, b"", "", dict(resp.headers), datetime.now(UTC))
            if resp.status_code >= 400:
                raise ConnectorHTTPError(f"HTTP {resp.status_code} from {url}", resp.status_code, url)
            return HttpResult(
                url=str(resp.url),
                status=resp.status_code,
                content=resp.content,
                content_type=resp.headers.get("content-type", "application/octet-stream").split(";")[0],
                headers=dict(resp.headers),
                retrieved_at=datetime.now(UTC),
            )
        raise ConnectorHTTPError(f"exhausted retries for {url}: {last_exc}", None, url)
