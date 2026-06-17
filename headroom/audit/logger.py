"""Audit logger — orchestrates Neo4j + Qdrant logging from a RequestOutcome.

Reads the authenticated user identity from contextvars (set by PRD 2
middleware) and builds both a structured Neo4j entry and a Qdrant
semantic embedding. Logging is fully asynchronous — the client response
is never blocked.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from headroom.audit.buffer import AuditBuffer
from headroom.audit.store import AuditStore
from headroom.audit.semantic import SemanticLogger

log = logging.getLogger("headroom.audit")


class AuditLogger:
    """Orchestrates dual logging (Neo4j + Qdrant) for completed requests.

    Parameters:
        store: ``AuditStore`` for Neo4j writes.
        buffer: ``AuditBuffer`` wrapping the store's insert method.
        semantic: ``SemanticLogger`` for Qdrant writes (may be disabled).
        semantic_enabled: Toggle Qdrant logging at runtime.
    """

    def __init__(
        self,
        store: AuditStore | None = None,
        buffer: AuditBuffer | None = None,
        semantic: SemanticLogger | None = None,
        semantic_enabled: bool = True,
    ) -> None:
        self._store = store or AuditStore()
        self._buffer = buffer or AuditBuffer(store_insert=self._store.insert_batch)
        self._semantic = semantic or SemanticLogger(enabled=semantic_enabled)
        self._semantic_enabled = semantic_enabled

    async def start(self) -> None:
        """Start the background buffer flush loop and ensure Qdrant collection."""
        await self._buffer.start()
        if self._semantic_enabled:
            self._semantic.ensure_collection()

    async def stop(self) -> None:
        """Flush remaining entries and stop the background loop."""
        await self._buffer.stop()

    def log(self, outcome: Any) -> None:
        """Record a completed request from its ``RequestOutcome``.

        *outcome* is a ``headroom.proxy.outcome.RequestOutcome``.
        Identity is read from the PRD 2 contextvars.
        """
        from headroom_auth.identity import (
            get_current_team,
            get_current_user,
            get_current_username,
        )

        user_id = get_current_user()
        if user_id is None:
            return  # unauthenticated — skip

        username = get_current_username() or "unknown"
        team = get_current_team() or ""

        summary = _build_summary(outcome)

        entry = {
            "request_id": outcome.request_id,
            "user_id": user_id,
            "username": username,
            "team": team,
            "provider": outcome.provider,
            "model": outcome.model,
            "input_tokens": outcome.optimized_tokens,
            "output_tokens": outcome.output_tokens,
            "tokens_saved": outcome.tokens_saved,
            "latency_ms": outcome.total_latency_ms,
            "cache_hit": outcome.from_response_cache,
            "status_code": 200,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary or "",
        }

        self._buffer.enqueue(entry)

        if self._semantic_enabled and self._semantic.is_available:
            if summary:
                self._semantic.log_request(
                    request_id=outcome.request_id,
                    user_id=user_id,
                    username=username,
                    team=team,
                    provider=outcome.provider,
                    model=outcome.model,
                    timestamp=datetime.now(timezone.utc),
                    summary=summary,
                )


# ---------------------------------------------------------------------------
# module-level singleton — initialized at proxy startup
# ---------------------------------------------------------------------------

_audit_logger: AuditLogger | None = None


def init_audit_logger(
    semantic_enabled: bool = True,
) -> AuditLogger:
    """Initialize (or return existing) module-level ``AuditLogger`` singleton."""
    global _audit_logger
    if _audit_logger is not None:
        return _audit_logger
    _audit_logger = AuditLogger(semantic_enabled=semantic_enabled)
    return _audit_logger


async def start_audit_logger() -> None:
    """Start the background buffer flush for the singleton logger."""
    if _audit_logger is not None:
        await _audit_logger.start()


async def stop_audit_logger() -> None:
    """Flush and stop the singleton logger's buffer."""
    if _audit_logger is not None:
        await _audit_logger.stop()


def _build_summary(
    outcome: Any,
    max_words: int = 200,
) -> str:
    """Build a short textual summary from a RequestOutcome for embedding.

    Uses the provider and model as context. Full message bodies are
    not available on RequestOutcome by default, so the summary is
    metadata-rich rather than content-rich.
    """
    parts = [
        f"Request to {outcome.provider} using model {outcome.model}.",
        f"Input tokens: {outcome.optimized_tokens}, output tokens: {outcome.output_tokens}.",
        f"Tokens saved: {outcome.tokens_saved}.",
    ]
    summary = " ".join(parts)
    words = summary.split()
    if len(words) > max_words:
        summary = " ".join(words[:max_words])
    return summary
