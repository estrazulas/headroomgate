"""Data models for the audit system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RequestLog:
    """A recorded proxy request, stored as a ``(:RequestLog)`` node in Neo4j.

    Fields are deliberately denormalized (``username``, ``team``) so the
    most common audit queries do not need a JOIN to ``(:User)``.
    """

    request_id: str
    user_id: str
    username: str  # denormalized from User
    team: str  # denormalized from User
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    tokens_saved: int
    latency_ms: float
    cache_hit: bool
    status_code: int
    timestamp: datetime = field(default_factory=_utcnow)

    def to_neo4j_dict(self) -> dict:
        """Convert to a dict suitable for ``UNWIND $batch CREATE``."""
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "username": self.username,
            "team": self.team,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tokens_saved": self.tokens_saved,
            "latency_ms": self.latency_ms,
            "cache_hit": self.cache_hit,
            "status_code": self.status_code,
            "timestamp": self.timestamp.isoformat(),
        }
