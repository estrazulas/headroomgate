"""Unit tests for per-user rate limiter (PRD 2 tasks 5.1-5.3)."""

import asyncio

import pytest

from headroom_auth.rate_limiter import PerUserRateLimiter, rate_limit_error


class TestPerUserRateLimiter:
    """Per-user_id token bucket rate limiting."""

    @pytest.fixture
    def limiter(self) -> PerUserRateLimiter:
        return PerUserRateLimiter()

    async def test_allows_first_request(self, limiter: PerUserRateLimiter) -> None:
        allowed, wait, headers = await limiter.check_rate_limit("u_1", rpm=60, tpm=100_000)
        assert allowed is True
        assert wait == 0.0
        assert headers["X-RateLimit-Limit"] == "60"

    async def test_headers_include_remaining_and_reset(self, limiter: PerUserRateLimiter) -> None:
        allowed, wait, headers = await limiter.check_rate_limit("u_1", rpm=60, tpm=100_000)
        assert "X-RateLimit-Remaining" in headers
        assert "X-RateLimit-Reset" in headers
        assert int(headers["X-RateLimit-Limit"]) == 60

    async def test_independent_buckets_per_user(self, limiter: PerUserRateLimiter) -> None:
        # Exhaust user A's bucket
        for _ in range(60):
            await limiter.check_rate_limit("u_a", rpm=60, tpm=100_000)
        allowed_a, _, _ = await limiter.check_rate_limit("u_a", rpm=60, tpm=100_000)
        assert allowed_a is False

        # User B should still be allowed
        allowed_b, _, _ = await limiter.check_rate_limit("u_b", rpm=60, tpm=100_000)
        assert allowed_b is True

    async def test_role_level_limits(self, limiter: PerUserRateLimiter) -> None:
        # Intern role has lower limits
        for _ in range(19):
            await limiter.check_rate_limit("intern", rpm=20, tpm=30_000)
        allowed, _, _ = await limiter.check_rate_limit("intern", rpm=20, tpm=30_000)
        assert allowed is True  # 20th request
        allowed, _, _ = await limiter.check_rate_limit("intern", rpm=20, tpm=30_000)
        assert allowed is False  # 21st request exceeds

    async def test_default_limits_when_role_has_none(self, limiter: PerUserRateLimiter) -> None:
        # rpm=None should use default 60
        allowed, _, headers = await limiter.check_rate_limit("u_none", rpm=None, tpm=None)
        assert allowed is True
        assert headers["X-RateLimit-Limit"] == "60"

    async def test_rate_limit_exceeded_returns_false_with_retry(self, limiter: PerUserRateLimiter) -> None:
        # Exhaust bucket
        for _ in range(60):
            await limiter.check_rate_limit("u_full", rpm=60, tpm=100_000)
        allowed, retry, headers = await limiter.check_rate_limit("u_full", rpm=60, tpm=100_000)
        assert allowed is False
        assert retry > 0

    async def test_rate_limit_error_format(self) -> None:
        err = rate_limit_error(15)
        assert err["error"] == "rate_limit_exceeded"
        assert err["retry_after_seconds"] == 15

    async def test_rate_limit_error_non_negative(self) -> None:
        err = rate_limit_error(-5)
        assert err["retry_after_seconds"] >= 0

    async def test_stats_reports_active_users(self, limiter: PerUserRateLimiter) -> None:
        await limiter.check_rate_limit("u_1", rpm=60, tpm=100_000)
        await limiter.check_rate_limit("u_2", rpm=60, tpm=100_000)
        stats = await limiter.stats()
        assert stats["active_users"] == 2
