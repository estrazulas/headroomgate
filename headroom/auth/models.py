"""Data models for the multi-user auth system.

Each model maps to a Neo4j node label. Fields marked ``uid`` are the
node-level unique identifiers (UUIDv4 strings).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


def _utcnow() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


@dataclass
class User:
    """A human developer who consumes the proxy.

    Attributes:
        user_id: UUIDv4 stable identifier for the ``:User`` node.
        username: Unique human-readable login name.
        role: Name of the ``:Role`` this user belongs to.
        team: Name of the ``:Team`` this user belongs to.
        is_active: When ``False``, every key is rejected (soft-delete).
        created_at: UTC timestamp of creation.
    """

    username: str
    role: str
    team: str
    user_id: str = ""
    is_active: bool = True
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        import uuid

        if not self.user_id:
            self.user_id = f"u_{uuid.uuid4().hex[:12]}"


@dataclass
class Role:
    """A named set of permissions and provider keys.

    Attributes:
        name: Unique role name (``admin``, ``team_lead``, ``developer``, ``viewer``).
        description: Human-readable summary of what the role grants.
        provider_keys: JSON-serializable dict of provider → Fernet-encrypted key.
        default_rpm: Default requests-per-minute limit (optional).
        default_tpm: Default tokens-per-minute limit (optional).
    """

    name: str
    description: str = ""
    provider_keys: dict[str, str] = field(default_factory=dict)
    default_rpm: int | None = None
    default_tpm: int | None = None


@dataclass
class Team:
    """A group of users scoped to the same team lead.

    Attributes:
        name: Unique team name (``backend``, ``frontend``).
        created_at: UTC timestamp of creation.
    """

    name: str
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class ApiKey:
    """A proxy API key with prefix ``hr_``.

    Attributes:
        key_id: Short stable identifier (``k_<random>``) for reference in CLI.
        key_hash: SHA-256 hex digest of the full key. The raw key is *never* stored.
        key_prefix: First 8 chars of the raw key for visual identification.
        user_id: The ``:User.user_id`` that owns this key.
        is_active: When ``False``, the key is revoked.
        created_at: UTC timestamp of creation.
        expires_at: UTC timestamp after which the key is invalid.
    """

    key_hash: str
    key_prefix: str
    user_id: str
    key_id: str = ""
    is_active: bool = True
    created_at: datetime = field(default_factory=_utcnow)
    expires_at: datetime = field(
        default_factory=lambda: _utcnow() + timedelta(days=90)
    )

    def __post_init__(self) -> None:
        import uuid

        if not self.key_id:
            self.key_id = f"k_{uuid.uuid4().hex[:12]}"
