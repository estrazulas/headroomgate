"""Per-request user identity stored in :mod:`contextvars`.

After the auth middleware validates a proxy key, it stores the resolved
identity (user_id, username, role, team) in context-local variables so
downstream consumers — audit logs, metrics, the PRD 3 request log — can
access them without threading a user parameter through every handler.

Follows the same pattern as ``headroom.proxy.project_context``.
"""

from __future__ import annotations

from contextvars import ContextVar

_current_user_id: ContextVar[str | None] = ContextVar("headroom_current_user_id", default=None)
_current_username: ContextVar[str | None] = ContextVar("headroom_current_username", default=None)
_current_role: ContextVar[str | None] = ContextVar("headroom_current_role", default=None)
_current_team: ContextVar[str | None] = ContextVar("headroom_current_team", default=None)


def set_current_identity(
    user_id: str,
    username: str,
    role: str,
    team: str,
) -> None:
    """Bind the authenticated user identity for the current request."""
    _current_user_id.set(user_id)
    _current_username.set(username)
    _current_role.set(role)
    _current_team.set(team)


def clear_current_identity() -> None:
    """Clear the current request's identity (called after the response)."""
    _current_user_id.set(None)
    _current_username.set(None)
    _current_role.set(None)
    _current_team.set(None)


def get_current_user() -> str | None:
    """``user_id`` of the authenticated user, or ``None``."""
    return _current_user_id.get()


def get_current_username() -> str | None:
    """``username`` of the authenticated user, or ``None``."""
    return _current_username.get()


def get_current_role() -> str | None:
    """Role name of the authenticated user, or ``None``."""
    return _current_role.get()


def get_current_team() -> str | None:
    """Team name of the authenticated user, or ``None``."""
    return _current_team.get()


__all__ = [
    "clear_current_identity",
    "get_current_role",
    "get_current_team",
    "get_current_user",
    "get_current_username",
    "set_current_identity",
]
