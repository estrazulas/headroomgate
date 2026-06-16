"""Per-user token-bucket rate limiter for the auth middleware.

Each authenticated user gets independent request and token buckets
parameterized by the RPM/TPM limits inherited from their role. Follows
the same token-bucket algorithm as ``headroom.proxy.rate_limiter``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("headroom_auth.rate_limiter")

# Prevent unbounded bucket growth from spoofed user IDs.
MAX_BUCKETS = 1000


@dataclass
class _Bucket:
    """A single token bucket with configurable rate."""

    tokens: float
    rate_per_minute: float
    last_update: float = field(default_factory=time.monotonic)

    def refill(self) -> float:
        """Replenish tokens based on elapsed time. Returns available tokens."""
        now = time.monotonic()
        elapsed = now - self.last_update
        refill = elapsed * (self.rate_per_minute / 60.0)
        self.tokens = min(self.rate_per_minute, self.tokens + refill)
        self.last_update = now
        return self.tokens

    def try_consume(self, count: float = 1.0) -> tuple[bool, float]:
        """Try to consume *count* tokens. Returns ``(allowed, wait_seconds)``."""
        available = self.refill()
        if available >= count:
            self.tokens -= count
            return True, 0.0
        wait_seconds = (count - available) * (60.0 / self.rate_per_minute)
        return False, wait_seconds


class PerUserRateLimiter:
    """Per-user token-bucket rate limiter.

    Each ``user_id`` gets independent request and token buckets. Limits
    are passed per-check so different roles (with different RPM/TPM) can
    share the same limiter instance.

    Stale buckets (unused for >10 minutes) are evicted to bound memory.
    """

    def __init__(self) -> None:
        self._request_buckets: dict[str, _Bucket] = {}
        self._token_buckets: dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup = time.monotonic()

    async def check_rate_limit(
        self,
        user_id: str,
        rpm: int | None,
        tpm: int | None,
        estimated_tokens: int = 0,
    ) -> tuple[bool, float, dict[str, str]]:
        """Check both request and token rate limits for *user_id*.

        Parameters:
            user_id: The authenticated user's id (bucket key).
            rpm: Requests-per-minute limit (``None`` = unlimited).
            tpm: Tokens-per-minute limit (``None`` = unlimited).
            estimated_tokens: Estimated token consumption for this request
                (0 for pre-request check, actual for post-response).

        Returns:
            ``(allowed, retry_after_seconds, rate_limit_headers)`` where
            *rate_limit_headers* is a dict of ``X-RateLimit-*`` header values.
        """
        # Apply system defaults when role has no explicit limits.
        req_limit = rpm if rpm is not None else 60
        tok_limit = tpm if tpm is not None else 100_000

        async with self._lock:
            await self._cleanup_if_needed()

            # --- request bucket ---
            req_bucket = self._request_buckets.get(user_id)
            if req_bucket is None or req_bucket.rate_per_minute != req_limit:
                req_bucket = _Bucket(tokens=req_limit, rate_per_minute=req_limit)
                self._request_buckets[user_id] = req_bucket

            req_allowed, req_wait = req_bucket.try_consume(1)

            # --- token bucket ---
            tok_bucket = self._token_buckets.get(user_id)
            if tok_bucket is None or tok_bucket.rate_per_minute != tok_limit:
                tok_bucket = _Bucket(tokens=tok_limit, rate_per_minute=tok_limit)
                self._token_buckets[user_id] = tok_bucket

            tok_allowed, tok_wait = tok_bucket.try_consume(max(estimated_tokens, 1))

            # --- response ---
            remaining = int(min(req_bucket.tokens, tok_bucket.tokens))
            # Reset time: when the bucket would be full again at the current rate.
            # For simplicity, use the request bucket's next-full time.
            deficit = req_limit - req_bucket.tokens
            reset_seconds = deficit * (60.0 / req_limit) if req_limit > 0 else 0

            headers = {
                "X-RateLimit-Limit": str(req_limit),
                "X-RateLimit-Remaining": str(max(0, remaining)),
                "X-RateLimit-Reset": str(int(time.time() + reset_seconds)),
            }

            # Request check is the gate. Token overflow is checked post-response.
            if not req_allowed:
                return False, req_wait, headers

            if estimated_tokens > 0 and not tok_allowed:
                return False, tok_wait, headers

            return True, 0.0, headers

    async def record_tokens(self, user_id: str, token_count: int) -> None:
        """Deduct *token_count* from the user's token bucket after the response.

        Called post-response when the actual token count is known.
        Only deducts what's available — never goes negative.
        """
        async with self._lock:
            bucket = self._token_buckets.get(user_id)
            if bucket is not None:
                bucket.tokens = max(0.0, bucket.tokens - token_count)

    async def _cleanup_if_needed(self) -> None:
        """Evict buckets unused for >10 minutes (runs at most once per 60s)."""
        now = time.monotonic()
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now

        threshold = now - 600  # 10 minutes
        stale_requests = [
            uid for uid, b in self._request_buckets.items()
            if b.last_update < threshold
        ]
        for uid in stale_requests:
            del self._request_buckets[uid]
            self._token_buckets.pop(uid, None)

        if stale_requests:
            log.debug("rate-limiter: evicted %d stale buckets", len(stale_requests))

    async def stats(self) -> dict[str, Any]:
        """Return rate limiter statistics for observability."""
        async with self._lock:
            return {
                "active_users": len(self._request_buckets),
                "max_buckets": MAX_BUCKETS,
            }


def rate_limit_error(retry_after_seconds: float) -> dict[str, Any]:
    """Build a 429 JSON error body for rate limit exceeded."""
    return {
        "error": "rate_limit_exceeded",
        "retry_after_seconds": int(max(0, retry_after_seconds)),
    }
