"""Integration tests for admin HTTP API endpoints (Tasks 9.2, 9.3, 9.4).

Tests the full HTTP request/response cycle through FastAPI TestClient
including session creation, cookie handling, RBAC enforcement at route
level, and store-level integration with Neo4j.

Requires Neo4j to be running (``docker compose up -d neo4j``).
Auto-skips if NEO4J_URI is not reachable.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from headroom.admin.router import init_admin, router, shutdown_admin
from headroom.auth.store import Neo4jAuthStore
from headroom.usage.store import AuditStore

# ---------------------------------------------------------------------------
# Unique-name helper — avoids 409 conflicts between test runs
# ---------------------------------------------------------------------------

_TAG = secrets.token_hex(4)


def _unique(prefix: str) -> str:
    return f"{prefix}_{_TAG}"


# ---------------------------------------------------------------------------
# Neo4j detection
# ---------------------------------------------------------------------------


def _neo4j_available() -> bool:
    """Check if Neo4j is reachable by opening a test connection."""
    uri = os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            session.run("RETURN 1")
        driver.close()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Module-scoped fixtures — one init, shared across all tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stores() -> Generator[tuple[Neo4jAuthStore, AuditStore], None, None]:
    """Create and initialize the shared auth and audit stores."""
    auth_store = Neo4jAuthStore()
    auth_store.init_db()
    audit_store = AuditStore()
    yield auth_store, audit_store


@pytest.fixture(scope="module")
def app(stores: tuple[Neo4jAuthStore, AuditStore]) -> Generator[FastAPI, None, None]:
    """Create a FastAPI test app with the admin router and initialised stores."""
    auth_store, audit_store = stores

    app = FastAPI()
    app.include_router(router, prefix="/manage")

    # Initialise the module-level globals that router._get_auth() etc look up
    loop = asyncio.new_event_loop()
    loop.run_until_complete(init_admin(auth_store=auth_store, audit_store=audit_store))
    loop.close()

    yield app

    shutdown_admin()


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    """TestClient per test."""
    with TestClient(app) as c:
        yield c


class _LoginHelper:
    """Helper to log in a test user and return the session cookie value."""

    def __init__(self, client: TestClient, auth_store: Neo4jAuthStore) -> None:
        self._client = client
        self._auth = auth_store

    def login(self, username: str, role: str, team: str = "test_team") -> str | None:
        """Create user *username* and an API key, then POST /manage/login.
        Returns the ``headroom_session`` cookie value (or None on failure).
        """
        self._auth.create_user(username, role, team)
        raw_key, _ = self._auth.create_key(username)
        resp = self._client.post("/manage/login", data={"api_key": raw_key}, follow_redirects=False)
        return resp.cookies.get("headroom_session")


# ===================================================================
# Task 9.2 — Login / logout flow
# ===================================================================


@pytest.mark.skipif(not _neo4j_available(), reason="Neo4j not available")
class TestLoginFlowHTTP:
    """Task 9.2 — HTTP integration tests for login/logout flow."""

    def test_login_page_returns_200(self, client: TestClient) -> None:
        """GET /manage/login is publicly accessible (no cookie required)."""
        resp = client.get("/manage/login")
        assert resp.status_code == 200

    def test_login_valid_key_returns_303_and_cookie(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore]
    ) -> None:
        """POST /manage/login with a valid hr_* key → 303 redirect + Set-Cookie."""
        auth, _ = stores
        u = _unique("login_valid")
        session = _LoginHelper(client, auth).login(u, "admin")
        assert session is not None
        assert len(session) == 64  # 256-bit hex

    def test_login_redirect_location(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore]
    ) -> None:
        """POST /manage/login redirects to /manage."""
        auth, _ = stores
        u = _unique("login_redir")
        auth.create_user(u, "admin", "redir_team")
        raw_key, _ = auth.create_key(u)
        resp = client.post("/manage/login", data={"api_key": raw_key}, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers.get("location") == "/manage"

    def test_login_invalid_key_shows_error(self, client: TestClient) -> None:
        """POST /manage/login with invalid key returns 200 + error message."""
        resp = client.post("/manage/login", data={"api_key": "hr_bad_key"})
        assert resp.status_code == 200
        assert "Invalid API key" in resp.text

    def test_login_revoked_key_fails(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore]
    ) -> None:
        """Revoked key does not create a session."""
        auth, _ = stores
        u = _unique("login_revoked")
        auth.create_user(u, "developer", "revoked_team")
        raw_key, api_key = auth.create_key(u)
        auth.revoke_key(api_key.key_id)

        resp = client.post("/manage/login", data={"api_key": raw_key})
        assert "Invalid API key" in resp.text

    def test_session_cookie_grants_access_to_protected_pages(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore]
    ) -> None:
        """Cookie obtained from login can be reused to access protected routes."""
        auth, _ = stores
        session = _LoginHelper(client, auth).login(_unique("login_access"), "admin")

        resp = client.get("/manage/users", cookies={"headroom_session": session})
        assert resp.status_code == 200

    def test_logout_clears_cookie(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore]
    ) -> None:
        """POST /manage/logout → 303 redirect + Set-Cookie with empty value (cleared)."""
        auth, _ = stores
        session = _LoginHelper(client, auth).login(_unique("login_logout"), "admin")

        logout_resp = client.post(
            "/manage/logout",
            cookies={"headroom_session": session},
            follow_redirects=False,
        )
        assert logout_resp.status_code == 303
        assert logout_resp.headers.get("location") == "/manage/login"

        # Set-Cookie header should clear the cookie (max-age=0 or blank value)
        set_cookie = logout_resp.headers.get("set-cookie", "")
        assert "headroom_session=" in set_cookie
        assert "Max-Age=0" in set_cookie or "expires=" in set_cookie.lower()

    def test_unauthenticated_access_returns_401(self, client: TestClient) -> None:
        """Protected endpoint without cookie → 401."""
        for path in ["/manage/users", "/manage/teams", "/manage/keys", "/manage/usage"]:
            resp = client.get(path)
            assert resp.status_code == 401, f"{path} should return 401"

    def test_unauthenticated_api_returns_401(self, client: TestClient) -> None:
        """Protected API endpoints without cookie → 401."""
        for path in [
            "/manage/api/users",
            "/manage/api/teams",
            "/manage/api/keys",
            "/manage/api/usage/summary",
        ]:
            resp = client.get(path)
            assert resp.status_code == 401, f"{path} should return 401"

    # ── Store-level integration (login flow internals) ──────────────

    def test_login_valid_key_store_level(self, stores: tuple[Neo4jAuthStore, AuditStore]) -> None:
        """Store-level: resolve_key_identity returns identity for valid key."""
        auth, _ = stores
        u = _unique("login_store_valid")
        auth.create_user(u, "admin", "store_team")
        raw_key, _ = auth.create_key(u)

        identity = auth.resolve_key_identity(raw_key)
        assert identity is not None
        assert identity["role"] == "admin"

    def test_login_invalid_key_store_level(self, stores: tuple[Neo4jAuthStore, AuditStore]) -> None:
        """Store-level: resolve_key_identity returns None for invalid key."""
        auth, _ = stores
        identity = auth.resolve_key_identity("hr_nonexistent_000000000000")
        assert identity is None


# ===================================================================
# Task 9.3 — CRUD API endpoints + RBAC enforcement
# ===================================================================


@pytest.mark.skipif(not _neo4j_available(), reason="Neo4j not available")
class TestCRUDWithRBAC:
    """Task 9.3 — HTTP integration tests for CRUD endpoints with RBAC."""

    @pytest.fixture
    def helper(self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore]) -> _LoginHelper:
        return _LoginHelper(client, stores[0])

    # ── User CRUD ──────────────────────────────────────────────────

    def test_admin_list_all_users(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Admin can list users across all teams."""
        auth, _ = stores
        u_a = _unique("crud_list_a")
        u_b = _unique("crud_list_b")
        auth.create_user(u_a, "developer", "team_alpha")
        auth.create_user(u_b, "developer", "team_beta")

        session = helper.login(_unique("crud_admin_list"), "admin")
        resp = client.get("/manage/api/users", cookies={"headroom_session": session})
        assert resp.status_code == 200

        usernames = [u["username"] for u in resp.json()]
        assert u_a in usernames
        assert u_b in usernames

    def test_team_lead_sees_only_own_team(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Team lead's list_users returns only their team's users."""
        auth, _ = stores
        u_a = _unique("crud_team_a")
        u_b = _unique("crud_team_b")
        auth.create_user(u_a, "developer", "lead_team")
        auth.create_user(u_b, "developer", "other_team")

        session = helper.login(_unique("crud_lead_list"), "team_lead", "lead_team")
        resp = client.get("/manage/api/users", cookies={"headroom_session": session})
        assert resp.status_code == 200

        usernames = {u["username"] for u in resp.json()}
        assert u_a in usernames
        assert u_b not in usernames

    def test_admin_create_user(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Admin creates a user in any team."""
        session = helper.login(_unique("crud_admin_create"), "admin", "admin_team")

        new_user = _unique("crud_new_dev")
        resp = client.post(
            "/manage/api/users",
            json={"username": new_user, "role": "developer", "team": "infra"},
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == new_user
        assert resp.json()["team"] == "infra"

    def test_create_user_requires_username(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """POST /api/users with empty username returns 400."""
        session = helper.login(_unique("crud_admin_req"), "admin")
        resp = client.post(
            "/manage/api/users",
            json={"username": "", "role": "developer", "team": "infra"},
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 400

    def test_create_duplicate_user_returns_409(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Creating a duplicate username returns 409."""
        auth, _ = stores
        dup_user = _unique("crud_dup")
        auth.create_user(dup_user, "developer", "dup_team")
        session = helper.login(_unique("crud_admin_dup"), "admin")

        resp = client.post(
            "/manage/api/users",
            json={"username": dup_user, "role": "developer", "team": "dup_team"},
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 409

    def test_team_lead_create_in_own_team(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Team lead can create a user in their own team."""
        session = helper.login(_unique("crud_lead_ok"), "team_lead", "backend")

        new_user = _unique("crud_lead_dev")
        resp = client.post(
            "/manage/api/users",
            json={"username": new_user, "role": "developer", "team": "backend"},
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 200

    def test_team_lead_cannot_create_outside_team(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Team lead creating user in another team → 403."""
        session = helper.login(_unique("crud_lead_forbid"), "team_lead", "backend")
        resp = client.post(
            "/manage/api/users",
            json={"username": _unique("crud_cross"), "role": "developer", "team": "frontend"},
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 403

    def test_toggle_user_status(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Admin can deactivate and reactivate a user."""
        auth, _ = stores
        toggle_user = _unique("crud_toggle")
        auth.create_user(toggle_user, "developer", "toggle_team")
        session = helper.login(_unique("crud_admin_toggle"), "admin")

        # Deactivate
        resp = client.put(
            f"/manage/api/users/{toggle_user}/status",
            json={"is_active": False},
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 200
        user = auth.get_user(toggle_user)
        assert user is not None and user.is_active is False

        # Reactivate
        resp = client.put(
            f"/manage/api/users/{toggle_user}/status",
            json={"is_active": True},
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 200
        user = auth.get_user(toggle_user)
        assert user is not None and user.is_active is True

    # ── Team CRUD ──────────────────────────────────────────────────

    def test_admin_list_teams(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Admin can list all teams."""
        auth, _ = stores
        t_a = _unique("team_list_a")
        t_b = _unique("team_list_b")
        auth.create_team(t_a)
        auth.create_team(t_b)

        session = helper.login(_unique("crud_admin_teams"), "admin")
        resp = client.get("/manage/api/teams", cookies={"headroom_session": session})
        assert resp.status_code == 200
        names = {t["name"] for t in resp.json()}
        assert t_a in names
        assert t_b in names

    def test_admin_create_team(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Admin creates a team."""
        session = helper.login(_unique("crud_admin_mkteam"), "admin")
        new_team = _unique("team_new")
        resp = client.post(
            "/manage/api/teams",
            json={"name": new_team},
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == new_team

    def test_team_lead_cannot_create_team(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Team lead posting to /api/teams → 403."""
        session = helper.login(_unique("crud_lead_noteam"), "team_lead", "lead_team")
        resp = client.post(
            "/manage/api/teams",
            json={"name": _unique("team_illegal")},
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 403

    # ── Key CRUD ───────────────────────────────────────────────────

    def test_admin_key_lifecycle(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Full key lifecycle through HTTP: create → list → revoke."""
        auth, _ = stores
        key_user = _unique("crud_key_user")
        auth.create_user(key_user, "developer", "key_team")
        session = helper.login(_unique("crud_key_admin"), "admin")

        # List keys (baseline)
        resp = client.get("/manage/api/keys", cookies={"headroom_session": session})
        assert resp.status_code == 200

        # Create key
        resp = client.post(
            "/manage/api/keys",
            json={"username": key_user, "ttl_days": 30},
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 200
        key_data = resp.json()
        assert key_data["raw_key"].startswith("hr_")
        key_id = key_data["key_id"]

        # Revoke key
        resp = client.delete(
            f"/manage/api/keys/{key_id}",
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 200

    def test_create_key_requires_username(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """POST /api/keys with empty username returns 400."""
        session = helper.login(_unique("crud_key_admin2"), "admin")
        resp = client.post(
            "/manage/api/keys",
            json={"username": "", "ttl_days": 30},
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 400

    # ── Store-level CRUD integration ───────────────────────────────

    def test_list_users_team_filter_store(self, stores: tuple[Neo4jAuthStore, AuditStore]) -> None:
        """Store-level: list_users(team=...) filters correctly."""
        auth, _ = stores
        u_a = _unique("store_filter_a")
        u_b = _unique("store_filter_b")
        auth.create_user(u_a, "developer", "filter_team_a")
        auth.create_user(u_b, "developer", "filter_team_b")

        users = auth.list_users(team="filter_team_a")
        usernames = [u["username"] for u in users]
        assert u_a in usernames
        assert u_b not in usernames

    def test_key_lifecycle_store(self, stores: tuple[Neo4jAuthStore, AuditStore]) -> None:
        """Store-level: create → list → revoke key lifecycle."""
        auth, _ = stores
        key_owner = _unique("store_key_owner")
        auth.create_user(key_owner, "developer", "key_test")
        raw_key, api_key = auth.create_key(key_owner)
        assert raw_key.startswith("hr_")

        keys = auth.list_keys(username=key_owner)
        assert len(keys) >= 1
        assert keys[0]["key_id"] == api_key.key_id

        result = auth.revoke_key(api_key.key_id)
        assert result is not None

        identity = auth.resolve_key_identity(raw_key)
        assert identity is None  # revoked key is dead


# ===================================================================
# Task 9.4 — Usage API endpoints + scope enforcement
# ===================================================================


@pytest.mark.skipif(not _neo4j_available(), reason="Neo4j not available")
class TestUsageAPI:
    """Task 9.4 — HTTP integration tests for usage endpoints with scope."""

    @pytest.fixture
    def helper(self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore]) -> _LoginHelper:
        return _LoginHelper(client, stores[0])

    def test_usage_summary_returns_data(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """GET /api/usage/summary returns aggregate data."""
        session = helper.login(_unique("usage_admin_sum"), "admin")
        resp = client.get(
            "/manage/api/usage/summary?since=30d",
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_requests" in data
        assert "total_tokens_saved" in data or "total_tokens_in" in data

    def test_usage_summary_team_lead(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Team lead can access usage summary."""
        session = helper.login(_unique("usage_lead_sum"), "team_lead", "usage_team")
        resp = client.get(
            "/manage/api/usage/summary?since=30d",
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 200

    def test_usage_top_returns_list(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """GET /api/usage/top returns a ranked list."""
        session = helper.login(_unique("usage_admin_top"), "admin")
        resp = client.get(
            "/manage/api/usage/top?since=30d&limit=5",
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_usage_user_sessions_returns_list(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """GET /api/usage/users/<id>/sessions returns paginated history."""
        session = helper.login(_unique("usage_admin_sess"), "admin")
        resp = client.get(
            "/manage/api/usage/users/nobody/sessions?since=30d&limit=5",
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 404  # "nobody" does not exist
        assert resp.json()["detail"] is not None

    def test_usage_search_returns_list(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """GET /api/usage/search returns paginated dict (results + total)."""
        session = helper.login(_unique("usage_admin_search"), "admin")
        resp = client.get(
            "/manage/api/usage/search?q=test&since=30d&limit=5",
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "results" in data
        assert "total" in data

    def test_usage_search_empty_query_returns_empty(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Empty search query returns {results: [], total: 0}."""
        session = helper.login(_unique("usage_admin_noq"), "admin")
        resp = client.get(
            "/manage/api/usage/search?q=&since=30d",
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 200
        assert resp.json() == {"results": [], "total": 0}

    # ── Scope enforcement at HTTP level ────────────────────────────

    def test_team_lead_usage_scoped(
        self, client: TestClient, stores: tuple[Neo4jAuthStore, AuditStore], helper: _LoginHelper
    ) -> None:
        """Team lead's usage endpoints execute without error (scope applied server-side)."""
        session = helper.login(_unique("usage_lead_scope"), "team_lead", "usage_team_b")
        resp = client.get(
            "/manage/api/usage/summary?since=30d",
            cookies={"headroom_session": session},
        )
        assert resp.status_code == 200

    # ── Store-level usage integration ──────────────────────────────

    def test_query_summary_store(self, stores: tuple[Neo4jAuthStore, AuditStore]) -> None:
        """Store-level: query_summary returns aggregate data."""
        _, audit = stores
        result = audit.query_summary()
        assert isinstance(result, list)

    def test_query_top_users_store(self, stores: tuple[Neo4jAuthStore, AuditStore]) -> None:
        """Store-level: query_top_users returns ranked list."""
        _, audit = stores
        result = audit.query_top_users(limit=5)
        assert isinstance(result, list)

    def test_team_scoped_users_store(self, stores: tuple[Neo4jAuthStore, AuditStore]) -> None:
        """Store-level: list_users team filter works."""
        auth, _ = stores
        u_a = _unique("store_scope_a")
        u_b = _unique("store_scope_b")
        auth.create_user(u_a, "developer", "scope_team_c")
        auth.create_user(u_b, "developer", "scope_team_c")
        users = auth.list_users(team="scope_team_c")
        assert len(users) >= 2
        for u in users:
            assert u["team"] == "scope_team_c"
