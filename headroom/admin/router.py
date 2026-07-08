"""Admin web interface router — mounted at ``/manage``.

Provides session-based authentication, user/team/key CRUD, usage
monitoring, and RBAC enforcement — all using the existing Neo4j
auth store and audit store.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from headroom.admin.session import AdminSessionStore
from headroom.auth.store import Neo4jAuthStore
from headroom.usage.store import AuditStore

log = logging.getLogger("headroom.admin")

# ---------------------------------------------------------------------------
# Shared instances (lazy-init)
# ---------------------------------------------------------------------------

_auth_store: Neo4jAuthStore | None = None
_audit_store: AuditStore | None = None
_anthropic_api_url: str = ""
_session_store: AdminSessionStore | None = None


async def init_admin(
    auth_store: Neo4jAuthStore | None = None,
    audit_store: AuditStore | None = None,
    anthropic_api_url: str | None = None,
) -> None:
    """Wire up the shared auth/audit stores and start the session store.

    Must be called from an async context (e.g. FastAPI lifespan).
    """
    global _auth_store, _audit_store, _anthropic_api_url

    if anthropic_api_url is not None:
        _anthropic_api_url = anthropic_api_url

    if auth_store is not None:
        _auth_store = auth_store
    if audit_store is not None:
        _audit_store = audit_store

    await _get_session_store().start_async()


def shutdown_admin() -> None:
    """Stop the session store background task."""
    import asyncio

    try:
        asyncio.create_task(_get_session_store().stop())
    except RuntimeError:
        pass


def _get_session_store() -> AdminSessionStore:
    global _session_store
    if _session_store is None:
        _session_store = AdminSessionStore()
    return _session_store


def _get_auth() -> Neo4jAuthStore:
    global _auth_store
    if _auth_store is None:
        _auth_store = Neo4jAuthStore()
    return _auth_store


def _get_audit() -> AuditStore:
    global _audit_store
    if _audit_store is None:
        _audit_store = AuditStore()
    return _audit_store


# ---------------------------------------------------------------------------
# Cost estimation (rough — for dashboard display only)
# ---------------------------------------------------------------------------

_ESTIMATED_INPUT_PRICE_PER_1M: dict[str, float] = {
    # Anthropic
    "claude-sonnet-4": 3.0,
    "claude-sonnet-4-20250514": 3.0,
    "claude-3-5-sonnet": 3.0,
    "claude-3-5-sonnet-20241022": 3.0,
    "claude-3-haiku": 0.25,
    "claude-3-opus": 15.0,
    "claude-opus-4": 15.0,
    "claude-opus-4-20250514": 15.0,
    "claude-thinking": 3.0,
    # OpenAI
    "gpt-4o": 2.50,
    "gpt-4o-mini": 0.15,
    "o3": 10.0,
    "o4": 10.0,
    # Google
    "gemini-2.0-flash": 0.10,
    "gemini-2.5-pro": 1.25,
    "gemini-2.5-flash": 0.075,
    # DeepSeek
    "deepseek-chat": 0.27,
    "deepseek-reasoner": 0.55,
    "default": 3.0,  # fallback: Claude Sonnet pricing
}


def _estimate_savings_usd(model: str, tokens_saved: int) -> float:
    """Rough dollar estimate of tokens saved at model list price."""
    _prices = _ESTIMATED_INPUT_PRICE_PER_1M

    # When DeepSeek is the Anthropic API backend, the model name in the log
    # reflects what the client *asked for* (e.g. claude-sonnet-4-…), not the
    # actual backend model.  Use the canonical DeepSeek pricing registry.
    if "deepseek" in _anthropic_api_url.lower():
        from headroom.pricing.deepseek_prices import get_deepseek_registry

        reg = get_deepseek_registry()
        cost = reg.estimate_cost("deepseek-v4-flash", input_tokens=tokens_saved)
        return round(cost.cost_usd, 4)

    price = _ESTIMATED_INPUT_PRICE_PER_1M.get("default", 3.0)
    for key, val in _ESTIMATED_INPUT_PRICE_PER_1M.items():
        if key in model:
            price = val
            break
    return round(tokens_saved / 1_000_000 * price, 4)


# ---------------------------------------------------------------------------
# Session cookie helpers
# ---------------------------------------------------------------------------

_COOKIE_NAME = "headroom_session"
_SESSION_TTL_SECONDS = 28800  # 8 hours

ADMIN_ROLES = frozenset({"admin"})
LEAD_ROLES = frozenset({"admin", "team_lead"})


async def _resolve_session(session_id: str | None) -> dict[str, Any] | None:
    """Look up a session and return its data, or None."""
    if session_id is None:
        return None
    return await _get_session_store().get(session_id)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=_SESSION_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        path="/manage",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=_COOKIE_NAME, path="/manage")


def _enforce_role(user: dict[str, Any] | None, allowed_roles: frozenset) -> None:
    """Raise 401/403 if user is missing or lacks the required role."""
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user.get("role") not in allowed_roles:
        raise HTTPException(status_code=403, detail="Forbidden")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def _require_user(
    headroom_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    user = await _resolve_session(headroom_session)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def _require_admin_or_lead(
    headroom_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    user = await _resolve_session(headroom_session)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user.get("role") not in LEAD_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


async def _require_admin(
    headroom_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    user = await _resolve_session(headroom_session)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _render(name: str, **context: Any) -> str:
    """Render a Jinja2 template."""
    from starlette.templating import Jinja2Templates

    result = Jinja2Templates(directory=str(TEMPLATES_DIR)).get_template(name).render(**context)
    return str(result)


def _page_context(
    user: dict[str, Any], title: str, active_nav: str = "", **extra: Any
) -> dict[str, Any]:
    ctx = {
        "username": user.get("username", ""),
        "role": user.get("role", ""),
        "user_role": user.get("role", ""),
        "user_team": user.get("team", ""),
        "current_year": datetime.now(timezone.utc).year,
        "title": title,
        "active_nav": active_nav,
    }
    ctx.update(extra)
    return ctx


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()


# ── Authentication ────────────────────────────────────────────────────────


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    headroom_session: str | None = Cookie(default=None),
) -> str:
    """Show login page."""
    user = await _resolve_session(headroom_session)
    if user is not None:
        return "<html><body><script>window.location.href='/manage';</script></body></html>"
    return _render("login.html")


@router.post("/login")
async def login(
    headroomgate_key: str = Form(...),
) -> Response:
    """Validate hr_* key, create session, set httpOnly cookie."""
    store = _get_auth()
    identity = store.resolve_key_identity(headroomgate_key)
    if identity is None:
        return HTMLResponse(
            _render(
                "login.html", error="Invalid API key. Make sure the key is active and not expired."
            )
        )

    session_data = {
        "user_id": identity["user_id"],
        "username": identity["username"],
        "role": identity["role"],
        "team": identity.get("team", ""),
    }
    token = await _get_session_store().create(session_data)

    resp = RedirectResponse(url="/manage", status_code=303)
    _set_session_cookie(resp, token)
    return resp


@router.post("/logout")
async def logout() -> Response:
    """Delete session and clear cookie."""
    resp = RedirectResponse(url="/manage/login", status_code=303)
    _clear_session_cookie(resp)
    return resp


# ── Pages (auth-required) ────────────────────────────────────────────────


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_index() -> str:
    """Redirect to users page."""
    return "<html><body><script>window.location.href='/manage/users';</script></body></html>"


@router.get("/access-denied", response_class=HTMLResponse)
async def access_denied() -> str:
    return _render("access_denied.html")


@router.get("/users", response_class=HTMLResponse)
async def users_page(user: dict[str, Any] = Depends(_require_admin_or_lead)) -> str:
    if user.get("role") in ("developer", "viewer"):
        return _render("access_denied.html")
    return _render("users.html", **_page_context(user, title="Users", active_nav="users"))


@router.get("/teams", response_class=HTMLResponse)
async def teams_page(user: dict[str, Any] = Depends(_require_admin)) -> str:
    return _render("teams.html", **_page_context(user, title="Teams", active_nav="teams"))


@router.get("/keys", response_class=HTMLResponse)
async def keys_page(user: dict[str, Any] = Depends(_require_admin_or_lead)) -> str:
    if user.get("role") in ("developer", "viewer"):
        return _render("access_denied.html")
    return _render("keys.html", **_page_context(user, title="API Keys", active_nav="keys"))


@router.get("/usage", response_class=HTMLResponse)
async def usage_page(user: dict[str, Any] = Depends(_require_admin_or_lead)) -> str:
    if user.get("role") in ("developer", "viewer"):
        return _render("access_denied.html")
    return _render("usage.html", **_page_context(user, title="Usage", active_nav="usage"))


@router.get("/roles", response_class=HTMLResponse)
async def roles_page(user: dict[str, Any] = Depends(_require_admin)) -> str:
    return _render("roles.html", **_page_context(user, title="Roles", active_nav="roles"))


# ── User management API ──────────────────────────────────────────────────


@router.get("/api/users")
async def api_list_users(
    user: dict[str, Any] = Depends(_require_admin_or_lead),
) -> list[dict[str, Any]]:
    """List users with RBAC scoping."""
    store = _get_auth()
    team_filter: str | None = None
    if user["role"] == "team_lead":
        team_filter = user.get("team")
    return store.list_users(team=team_filter)


@router.post("/api/users")
async def api_create_user(
    request: Request,
    user: dict[str, Any] = Depends(_require_admin_or_lead),
) -> dict[str, Any]:
    """Create a new user (team_lead only in own team)."""
    body = await request.json()
    username = body.get("username", "").strip()
    role = body.get("role", "developer").strip()
    team = body.get("team", "").strip()

    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if not team:
        raise HTTPException(status_code=400, detail="Team is required")
    if user["role"] == "team_lead" and team != user.get("team"):
        raise HTTPException(status_code=403, detail="Cannot create user outside your team")

    store = _get_auth()
    if store.user_exists(username):
        raise HTTPException(status_code=409, detail=f"User '{username}' already exists")
    # Non-admin users can only create users in existing teams
    if user.get("role") != "admin" and not store.team_exists(team):
        raise HTTPException(
            status_code=400, detail=f"Team '{team}' does not exist. Create it first."
        )

    new_user = store.create_user(username=username, role=role, team=team)
    return {
        "user_id": new_user.user_id,
        "username": new_user.username,
        "role": new_user.role,
        "team": new_user.team,
        "is_active": new_user.is_active,
        "created_at": new_user.created_at.isoformat(),
    }


@router.put("/api/users/{username}/status")
async def api_update_user_status(
    username: str,
    request: Request,
    user: dict[str, Any] = Depends(_require_admin_or_lead),
) -> dict[str, Any]:
    """Activate/deactivate a user."""
    body = await request.json()
    is_active = body.get("is_active", True)

    # Cannot deactivate yourself
    if username == user.get("username"):
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    store = _get_auth()
    if user["role"] == "team_lead":
        target = store.get_user(username)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        if target.team != user.get("team"):
            raise HTTPException(status_code=403, detail="Cannot manage user outside your team")

    result = store.update_user_status(username, is_active)
    if result is None:
        raise HTTPException(status_code=404, detail="User not found")
    return result


# ── Team management API ──────────────────────────────────────────────────


@router.get("/api/teams")
async def api_list_teams(
    user: dict[str, Any] = Depends(_require_admin_or_lead),
) -> list[dict[str, Any]]:
    """List teams with member counts."""
    store = _get_auth()
    if user["role"] == "team_lead":
        return [t for t in store.list_teams() if t["name"] == user.get("team")]
    return store.list_teams()


@router.post("/api/teams")
async def api_create_team(
    request: Request,
    user: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Create a team (admin only)."""
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Team name is required")

    store = _get_auth()
    if store.team_exists(name):
        raise HTTPException(status_code=409, detail=f"Team '{name}' already exists")

    team = store.create_team(name)
    return {"name": team.name, "created_at": team.created_at.isoformat()}


@router.post("/api/teams/{team_name}/users")
async def api_add_user_to_team(
    team_name: str,
    request: Request,
    user: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Add user to a team (admin only)."""
    body = await request.json()
    username = body.get("username", "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    store = _get_auth()
    if store.get_user(username) is None:
        raise HTTPException(status_code=404, detail="User not found")

    store.add_user_to_team(username, team_name)
    return {"username": username, "team": team_name}


# ── API key management ───────────────────────────────────────────────────


@router.get("/api/keys")
async def api_list_keys(
    user: dict[str, Any] = Depends(_require_admin_or_lead),
) -> list[dict[str, Any]]:
    """List keys with RBAC scoping."""
    store = _get_auth()
    all_keys = store.list_keys()
    if user["role"] == "team_lead":
        team_users = store.list_users(team=user.get("team", ""))
        team_usernames = {u["username"] for u in team_users}
        return [k for k in all_keys if k.get("username") in team_usernames]
    return all_keys


@router.post("/api/keys")
async def api_create_key(
    request: Request,
    user: dict[str, Any] = Depends(_require_admin_or_lead),
) -> dict[str, Any]:
    """Generate a new API key. Returns full key once."""
    body = await request.json()
    username = body.get("username", "").strip()
    ttl_days = int(body.get("ttl_days", 90))
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    store = _get_auth()

    # Validate user exists (for all roles)
    target = store.get_user(username)
    if target is None:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")

    # Team leads can only create keys for their own team
    if user["role"] == "team_lead":
        if target.team != user.get("team"):
            raise HTTPException(
                status_code=403, detail="Cannot create key for user outside your team"
            )

    raw_key, api_key_model = store.create_key(username, ttl_days=ttl_days)
    return {
        "raw_key": raw_key,
        "key_prefix": api_key_model.key_prefix,
        "key_id": api_key_model.key_id,
        "username": username,
        "expires_at": api_key_model.expires_at.isoformat(),
    }


@router.delete("/api/keys/{key_id}")
async def api_revoke_key(
    key_id: str,
    user: dict[str, Any] = Depends(_require_admin_or_lead),
) -> dict[str, Any]:
    """Revoke a key by key_id."""
    store = _get_auth()
    all_keys = store.list_keys()
    target_key = next((k for k in all_keys if k["key_id"] == key_id), None)
    if target_key is None:
        raise HTTPException(status_code=404, detail="Key not found")

    # Cannot revoke your own key
    if target_key.get("username") == user.get("username"):
        raise HTTPException(status_code=400, detail="Cannot revoke your own key")

    if user["role"] == "team_lead":
        target_user = store.get_user(target_key.get("username", ""))
        if target_user is None or target_user.team != user.get("team"):
            raise HTTPException(status_code=403, detail="Cannot revoke key outside your team")

    result = store.revoke_key(key_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return result


# ── Role & provider key management API ────────────────────────────────────

_ALLOWED_PROVIDERS = frozenset({"anthropic", "openai", "gemini"})


@router.get("/api/roles")
async def api_list_roles(
    user: dict[str, Any] = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """List all roles with provider counts (admin only)."""
    store = _get_auth()
    roles = store.list_roles()
    # Enrich with provider count
    for role in roles:
        try:
            keys = store.list_provider_keys(role["name"])
            role["provider_count"] = len(keys)  # type: ignore[assignment]
        except Exception:
            role["provider_count"] = 0  # type: ignore[assignment]
    return roles


@router.get("/api/roles/{role_name}/providers")
async def api_list_role_providers(
    role_name: str,
    user: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """List configured providers for a role (without key values)."""
    store = _get_auth()
    try:
        keys = store.list_provider_keys(role_name)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"role": role_name, "providers": keys}


@router.post("/api/roles/{role_name}/providers/{provider}")
async def api_set_role_provider_key(
    role_name: str,
    provider: str,
    request: Request,
    user: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Set a provider key for a role (admin only, encrypts with Fernet)."""
    # Protect admin role
    if role_name == "admin":
        raise HTTPException(
            status_code=403,
            detail="The admin role is protected. Use the CLI to manage its provider keys.",
        )

    # Validate provider name
    if provider.lower() not in _ALLOWED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider}'. Allowed: {', '.join(sorted(_ALLOWED_PROVIDERS))}",
        )

    # Check encryption key availability
    if not os.environ.get("HEADROOM_ENCRYPTION_KEY"):
        raise HTTPException(
            status_code=400,
            detail="HEADROOM_ENCRYPTION_KEY is not set. Generate one with: headroom auth generate-key",
        )

    body = await request.json()
    key_value = body.get("key", "").strip()
    if not key_value:
        raise HTTPException(status_code=400, detail="Provider key is required")

    store = _get_auth()
    try:
        store.set_provider_key(role_name, provider.lower(), key_value)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"role": role_name, "provider": provider.lower(), "configured": True}


@router.delete("/api/roles/{role_name}/providers/{provider}")
async def api_remove_role_provider_key(
    role_name: str,
    provider: str,
    user: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Remove a provider key from a role (admin only)."""
    # Protect admin role
    if role_name == "admin":
        raise HTTPException(
            status_code=403,
            detail="The admin role is protected. Use the CLI to manage its provider keys.",
        )

    # Validate provider name
    if provider.lower() not in _ALLOWED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider}'. Allowed: {', '.join(sorted(_ALLOWED_PROVIDERS))}",
        )

    store = _get_auth()
    try:
        result = store.remove_provider_key(role_name, provider.lower())
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return result


# ── Usage monitoring API ─────────────────────────────────────────────────


def _since_param(since: str | None) -> datetime | None:
    if since is None:
        return None
    now = datetime.now(timezone.utc)
    from datetime import timedelta

    if since == "24h":
        return now - timedelta(hours=24)
    if since == "7d":
        return now - timedelta(days=7)
    if since == "30d":
        return now - timedelta(days=30)
    return None


@router.get("/api/usage/summary")
async def api_usage_summary(
    since: str = "7d",
    user: dict[str, Any] = Depends(_require_admin_or_lead),
) -> dict[str, Any]:
    """Aggregate usage metrics."""
    since_dt = _since_param(since)
    audit = _get_audit()

    if user["role"] == "team_lead":
        result = audit.query_team_usage(team=user.get("team", ""), since=since_dt)
        if result:
            r = result[0]
            tokens_saved = r.get("tokens_saved", 0) or 0
            return {
                "total_requests": r.get("requests", 0),
                "total_tokens_in": r.get("tokens_in", 0),
                "total_tokens_out": r.get("tokens_out", 0),
                "total_tokens_saved": tokens_saved,
                "cost_saved_usd": _estimate_savings_usd("default", tokens_saved),
                "active_users": r.get("active_users", 0),
                "model_count": r.get("model_count", 0),
            }

    result = audit.query_summary(since=since_dt)
    if result:
        r = result[0]
        tokens_saved = r.get("total_tokens_saved", 0) or 0
        return {
            "total_requests": r.get("total_requests", 0),
            "total_tokens_in": r.get("total_tokens_in", 0),
            "total_tokens_out": r.get("total_tokens_out", 0),
            "total_tokens_saved": tokens_saved,
            "cost_saved_usd": _estimate_savings_usd("default", tokens_saved),
            "active_users": r.get("active_users", 0),
            "active_models": r.get("active_models", 0),
            "cache_hits": r.get("cache_hits", 0),
        }
    return {
        "total_requests": 0,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "total_tokens_saved": 0,
        "cost_saved_usd": 0.0,
        "active_users": 0,
    }


@router.get("/api/usage/top")
async def api_usage_top(
    since: str = "7d",
    limit: int = 10,
    user: dict[str, Any] = Depends(_require_admin_or_lead),
) -> list[dict[str, Any]]:
    """Top consumers by token usage."""
    since_dt = _since_param(since)
    audit = _get_audit()
    if user["role"] == "team_lead":
        team_users = _get_auth().list_users(team=user.get("team", ""))
        user_ids = {u["user_id"] for u in team_users}
        return [
            t
            for t in audit.query_top_users(since=since_dt, limit=50, by_tokens=True)
            if t.get("user_id") in user_ids
        ][:limit]
    return audit.query_top_users(since=since_dt, limit=limit, by_tokens=True)


@router.get("/api/usage/users/{user_id_or_username}/sessions")
async def api_user_sessions(
    user_id_or_username: str,
    since: str = "7d",
    limit: int = 25,
    offset: int = 0,
    user: dict[str, Any] = Depends(_require_admin_or_lead),
) -> dict[str, Any]:
    """Paginated user request history.

    Accepts either a ``user_id`` (``u_...``) or a ``username`` in the path.
    Usernames are resolved to user_ids server-side.
    Returns ``{sessions: [...], total: int}``.
    """
    since_dt = _since_param(since)
    audit = _get_audit()
    store = _get_auth()

    # Resolve username → user_id if the segment is not already a u_ id
    actual_user_id = user_id_or_username
    if not user_id_or_username.startswith("u_"):
        resolved = store.get_user(user_id_or_username)
        if resolved is None:
            raise HTTPException(status_code=404, detail=f"User '{user_id_or_username}' not found")
        actual_user_id = resolved.user_id

    team_filter: str | None = user.get("team") if user["role"] == "team_lead" else None
    total = audit.get_user_history_count(user_id=actual_user_id, since=since_dt, team=team_filter)
    sessions = audit.get_user_history(
        user_id=actual_user_id,
        since=since_dt,
        limit=min(limit, 100),
        offset=offset,
        team=team_filter,
    )
    # Enrich with cost estimate
    for s in sessions:
        saved = s.get("tokens_saved", 0) or 0
        model = s.get("model", "")
        s["cost_saved_usd"] = _estimate_savings_usd(model, saved)
    return {"sessions": sessions, "total": total}


@router.get("/api/usage/search")
async def api_usage_search(
    q: str = "",
    since: str = "7d",
    limit: int = 10,
    offset: int = 0,
    username: str | None = None,
    user: dict[str, Any] = Depends(_require_admin_or_lead),
) -> dict[str, Any]:
    """Semantic search via Qdrant with RBAC scoping and pagination.

    Returns ``{results: [...], total: int}``.
    """
    if not q.strip():
        return {"results": [], "total": 0}
    since_dt = _since_param(since)

    from headroom.usage.semantic import SemanticLogger

    searcher = SemanticLogger()
    team_filter: str | None = user.get("team") if user["role"] == "team_lead" else None

    # Resolve username → user_id if a username filter is given
    user_id_filter: str | None = None
    if username:
        store = _get_auth()
        resolved = store.get_user(username)
        if resolved is not None:
            user_id_filter = resolved.user_id
        else:
            return {"results": [], "total": 0}

    # Fetch limit+offset+1 to determine has_more
    fetch_limit = limit + offset + 1
    results = searcher.search(
        query_text=q,
        team=team_filter,
        since=since_dt,
        user_id=user_id_filter,
        limit=fetch_limit,
        min_score=0.7,
    )

    if user["role"] == "team_lead":
        team_usernames = {u["username"] for u in _get_auth().list_users(team=user.get("team", ""))}
        results = [r for r in results if r.get("username") in team_usernames]

    total = len(results)
    page = results[offset : offset + limit]
    return {"results": page, "total": total}
