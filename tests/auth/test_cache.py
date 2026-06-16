"""Unit tests for AuthCache (PRD 2 tasks 2.1-2.3)."""

import asyncio
import hashlib
import time

import pytest

from headroom_auth.cache import AuthCache, CachedIdentity


class TestCachedIdentity:
    """CachedIdentity construction and defaults."""

    def test_identity_defaults(self) -> None:
        ident = CachedIdentity(
            user_id="u_test", username="joao", role="developer", team="backend"
        )
        assert ident.user_id == "u_test"
        assert ident.username == "joao"
        assert ident.role == "developer"
        assert ident.team == "backend"
        assert ident.provider_keys == {}
        assert ident.default_rpm is None
        assert ident.default_tpm is None
        assert ident.cached_at > 0

    def test_identity_with_provider_keys(self) -> None:
        ident = CachedIdentity(
            user_id="u_1",
            username="maria",
            role="admin",
            team="platform",
            provider_keys={"anthropic": "sk-ant-test", "openai": "sk-proj-test"},
            default_rpm=120,
            default_tpm=200_000,
        )
        assert ident.provider_keys["anthropic"] == "sk-ant-test"
        assert ident.provider_keys["openai"] == "sk-proj-test"
        assert ident.default_rpm == 120
        assert ident.default_tpm == 200_000

    def test_last_accessed_updates_on_access(self) -> None:
        ident = CachedIdentity(user_id="u_1", username="a", role="dev", team="t")
        first_access = ident.last_accessed
        time.sleep(0.001)
        # Simulate what AuthCache.get() does
        ident.last_accessed = time.monotonic()
        assert ident.last_accessed > first_access


class TestAuthCache:
    """AuthCache TTL, stale fallback, and cleanup."""

    @pytest.fixture
    def cache(self) -> AuthCache:
        return AuthCache(ttl_seconds=10, stale_grace_seconds=300)

    def _kh(self, key: str) -> str:
        return hashlib.sha256(key.encode("ascii")).hexdigest()

    def _ident(self, username: str = "joao") -> CachedIdentity:
        return CachedIdentity(
            user_id=f"u_{username}",
            username=username,
            role="developer",
            team="backend",
            provider_keys={"anthropic": "sk-ant-test"},
        )

    async def test_cache_hit(self, cache: AuthCache) -> None:
        kh = self._kh("hr_test_key")
        ident = self._ident()
        await cache.set(kh, ident)

        cached = await cache.get(kh)
        assert cached is not None
        assert cached.username == "joao"
        assert cached.provider_keys == {"anthropic": "sk-ant-test"}

    async def test_cache_miss_empty(self, cache: AuthCache) -> None:
        kh = self._kh("hr_nonexistent")
        assert await cache.get(kh) is None

    async def test_cache_size_tracks_entries(self, cache: AuthCache) -> None:
        assert cache.size == 0
        await cache.set(self._kh("k1"), self._ident("a"))
        await cache.set(self._kh("k2"), self._ident("b"))
        assert cache.size == 2

    async def test_ttl_expiry(self, cache: AuthCache) -> None:
        # Use a very short TTL for testing
        short_cache = AuthCache(ttl_seconds=0)  # expires immediately
        kh = self._kh("hr_fast_expire")
        await short_cache.set(kh, self._ident())
        cached = await short_cache.get(kh)
        assert cached is None  # already expired

    async def test_ttl_not_expired(self, cache: AuthCache) -> None:
        kh = self._kh("hr_fresh")
        await cache.set(kh, self._ident())
        cached = await cache.get(kh)
        assert cached is not None  # 10s TTL, just stored

    async def test_stale_fallback_on_expired(self, cache: AuthCache) -> None:
        short_cache = AuthCache(ttl_seconds=0)
        kh = self._kh("hr_stale")
        await short_cache.set(kh, self._ident())
        # get() returns None (expired), but get_stale() returns the entry
        assert await short_cache.get(kh) is None
        stale = await short_cache.get_stale(kh)
        assert stale is not None
        assert stale.username == "joao"

    async def test_cleanup_evicts_unaccessed(self, cache: AuthCache) -> None:
        # Use a short stale grace period
        short_cache = AuthCache(ttl_seconds=60, stale_grace_seconds=0)
        kh = self._kh("hr_old")
        ident = self._ident()
        ident.last_accessed = 0  # ancient
        await short_cache.set(kh, ident)
        assert short_cache.size == 1
        removed = await short_cache.cleanup()
        assert removed == 1
        assert short_cache.size == 0

    async def test_cleanup_keeps_active_entries(self, cache: AuthCache) -> None:
        kh = self._kh("hr_active")
        ident = self._ident()
        ident.last_accessed = time.monotonic()  # just now
        await cache.set(kh, ident)
        removed = await cache.cleanup()
        assert removed == 0
        assert cache.size == 1

    async def test_get_updates_last_accessed(self, cache: AuthCache) -> None:
        kh = self._kh("hr_touch")
        ident = self._ident()
        old_access = ident.last_accessed
        time.sleep(0.001)
        await cache.set(kh, ident)
        cached = await cache.get(kh)
        assert cached is not None
        assert cached.last_accessed > old_access

    async def test_ttl_property(self) -> None:
        cache = AuthCache(ttl_seconds=42)
        assert cache.ttl == 42
