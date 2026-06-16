"""Headroom Auth - Multi-user access control for the LLM proxy.

This package provides the persistence layer (Neo4j), cryptography (Fernet),
and data models for the headroom multi-user auth system.

Components are lazy-imported so that ``import headroom.auth`` is cheap;
consumers that need specific pieces import them directly.
"""

from __future__ import annotations


def __getattr__(name: str) -> object:
    """Lazy import for store and crypto components."""
    if name == "Neo4jAuthStore":
        from headroom.auth.store import Neo4jAuthStore

        return Neo4jAuthStore

    if name == "FernetCrypto":
        from headroom.auth.crypto import FernetCrypto

        return FernetCrypto

    if name == "User":
        from headroom.auth.models import User

        return User

    if name == "Role":
        from headroom.auth.models import Role

        return Role

    if name == "Team":
        from headroom.auth.models import Team

        return Team

    if name == "ApiKey":
        from headroom.auth.models import ApiKey

        return ApiKey

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Neo4jAuthStore",
    "FernetCrypto",
    "User",
    "Role",
    "Team",
    "ApiKey",
]
