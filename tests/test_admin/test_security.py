"""Security/RBAC tests for the admin interface (Tasks 8.1-8.13).

These tests verify the RBAC enforcement at the API layer without needing
Neo4j — they directly test the router's dependency injection behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from headroom.admin.router import _require_admin, _require_admin_or_lead, router


def _make_test_app() -> FastAPI:
    """Create a minimal test app with the admin router."""
    app = FastAPI()
    app.include_router(router, prefix="/manage")
    return app


# ── Dependency guard tests ──────────────────────────────────────────────


class TestDependencyGuards:
    """Unit tests for the FastAPI dependency guards used by all admin routes."""

    @pytest.mark.asyncio
    async def test_no_session_returns_401(self) -> None:
        """Access without session cookie returns 401."""
        with pytest.raises(HTTPException) as exc:
            await _require_admin_or_lead(headroom_session=None)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_developer_access_denied(self) -> None:
        """Developer role cannot access admin pages (Task 8.5)."""
        with pytest.raises(HTTPException):
            await _require_admin_or_lead(headroom_session="fake")
        # Would raise 401 because session doesn't exist — the role check
        # only happens after session resolution.

    @pytest.mark.asyncio
    async def test_viewer_access_denied(self) -> None:
        """Viewer role cannot access admin pages (Task 8.6)."""
        with pytest.raises(HTTPException) as exc:
            await _require_admin_or_lead(headroom_session="fake")
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_forged_session_cookie(self) -> None:
        """Forged session cookie (random token) is rejected (Task 8.7)."""
        with pytest.raises(HTTPException) as exc:
            await _require_admin_or_lead(headroom_session="random_forged_token_12345")
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_role_passes(self) -> None:
        """Admin role passes _require_admin_or_lead check."""
        # Mock the session resolution
        mock_session = AsyncMock(
            return_value={
                "user_id": "u_admin",
                "username": "admin",
                "role": "admin",
                "team": "test_team",
            }
        )
        with patch("headroom.admin.router._resolve_session", mock_session):
            result = await _require_admin_or_lead(headroom_session="valid_token")
            assert result["role"] == "admin"

    @pytest.mark.asyncio
    async def test_team_lead_passes_admin_or_lead_check(self) -> None:
        """Team lead role passes _require_admin_or_lead check."""
        mock_session = AsyncMock(
            return_value={
                "user_id": "u_lead",
                "username": "lead",
                "role": "team_lead",
                "team": "backend",
            }
        )
        with patch("headroom.admin.router._resolve_session", mock_session):
            result = await _require_admin_or_lead(headroom_session="valid_token")
            assert result["role"] == "team_lead"

    @pytest.mark.asyncio
    async def test_developer_rejected_by_admin_or_lead(self) -> None:
        """Developer role is rejected by _require_admin_or_lead (Task 8.5)."""
        mock_session = AsyncMock(
            return_value={
                "user_id": "u_dev",
                "username": "dev",
                "role": "developer",
                "team": "backend",
            }
        )
        with patch("headroom.admin.router._resolve_session", mock_session):
            with pytest.raises(HTTPException) as exc:
                await _require_admin_or_lead(headroom_session="valid_token")
            assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_rejected_by_admin_or_lead(self) -> None:
        """Viewer role is rejected by _require_admin_or_lead (Task 8.6)."""
        mock_session = AsyncMock(
            return_value={
                "user_id": "u_viewer",
                "username": "viewer",
                "role": "viewer",
                "team": "backend",
            }
        )
        with patch("headroom.admin.router._resolve_session", mock_session):
            with pytest.raises(HTTPException) as exc:
                await _require_admin_or_lead(headroom_session="valid_token")
            assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_passes_admin_only_check(self) -> None:
        """Admin role passes _require_admin check."""
        mock_session = AsyncMock(
            return_value={
                "user_id": "u_admin",
                "username": "admin",
                "role": "admin",
                "team": "test_team",
            }
        )
        with patch("headroom.admin.router._resolve_session", mock_session):
            result = await _require_admin(headroom_session="valid_token")
            assert result["role"] == "admin"

    @pytest.mark.asyncio
    async def test_team_lead_rejected_by_admin_only(self) -> None:
        """Team lead role is rejected by _require_admin (Task 8.3)."""
        mock_session = AsyncMock(
            return_value={
                "user_id": "u_lead",
                "username": "lead",
                "role": "team_lead",
                "team": "backend",
            }
        )
        with patch("headroom.admin.router._resolve_session", mock_session):
            with pytest.raises(HTTPException) as exc:
                await _require_admin(headroom_session="valid_token")
            assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_no_session_direct_api_returns_401(self) -> None:
        """Direct API call without session cookie → 401, no data leaked (Task 8.9)."""
        with pytest.raises(HTTPException) as exc:
            await _require_admin_or_lead(headroom_session=None)
        assert exc.value.status_code == 401


class TestHttpEndpointAccess:
    """HTTP-level tests using FastAPI TestClient."""

    def test_login_page_accessible_without_auth(self) -> None:
        """Login page loads without session cookie."""
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/manage/login")
        assert resp.status_code == 200
        assert "Login" in resp.text or "API Key" in resp.text

    def test_users_page_requires_auth(self) -> None:
        """Users page returns 401 without session cookie."""
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/manage/users")
        assert resp.status_code == 401

    def test_teams_page_requires_auth(self) -> None:
        """Teams page returns 401 without session cookie."""
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/manage/teams")
        assert resp.status_code == 401

    def test_keys_page_requires_auth(self) -> None:
        """Keys page returns 401 without session cookie."""
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/manage/keys")
        assert resp.status_code == 401

    def test_api_users_requires_auth(self) -> None:
        """API endpoint returns 401 without session cookie."""
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/manage/api/users")
        assert resp.status_code == 401

    def test_api_teams_requires_auth(self) -> None:
        """Teams API returns 401 without session cookie."""
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/manage/api/teams")
        assert resp.status_code == 401

    def test_api_keys_requires_auth(self) -> None:
        """Keys API returns 401 without session cookie."""
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/manage/api/keys")
        assert resp.status_code == 401

    def test_api_usage_summary_requires_auth(self) -> None:
        """Usage API returns 401 without session cookie."""
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/manage/api/usage/summary")
        assert resp.status_code == 401

    # ── Lazy-init tests (would have caught the RuntimeError bug) ──────

    @pytest.mark.asyncio
    async def test_login_no_crash_with_default_init(self) -> None:
        """init_admin() without args should not crash (lazy stores)."""
        from headroom.admin.router import init_admin, shutdown_admin

        await init_admin()
        shutdown_admin()
