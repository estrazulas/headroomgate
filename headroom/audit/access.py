"""Role-based access scope for audit queries.

Enforces that developers see only their own requests, team leads see
their team, and admins see everything. Scope is resolved from the
PRD 2 identity contextvars (or CLI key resolution).
"""

from __future__ import annotations

from dataclasses import dataclass, field


class AuditAccessError(Exception):
    """Raised when a user attempts to access data outside their scope."""


@dataclass
class Scope:
    """Access boundaries for the current caller."""

    user_id: str
    username: str
    role: str
    team: str
    is_admin: bool = False
    allowed_user_ids: list[str] = field(default_factory=list)
    allowed_teams: list[str] = field(default_factory=list)

    def can_view_user(self, target_username: str) -> bool:
        if self.is_admin:
            return True
        if target_username == self.username:
            return True
        return False

    def can_view_team(self, target_team: str) -> bool:
        if self.is_admin:
            return True
        if self.role == "team_lead" and target_team == self.team:
            return True
        return False


def resolve_scope(user_id: str, username: str, role: str, team: str) -> Scope:
    """Build a ``Scope`` from the caller's identity.

    Parameters:
        user_id: Caller's ``user_id`` from contextvar or key resolution.
        username: Caller's username.
        role: Caller's role (``admin``, ``team_lead``, ``developer``, ``viewer``).
        team: Caller's team name.
    """
    is_admin = role == "admin"
    is_team_lead = role == "team_lead"

    allowed_user_ids = [user_id]
    allowed_teams = [team] if is_team_lead else []

    if is_admin:
        allowed_teams = []  # empty = all teams

    return Scope(
        user_id=user_id,
        username=username,
        role=role,
        team=team,
        is_admin=is_admin,
        allowed_user_ids=allowed_user_ids,
        allowed_teams=allowed_teams,
    )


def enforce_scope(
    scope: Scope,
    target_user: str | None = None,
    target_team: str | None = None,
) -> None:
    """Raise ``AuditAccessError`` if *scope* does not cover the target.

    Parameters:
        scope: The caller's access scope.
        target_user: The username being queried (if any).
        target_team: The team being queried (if any).
    """
    if scope.is_admin:
        return

    if target_user is not None and target_user != scope.username:
        if scope.role == "developer":
            raise AuditAccessError(
                "You can only view your own requests. Use --self."
            )
        if scope.role == "team_lead" and target_team is not None:
            if target_team != scope.team:
                raise AuditAccessError(
                    f"You can only view requests from your team ({scope.team})."
                    f" User '{target_user}' is outside your scope"
                    f" (belongs to team '{target_team}')."
                )
        elif scope.role == "team_lead":
            # target_team not provided — fall back to blocking (conservative)
            raise AuditAccessError(
                f"You can only view requests from your team ({scope.team})."
            )

    if target_team is not None and target_team != scope.team:
        if scope.role != "admin":
            raise AuditAccessError(
                f"Team '{target_team}' is outside your scope."
            )
