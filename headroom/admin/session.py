"""In-memory session store with TTL for the admin web interface.

Session tokens are 256-bit random hex strings stored as httpOnly,
SameSite=Strict cookies. The store periodically cleans expired sessions.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Any

log = logging.getLogger("headroom.admin.session")

# Type aliases
SessionId = str  # hex string, 64 chars
SessionData = dict[str, Any]


class AdminSessionStore:
    """In-memory session store with TTL and background cleanup.

    Sessions are ephemeral — lost on proxy restart, which is acceptable
    (users re-login with their API key). Default TTL is 8 hours.

    Parameters:
        ttl_seconds: Session time-to-live in seconds (default 8 hours).
        cleanup_interval: How often to clean expired sessions (default 5 min).
    """

    def __init__(
        self,
        ttl_seconds: int = 28800,
        cleanup_interval: int = 300,
    ) -> None:
        self._ttl = ttl_seconds
        self._cleanup_interval = cleanup_interval
        self._sessions: dict[SessionId, tuple[float, SessionData]] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background cleanup task.

        Safe to call outside an async context — the task is created
        lazily on the next ``start_async()`` call.
        """
        # Mark as requested; actual task creation happens in start_async()

    async def start_async(self) -> None:
        """Start the background cleanup task (must be called from an async context)."""
        if self._cleanup_task is None:

            async def _cleanup_loop() -> None:
                while True:
                    await asyncio.sleep(self._cleanup_interval)
                    cleaned = await self._clean_expired()
                    if cleaned:
                        log.debug("Cleaned %d expired sessions", cleaned)

            self._cleanup_task = asyncio.create_task(_cleanup_loop())
            log.info(
                "Admin session store started (ttl=%ds, cleanup=%ds)",
                self._ttl,
                self._cleanup_interval,
            )

    async def stop(self) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            log.info("Admin session store stopped")

    # ------------------------------------------------------------------
    # core operations
    # ------------------------------------------------------------------

    async def create(self, data: SessionData) -> SessionId:
        """Create a new session with *data* and return the session token."""
        session_id = secrets.token_hex(32)  # 256 bits
        expires_at = time.monotonic() + self._ttl
        async with self._lock:
            self._sessions[session_id] = (expires_at, data)
        return session_id

    async def get(self, session_id: SessionId) -> SessionData | None:
        """Resolve a session token to its data, or ``None`` if expired/missing."""
        async with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            expires_at, data = entry
            if time.monotonic() >= expires_at:
                del self._sessions[session_id]
                return None
            return data

    async def delete(self, session_id: SessionId) -> bool:
        """Delete a session. Returns ``True`` if it existed."""
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    async def _clean_expired(self) -> int:
        """Remove all expired sessions. Returns count removed."""
        now = time.monotonic()
        expired: list[SessionId] = []
        async with self._lock:
            for sid, (expires_at, _data) in self._sessions.items():
                if now >= expires_at:
                    expired.append(sid)
            for sid in expired:
                del self._sessions[sid]
        return len(expired)

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------

    @property
    def active_count(self) -> int:
        """Return the number of active sessions."""
        return len(self._sessions)
