"""In-memory validation cache with TTL and Neo4j fallback.

Avoids querying Neo4j on every request by caching resolved identities
for a configurable TTL. When Neo4j is unreachable, expired (stale) entries
are served as a fallback so the proxy keeps working during transient outages.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("headroom_auth.cache")


@dataclass
class CachedIdentity:
    """A resolved user identity stored in the validation cache.

    Provider keys are decrypted once at cache time so the middleware
    does not pay the Fernet cost on every request.
    """

    user_id: str
    username: str
    role: str
    team: str
    provider_keys: dict[str, str] = field(default_factory=dict)
    """Decrypted provider keys: ``{"anthropic": "sk-ant-...", "openai": "sk-proj-..."}``."""
    default_rpm: int | None = None
    default_tpm: int | None = None
    cached_at: float = field(default_factory=time.monotonic)
    last_accessed: float = field(default_factory=time.monotonic)

    @classmethod
    def from_resolve_result(cls, result: dict[str, Any], crypto: Any) -> "CachedIdentity":
        """Build a ``CachedIdentity`` from a ``Neo4jAuthStore.resolve_key_identity`` result.

        Provider keys are decrypted immediately so the middleware never
        touches encrypted blobs.
        """
        import json

        raw_keys = result.get("provider_keys") or "{}"
        try:
            encrypted: dict[str, str] = json.loads(raw_keys)
        except (json.JSONDecodeError, TypeError):
            encrypted = {}

        decrypted: dict[str, str] = {}
        for provider, token in encrypted.items():
            try:
                decrypted[provider] = crypto.decrypt(token)
            except Exception:
                log.warning(
                    "auth-cache: failed to decrypt provider key '%s' for user '%s'",
                    provider,
                    result.get("username", "?"),
                )

        return cls(
            user_id=result["user_id"],
            username=result["username"],
            role=result["role"],
            team=result.get("team", ""),
            provider_keys=decrypted,
            default_rpm=result.get("default_rpm"),
            default_tpm=result.get("default_tpm"),
        )


class AuthCache:
    """In-memory TTL cache for validated user identities.

    Parameters:
        ttl_seconds: Entries older than this are considered stale and
            trigger a Neo4j refresh (default 10).
        stale_grace_seconds: Entries not accessed for longer than this
            are evicted by ``cleanup()`` (default 300 = 5 minutes).
    """

    def __init__(
        self,
        ttl_seconds: int = 10,
        stale_grace_seconds: int = 300,
    ) -> None:
        self._ttl = ttl_seconds
        self._stale_grace = stale_grace_seconds
        self._entries: dict[str, CachedIdentity] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def get(self, key_hash: str) -> CachedIdentity | None:
        """Return the cached identity if it is still fresh (within TTL).

        Updates ``last_accessed`` on hit so active entries are not evicted.
        Returns ``None`` when the entry is missing or expired.
        """
        async with self._lock:
            entry = self._entries.get(key_hash)
            if entry is None:
                return None
            age = time.monotonic() - entry.cached_at
            if age > self._ttl:
                return None
            entry.last_accessed = time.monotonic()
            return entry

    async def get_stale(self, key_hash: str) -> CachedIdentity | None:
        """Return an expired entry for fallback purposes.

        Used when Neo4j is unreachable — the stale entry lets the request
        proceed with a warning log instead of failing with 503.
        """
        async with self._lock:
            entry = self._entries.get(key_hash)
            if entry is not None:
                entry.last_accessed = time.monotonic()
            return entry

    async def set(self, key_hash: str, identity: CachedIdentity) -> None:
        """Store (or refresh) a cache entry."""
        async with self._lock:
            self._entries[key_hash] = identity

    async def cleanup(self) -> int:
        """Remove entries that haven't been accessed in ``stale_grace_seconds``.

        Called periodically (every 60s) to prevent unbounded memory growth
        from keys that were used once and never again.

        Returns the number of evicted entries.
        """
        threshold = time.monotonic() - self._stale_grace
        async with self._lock:
            stale = [
                h
                for h, e in self._entries.items()
                if e.last_accessed < threshold
            ]
            for h in stale:
                del self._entries[h]
        if stale:
            log.debug("auth-cache: evicted %d stale entries", len(stale))
        return len(stale)

    @property
    def size(self) -> int:
        """Current number of cached entries (for testing and metrics)."""
        return len(self._entries)

    @property
    def ttl(self) -> int:
        """Configured TTL in seconds."""
        return self._ttl
