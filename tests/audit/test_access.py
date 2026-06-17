"""Unit tests for access scope (PRD 3 task 7.1-7.3)."""

import pytest

from headroom.audit.access import (
    AuditAccessError,
    Scope,
    enforce_scope,
    resolve_scope,
)


class TestResolveScope:
    def test_admin_sees_all(self) -> None:
        scope = resolve_scope("u_admin", "carlos", "admin", "")
        assert scope.is_admin is True
        assert scope.can_view_user("anyone")
        assert scope.can_view_team("any_team")

    def test_team_lead_scoped_to_team(self) -> None:
        scope = resolve_scope("u_maria", "maria", "team_lead", "backend")
        assert scope.is_admin is False
        assert scope.can_view_user("maria") is True
        assert scope.can_view_user("joao") is False
        assert scope.can_view_team("backend") is True
        assert scope.can_view_team("frontend") is False

    def test_developer_scoped_to_self(self) -> None:
        scope = resolve_scope("u_joao", "joao", "developer", "backend")
        assert scope.can_view_user("joao") is True
        assert scope.can_view_user("maria") is False

    def test_viewer_scoped_to_self(self) -> None:
        scope = resolve_scope("u_pedro", "pedro", "viewer", "frontend")
        assert scope.can_view_user("pedro") is True
        assert scope.can_view_user("alice") is False


class TestEnforceScope:
    def test_admin_no_restrictions(self) -> None:
        scope = resolve_scope("u_admin", "carlos", "admin", "")
        # Should not raise
        enforce_scope(scope, target_user="joao")
        enforce_scope(scope, target_team="frontend")

    def test_developer_cross_user_denied(self) -> None:
        scope = resolve_scope("u_joao", "joao", "developer", "backend")
        with pytest.raises(AuditAccessError, match="only view your own"):
            enforce_scope(scope, target_user="maria")

    def test_developer_self_allowed(self) -> None:
        scope = resolve_scope("u_joao", "joao", "developer", "backend")
        # Should not raise — same user
        enforce_scope(scope, target_user="joao")

    def test_team_lead_cross_team_denied(self) -> None:
        scope = resolve_scope("u_maria", "maria", "team_lead", "backend")
        with pytest.raises(AuditAccessError, match="outside your scope"):
            enforce_scope(scope, target_team="frontend")

    def test_team_lead_own_team_allowed(self) -> None:
        scope = resolve_scope("u_maria", "maria", "team_lead", "backend")
        # Should not raise
        enforce_scope(scope, target_team="backend")
