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

from headroom.usage.buffer import AuditBuffer
from headroom.usage.store import AuditStore
from headroom.usage.semantic import SemanticLogger

log = logging.getLogger("headroom.usage")


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
    """Build a textual summary from a RequestOutcome for embedding and history.

    Tries to extract the last user message content from request_messages
    (available when proxy runs with --log-full-messages). Falls back to
    metadata if message bodies are not available.
    """
    # Try to extract actual user message content
    user_text = _extract_user_message(outcome)
    if user_text:
        # Truncate to max_words
        words = user_text.split()
        if len(words) > max_words:
            user_text = " ".join(words[:max_words])
        return user_text

    # Fallback: metadata-only summary
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


def _extract_user_message(outcome: Any) -> str:
    """Extract the last user message from a RequestOutcome, if available.

    Checks outcome.request_messages (populated when log_full_messages is on)
    and outcome.compressed_messages for the last message with role="user".
    """
    messages = getattr(outcome, "request_messages", None) or getattr(
        outcome, "compressed_messages", None
    )
    if not messages:
        return ""
    # Find the last user message
    for msg in reversed(messages):
        role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
        if role == "user":
            content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            if isinstance(content, list):
                # Anthropic format: content is list of blocks
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                content = " ".join(parts)
            if isinstance(content, str) and content.strip():
                return content.strip()
            return str(content).strip()
    return ""
