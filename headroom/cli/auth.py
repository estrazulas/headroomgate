"""``headroom auth`` CLI — manage users, roles, teams, API keys, and provider keys."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import click

from headroom.auth.crypto import FernetCrypto, FernetCryptoError
from headroom.auth.store import AuthStoreError, Neo4jAuthStore

# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------


def _get_store() -> Neo4jAuthStore:
    """Build a Neo4j store from environment variables."""
    return Neo4jAuthStore()


def _get_crypto() -> FernetCrypto:
    """Build a Fernet crypto instance."""
    return FernetCrypto()


def _resolve_identity(as_user: str | None = None) -> dict[str, Any]:
    """Resolve the identity of the CLI operator.

    Reads ``HEADROOM_AUTH_USER`` env var or ``--as-user`` flag.
    Returns a dict with user_id, role, and team, or an empty dict
    if no identity is configured (effectively admin-like access).
    """
    identity = as_user or os.environ.get("HEADROOM_AUTH_USER", "")
    if not identity:
        return {}
    store = _get_store()
    try:
        user = store.get_user(identity)
        if user is None:
            return {}
        return {"user_id": user.user_id, "username": user.username, "role": user.role, "team": user.team}
    finally:
        store.close()


def _check_role(identity: dict[str, Any], allowed_roles: set[str]) -> None:
    """Raise ``click.UsageError`` if the operator's role is not allowed."""
    role = identity.get("role", "admin")
    if role not in allowed_roles:
        raise click.UsageError(
            f"Access denied: role '{role}' cannot perform this action. "
            f"Allowed roles: {', '.join(sorted(allowed_roles))}."
        )


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format a simple aligned table for terminal output."""
    if not rows:
        return "No results."
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    lines = [fmt.format(*headers), "-" * sum(col_widths) + "-" * (len(headers) * 2 - 2)]
    for row in rows:
        lines.append(fmt.format(*[str(c) for c in row]))
    return "\n".join(lines)


def _parse_json_flag(json_flag: bool) -> dict[str, Any]:
    """Return output format hint for commands."""
    return {"json": json_flag}


# ------------------------------------------------------------------
# Click group
# ------------------------------------------------------------------


@click.group(name="auth")
def auth_group() -> None:
    """Manage users, roles, teams, API keys, and provider keys.

    Requires Neo4j to be running (default: neo4j://localhost:7687).

    \b
    Quick start:
        headroom auth init-db
        headroom auth create-user joao --role developer --team backend
        headroom auth create-key joao
    """
    pass


# ------------------------------------------------------------------
# init-db
# ------------------------------------------------------------------


@auth_group.command(name="init-db")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def init_db_cmd(ctx: click.Context, yes: bool) -> None:
    """Initialize Neo4j constraints and base roles (idempotent)."""
    store = _get_store()
    try:
        if not yes:
            existing = store.list_roles()
            if existing:
                click.echo(
                    "Auth schema may already be initialized "
                    f"({len(existing)} roles exist). "
                    "Re-run init-db to verify constraints?"
                )
                if not click.confirm("Continue?", default=True):
                    click.echo("Aborted.")
                    ctx.exit(0)
        result = store.init_db()
        click.echo(
            f"Schema initialized: {result['constraints_created']} constraints, "
            f"{result['roles_created']} base roles ready."
        )
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


# ------------------------------------------------------------------
# user commands
# ------------------------------------------------------------------


@auth_group.command(name="create-user")
@click.argument("username")
@click.option("--role", "-r", required=True, help="Role name (admin, team_lead, developer, viewer).")
@click.option("--team", "-t", required=True, help="Team name.")
@click.option("--as-user", default=None, help="Operate as a specific user (for RBAC).")
@click.option("--json", "json_flag", is_flag=True, help="Output as JSON.")
@click.pass_context
def create_user_cmd(
    ctx: click.Context,
    username: str,
    role: str,
    team: str,
    as_user: str | None,
    json_flag: bool,
) -> None:
    """Create a new user."""
    identity = _resolve_identity(as_user)
    op_role = identity.get("role", "admin")
    if op_role not in {"admin", "team_lead"}:
        raise click.ClickException(
            "Access denied: only admin and team_lead can create users."
        )
    if op_role == "team_lead" and team != identity.get("team", ""):
        raise click.ClickException(
            f"Access denied: team_lead can only create users in team '{identity['team']}'."
        )
    store = _get_store()
    try:
        if not store.role_exists(role):
            raise click.ClickException(
                f"Role '{role}' does not exist. Use 'list-roles' to see available roles."
            )
        if store.user_exists(username):
            raise click.ClickException(
                f"Username '{username}' already exists. Use 'list-users' to check."
            )
        user = store.create_user(username, role, team)
        if json_flag:
            click.echo(json.dumps({
                "username": user.username,
                "role": user.role,
                "team": user.team,
                "user_id": user.user_id,
                "is_active": user.is_active,
            }))
        else:
            click.echo(
                f"User created: {user.username} (role: {user.role}, "
                f"team: {user.team}, id: {user.user_id})"
            )
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


@auth_group.command(name="list-users")
@click.option("--team", "-t", default=None, help="Filter by team name.")
@click.option("--json", "json_flag", is_flag=True, help="Output as JSON.")
@click.option("--as-user", default=None, help="Operate as a specific user.")
def list_users_cmd(team: str | None, json_flag: bool, as_user: str | None) -> None:
    """List all users."""
    identity = _resolve_identity(as_user)
    role = identity.get("role", "admin")
    store = _get_store()
    try:
        # Team lead sees only their team
        if role == "team_lead":
            team = identity["team"]
        elif role == "viewer":
            raise click.ClickException(
                "Access denied: viewer can only use 'whoami' and 'list-keys --self'."
            )
        users = store.list_users(team=team)
        if json_flag:
            click.echo(json.dumps(users, default=str))
        else:
            headers = ["username", "role", "team", "is_active", "keys"]
            rows = [
                [u["username"], u["role"], u["team"], str(u["is_active"]), str(u["key_count"])]
                for u in users
            ]
            click.echo(_format_table(headers, rows))
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


@auth_group.command(name="revoke-user")
@click.argument("username")
@click.option("--as-user", default=None, help="Operate as a specific user.")
def revoke_user_cmd(username: str, as_user: str | None) -> None:
    """Deactivate a user and all their keys."""
    identity = _resolve_identity(as_user)
    _check_role(identity, {"admin", "team_lead"})
    store = _get_store()
    try:
        if identity.get("role") == "team_lead":
            user = store.get_user(username)
            if user is None or user.team != identity["team"]:
                raise click.ClickException(
                    f"Access denied: you can only manage users in team '{identity['team']}'."
                )
        result = store.update_user_status(username, is_active=False)
        if result is None:
            raise click.ClickException(f"User '{username}' not found.")
        click.echo(f"User {username} deactivated. {result['keys_revoked']} key(s) revoked.")
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


@auth_group.command(name="reactivate-user")
@click.argument("username")
@click.option("--as-user", default=None, help="Operate as a specific user.")
def reactivate_user_cmd(username: str, as_user: str | None) -> None:
    """Reactivate a previously deactivated user."""
    identity = _resolve_identity(as_user)
    _check_role(identity, {"admin"})
    store = _get_store()
    try:
        result = store.update_user_status(username, is_active=True)
        if result is None:
            raise click.ClickException(f"User '{username}' not found.")
        click.echo(
            f"User {username} reactivated. "
            "Previously revoked keys remain inactive — create new keys with 'create-key'."
        )
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


# ------------------------------------------------------------------
# team commands
# ------------------------------------------------------------------


@auth_group.command(name="create-team")
@click.argument("name")
@click.option("--as-user", default=None, help="Operate as a specific user.")
def create_team_cmd(name: str, as_user: str | None) -> None:
    """Create a new team."""
    identity = _resolve_identity(as_user)
    _check_role(identity, {"admin"})
    store = _get_store()
    try:
        store.create_team(name)
        click.echo(f"Team created: {name}")
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


@auth_group.command(name="list-teams")
@click.option("--json", "json_flag", is_flag=True, help="Output as JSON.")
@click.option("--as-user", default=None, help="Operate as a specific user.")
def list_teams_cmd(json_flag: bool, as_user: str | None) -> None:
    """List all teams."""
    identity = _resolve_identity(as_user)
    _check_role(identity, {"admin", "team_lead"})
    store = _get_store()
    try:
        teams = store.list_teams()
        if json_flag:
            click.echo(json.dumps(teams, default=str))
        else:
            headers = ["team", "members", "active_members"]
            rows = [[t["name"], str(t["members"]), str(t["active_members"])] for t in teams]
            click.echo(_format_table(headers, rows))
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


@auth_group.command(name="add-user-to-team")
@click.argument("username")
@click.argument("team")
@click.option("--as-user", default=None, help="Operate as a specific user.")
def add_user_to_team_cmd(username: str, team: str, as_user: str | None) -> None:
    """Add a user to a team."""
    identity = _resolve_identity(as_user)
    _check_role(identity, {"admin"})
    store = _get_store()
    try:
        store.add_user_to_team(username, team)
        click.echo(f"User '{username}' added to team '{team}'.")
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


# ------------------------------------------------------------------
# key commands
# ------------------------------------------------------------------


@auth_group.command(name="create-key")
@click.argument("username")
@click.option("--ttl-days", default=90, type=int, help="Key expiration in days (default: 90).")
@click.option("--as-user", default=None, help="Operate as a specific user.")
def create_key_cmd(username: str, ttl_days: int, as_user: str | None) -> None:
    """Generate a new API key for a user. The key is displayed once."""
    identity = _resolve_identity(as_user)
    _check_role(identity, {"admin", "team_lead"})
    store = _get_store()
    try:
        if identity.get("role") == "team_lead":
            user = store.get_user(username)
            if user is None or user.team != identity["team"]:
                raise click.ClickException(
                    f"Access denied: you can only manage keys for users in team '{identity['team']}'."
                )
        raw_key, _ = store.create_key(username, ttl_days=ttl_days)
        click.echo(
            "API key generated (copy now — will not be displayed again):\n"
            + click.style(raw_key, bold=True, fg="yellow")
        )
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


@auth_group.command(name="list-keys")
@click.option("--user", "username", default=None, help="Filter by username.")
@click.option("--self", "self_flag", is_flag=True, help="List keys for the current user (uses HEADROOM_AUTH_USER).")
@click.option("--json", "json_flag", is_flag=True, help="Output as JSON.")
@click.option("--as-user", default=None, help="Operate as a specific user.")
def list_keys_cmd(
    username: str | None,
    self_flag: bool,
    json_flag: bool,
    as_user: str | None,
) -> None:
    """List API keys."""
    identity = _resolve_identity(as_user)
    role = identity.get("role", "admin")
    store = _get_store()
    try:
        if self_flag:
            if not identity:
                raise click.ClickException(
                    "HEADROOM_AUTH_USER not set. Set it or use --as-user."
                )
            username = identity["username"]
        if role == "team_lead" and username is None:
            # team_lead without --user sees only their team's keys
            pass  # list all via store; we limit by team below
        elif role == "viewer":
            if not self_flag:
                raise click.ClickException(
                    "Access denied: viewer can only use '--self' to see own keys."
                )
        keys = store.list_keys(username=username)
        # Filter by team for team_lead
        if role == "team_lead" and username is None:
            team = identity["team"]
            keys = [k for k in keys if k.get("team") == team
                    or store.get_user(k.get("username", "")) is not None
                    and (u := store.get_user(k.get("username", ""))) is not None
                    and u.team == team]
            # Simplified: filter after getting team info
            filtered = []
            for k in keys:
                u = store.get_user(k["username"])
                if u and u.team == team:
                    k["team"] = team
                    filtered.append(k)
            keys = filtered
        # Compute status for each key
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        for k in keys:
            if not k.get("is_active"):
                k["status"] = "revoked"
            elif k.get("expires_at"):
                expires = k["expires_at"]
                if isinstance(expires, datetime) and expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires < now:
                    k["status"] = "expired"
                else:
                    k["status"] = "active"
            else:
                k["status"] = "active"
        if json_flag:
            click.echo(json.dumps(keys, default=str))
        else:
            headers = ["key_id", "prefix", "status", "expires_at"]
            rows = [
                [k["key_id"], k["key_prefix"],
                 k.get("status", "active"),
                 str(k.get("expires_at", "—"))[:10]
                 + (f" ({_days_until(k['expires_at'])} days)" if k.get("expires_at") else "")]
                for k in keys
            ]
            click.echo(_format_table(headers, rows))
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


def _days_until(expires_at: Any) -> int:
    """Return days until expiration."""
    if expires_at is None:
        return 0
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    # Ensure timezone-aware for comparison
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    delta = expires_at - now
    return max(0, delta.days)


@auth_group.command(name="revoke-key")
@click.argument("key_id")
@click.option("--as-user", default=None, help="Operate as a specific user.")
def revoke_key_cmd(key_id: str, as_user: str | None) -> None:
    """Revoke an API key by its key_id."""
    identity = _resolve_identity(as_user)
    _check_role(identity, {"admin", "team_lead"})
    store = _get_store()
    try:
        result = store.revoke_key(key_id)
        if result is None:
            raise click.ClickException(f"Key '{key_id}' not found.")
        click.echo(f"Key {result['key_prefix']} revoked.")
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


# ------------------------------------------------------------------
# provider key commands
# ------------------------------------------------------------------


@auth_group.command(name="set-provider-key")
@click.argument("role")
@click.argument("provider")
@click.option("--stdin", "from_stdin", is_flag=True, help="Read the key from stdin instead of prompting.")
@click.option("--as-user", default=None, help="Operate as a specific user.")
def set_provider_key_cmd(
    role: str,
    provider: str,
    from_stdin: bool,
    as_user: str | None,
) -> None:
    """Store an encrypted provider API key for a role."""
    identity = _resolve_identity(as_user)
    _check_role(identity, {"admin"})
    # Validate encryption key is available
    try:
        _get_crypto().validate_key()
    except FernetCryptoError as exc:
        raise click.ClickException(str(exc)) from exc
    if from_stdin:
        api_key = sys.stdin.read().strip()
    else:
        api_key = click.prompt(
            f"Enter {provider} API key", hide_input=True, default=""
        )
    if not api_key:
        raise click.ClickException("API key cannot be empty.")
    # Validate by making a test request to the provider
    _validate_provider_key(provider, api_key)
    store = _get_store()
    try:
        result = store.set_provider_key(role, provider, api_key)
        verb = "stored" if result else "updated"
        click.echo(f"Key {provider} {verb} for role '{role}' (encrypted).")
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


def _validate_provider_key(provider: str, api_key: str) -> None:
    """Make a lightweight test request to verify the provider key is valid.

    Best-effort: if the test fails due to network issues, the key is still
    stored (the admin can retry). Only explicit auth failures are raised.
    """
    test_endpoints: dict[str, tuple[str, str]] = {
        "anthropic": ("GET", "https://api.anthropic.com/v1/messages?limit=1"),
        "openai": ("GET", "https://api.openai.com/v1/models?limit=1"),
        "gemini": ("GET", "https://generativelanguage.googleapis.com/v1beta/models?limit=1"),
    }
    info = test_endpoints.get(provider)
    if info is None:
        return  # Unknown provider — skip validation
    method, url = info
    try:
        import urllib.request
        req = urllib.request.Request(url, method=method)
        if provider == "anthropic":
            req.add_header("x-api-key", api_key)
            req.add_header("anthropic-version", "2023-06-01")
        elif provider == "openai":
            req.add_header("Authorization", f"Bearer {api_key}")
        elif provider == "gemini":
            req.add_header("x-goog-api-key", api_key)
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise click.ClickException(
                f"Error: {provider} API key is invalid or has insufficient permissions."
            ) from exc
        # Other HTTP errors (429, 500, etc.) — warn but don't block
        click.echo(
            f"Warning: {provider} validation returned HTTP {exc.code}. "
            "Key will be stored but may not work at runtime.",
            err=True,
        )
    except Exception as exc:
        click.echo(
            f"Warning: could not validate {provider} key (network error: {exc}). "
            "Key will be stored but may not work at runtime.",
            err=True,
        )


@auth_group.command(name="list-provider-keys")
@click.argument("role")
@click.option("--as-user", default=None, help="Operate as a specific user.")
def list_provider_keys_cmd(role: str, as_user: str | None) -> None:
    """List configured providers for a role (without revealing keys)."""
    identity = _resolve_identity(as_user)
    _check_role(identity, {"admin", "team_lead"})
    store = _get_store()
    try:
        keys = store.list_provider_keys(role)
        if keys:
            headers = ["provider", "status"]
            rows = [[k["provider"], k["status"]] for k in keys]
            click.echo(_format_table(headers, rows))
        else:
            click.echo(f"No provider keys configured for role '{role}'.")
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


# ------------------------------------------------------------------
# role commands
# ------------------------------------------------------------------


@auth_group.command(name="create-role")
@click.argument("name")
@click.option("--description", "-d", default="", help="Human-readable description.")
@click.option("--as-user", default=None, help="Operate as a specific user.")
def create_role_cmd(name: str, description: str, as_user: str | None) -> None:
    """Create a custom role."""
    identity = _resolve_identity(as_user)
    _check_role(identity, {"admin"})
    store = _get_store()
    try:
        store.create_role(name, description)
        click.echo(f"Role created: {name}")
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


@auth_group.command(name="list-roles")
@click.option("--as-user", default=None, help="Operate as a specific user.")
def list_roles_cmd(as_user: str | None) -> None:
    """List all roles."""
    identity = _resolve_identity(as_user)
    store = _get_store()
    try:
        roles = store.list_roles()
        headers = ["role", "description"]
        rows = [[r["name"], r.get("description", "")] for r in roles]
        click.echo(_format_table(headers, rows))
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


# ------------------------------------------------------------------
# whoami
# ------------------------------------------------------------------


@auth_group.command(name="whoami")
@click.option("--stdin", "from_stdin", is_flag=True, help="Read the key from stdin instead of prompting.")
def whoami_cmd(from_stdin: bool) -> None:
    """Resolve a proxy API key to its owner identity. Key is read via prompt."""
    if from_stdin:
        api_key = sys.stdin.read().strip()
    else:
        api_key = click.prompt("Enter proxy key", hide_input=True, default="")
    if not api_key:
        raise click.ClickException("API key cannot be empty.")
    store = _get_store()
    try:
        owner = store.get_key_owner(api_key)
        if owner is None:
            click.echo("Key not found or revoked.")
            ctx = click.get_current_context()
            ctx.exit(1)
        else:
            click.echo(f"Username: {owner['username']}")
            click.echo(f"Role: {owner['role']}")
            click.echo(f"Team: {owner['team']}")
            click.echo(f"Status: {owner['status']}")
    except AuthStoreError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()


# ------------------------------------------------------------------
# generate-key
# ------------------------------------------------------------------


@auth_group.command(name="generate-key")
def generate_key_cmd() -> None:
    """Generate a new Fernet encryption key for HEADROOM_ENCRYPTION_KEY."""
    key = FernetCrypto.generate_key()
    click.echo(key)
    click.echo("")
    click.echo("Copy the key above and export it:")
    click.echo(click.style("  export HEADROOM_ENCRYPTION_KEY=" + key, fg="yellow"))
    click.echo("")
    click.echo("⚠  Store this key in a secure location (1Password, Vault, etc.).")
    click.echo("   If lost, all encrypted provider keys become unrecoverable.")
