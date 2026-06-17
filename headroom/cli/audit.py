"""``headroom audit`` — query usage audit and analytics.

Structured queries (``user``, ``team``, ``top``, ``summary``) read from
Neo4j ``(:RequestLog)`` nodes. Semantic search (``search``) reads from
Qdrant ``headroom_request_logs`` collection. Access is scoped by role.

Registered in ``headroom/cli/main.py`` via ``_register_commands()``.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

import click

from .main import main

from rich.console import Console
from rich.table import Table

console = Console()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_duration(raw: str) -> datetime:
    """Parse ``--last 24h / 7d / 2w / 3m`` into a ``datetime`` threshold."""
    m = re.match(r"^(\d+)\s*(h|d|w|m)$", raw.strip())
    if not m:
        raise click.BadParameter(
            f"Invalid duration '{raw}'. Use format: 24h, 7d, 2w, 3m."
        )
    value = int(m.group(1))
    unit = m.group(2)
    now = datetime.now(timezone.utc)
    if unit == "h":
        return now - timedelta(hours=value)
    elif unit == "d":
        return now - timedelta(days=value)
    elif unit == "w":
        return now - timedelta(weeks=value)
    elif unit == "m":
        return now - timedelta(days=value * 30)
    return now


def _resolve_caller_identity() -> tuple[str, str, str, str] | None:
    """Resolve the caller from contextvars (proxy) or env key (CLI).

    Returns ``(user_id, username, role, team)`` or ``None``.
    """
    # Try contextvar first (inside proxy process)
    try:
        from headroom_auth.identity import (
            get_current_role,
            get_current_team,
            get_current_user,
            get_current_username,
        )

        uid = get_current_user()
        if uid:
            return (
                uid,
                get_current_username() or "?",
                get_current_role() or "viewer",
                get_current_team() or "",
            )
    except ImportError:
        pass

    # Fallback: resolve from HEADROOM_API_KEY via Neo4j
    api_key = os.environ.get("HEADROOM_API_KEY", "").strip()
    if api_key:
        try:
            from headroom.auth.store import Neo4jAuthStore

            store = Neo4jAuthStore()
            result = store.resolve_key_identity(api_key)
            if result:
                return (
                    result["user_id"],
                    result["username"],
                    result["role"],
                    result.get("team", ""),
                )
        except Exception:
            pass

    return None


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@main.group(name="audit")
def audit_group() -> None:
    """Query usage audit and analytics.

    Requires authenticated users (PRD 2). Role-based access:
    developer sees own data, team lead sees team, admin sees all.
    """
    pass


# ---------------------------------------------------------------------------
# audit user
# ---------------------------------------------------------------------------


@audit_group.command("user")
@click.argument("username", required=False)
@click.option("--self", "self_scope", is_flag=True, help="View your own usage.")
@click.option("--last", "last_duration", default="7d", help="Time range (e.g., 24h, 7d, 2w).")
@click.option("--by-day", is_flag=True, help="Break down by day.")
@click.option("--by-model", is_flag=True, help="Break down by model.")
@click.option("--history", is_flag=True, help="Show individual request history instead of aggregates.")
@click.option("--limit", "history_limit", type=int, default=25, help="Max entries with --history (1-100).")
def audit_user(
    username: str | None,
    self_scope: bool,
    last_duration: str,
    by_day: bool,
    by_model: bool,
    history: bool,
    history_limit: int,
) -> None:
    """Show usage for a specific user.

    \b
    Examples:
        headroom audit user alice --last 7d
        headroom audit user --self --last 7d --by-model
        headroom audit user alice --history --last 7d
        headroom audit user alice --history --last 7d --limit 10
    """
    from headroom.audit.access import AuditAccessError, enforce_scope, resolve_scope
    # Validate flags early — no Neo4j access needed
    if history and (by_day or by_model):
        raise click.UsageError(
            "--history is mutually exclusive with --by-day and --by-model."
        )
    history_limit = max(1, min(history_limit, 100))

    from headroom.audit.store import AuditStore

    identity = _resolve_caller_identity()
    if identity is None:
        click.echo("Error: could not resolve your identity. Set HEADROOM_API_KEY or run inside the proxy.", err=True)
        raise SystemExit(1)

    user_id, caller_username, role, team = identity
    scope = resolve_scope(user_id, caller_username, role, team)
    since = _parse_duration(last_duration)

    store = AuditStore()

    if self_scope:
        target_user_id = user_id
        display_name = caller_username
        target_team = scope.team
    elif username:
        try:
            enforce_scope(scope, target_user=username)
        except AuditAccessError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)
        # Resolve user_id from username via auth store
        from headroom.auth.store import Neo4jAuthStore

        auth = Neo4jAuthStore()
        user = auth.get_user(username)
        if user is None:
            click.echo(f"Error: user '{username}' not found.", err=True)
            raise SystemExit(1)
        target_user_id = user.user_id
        display_name = username
        target_team = user.team
    else:
        click.echo("Error: specify a username or --self.", err=True)
        raise SystemExit(1)

    # --- history mode ---
    if history:
        team_filter = None if scope.is_admin else scope.team
        rows = store.get_user_history(
            target_user_id, since=since, limit=history_limit, team=team_filter
        )

        table = Table(title=f"{display_name} — request history (last {last_duration})")
        table.add_column("Timestamp")
        table.add_column("Model")
        table.add_column("Tokens")
        table.add_column("Latency")
        table.add_column("Summary")

        for r in rows:
            ts = r.get("timestamp", "")
            if hasattr(ts, "strftime"):
                ts = ts.strftime("%Y-%m-%d %H:%M")
            summary = str(r.get("summary", "") or "")[:120]
            table.add_row(
                ts,
                str(r.get("model", "")),
                f"{r.get('input_tokens', 0):,}/{r.get('output_tokens', 0):,}",
                f"{r.get('latency_ms', 0):.0f}ms",
                summary,
            )
        console.print(table)
        store.close()
        return

    rows = store.query_user_usage(target_user_id, since=since, by_day=by_day, by_model=by_model)

    if by_day:
        table = Table(title=f"Usage for {display_name} — daily breakdown")
        table.add_column("Date")
        table.add_column("Requests")
        table.add_column("Tokens In")
        table.add_column("Tokens Out")
        table.add_column("Saved")
        for r in rows:
            table.add_row(
                str(r.get("date", "")),
                str(r.get("requests", 0)),
                f"{r.get('tokens_in', 0):,}",
                f"{r.get('tokens_out', 0):,}",
                f"{r.get('tokens_saved', 0):,}",
            )
        console.print(table)
    elif by_model:
        table = Table(title=f"Usage for {display_name} — by model")
        table.add_column("Model")
        table.add_column("Requests")
        table.add_column("Tokens In")
        table.add_column("Tokens Out")
        for r in rows:
            table.add_row(
                str(r.get("model", "")),
                str(r.get("requests", 0)),
                f"{r.get('tokens_in', 0):,}",
                f"{r.get('tokens_out', 0):,}",
            )
        console.print(table)
    else:
        r = rows[0] if rows else {}
        console.print(f"[bold]Usage for {display_name}[/bold]")
        console.print(f"Requests: {r.get('requests', 0):,}")
        console.print(f"Tokens: {r.get('tokens_in', 0):,} in / {r.get('tokens_out', 0):,} out")
        console.print(f"Saved: {r.get('tokens_saved', 0):,} tokens")
        console.print(f"Models: {r.get('model_count', 0)}")
        console.print(f"Cache hits: {r.get('cache_hits', 0)}")
        avg_lat = r.get("avg_latency_ms", 0)
        if avg_lat:
            console.print(f"Avg latency: {avg_lat:.0f}ms")


# ---------------------------------------------------------------------------
# audit team
# ---------------------------------------------------------------------------


@audit_group.command("team")
@click.argument("team_name", required=True)
@click.option("--last", "last_duration", default="7d", help="Time range.")
@click.option("--by-model", is_flag=True, help="Break down by model.")
def audit_team(team_name: str, last_duration: str, by_model: bool) -> None:
    """Show usage aggregated by team."""
    from headroom.audit.access import AuditAccessError, enforce_scope, resolve_scope
    from headroom.audit.store import AuditStore

    identity = _resolve_caller_identity()
    if identity is None:
        click.echo("Error: could not resolve your identity.", err=True)
        raise SystemExit(1)

    user_id, caller_username, role, team = identity
    scope = resolve_scope(user_id, caller_username, role, team)

    try:
        enforce_scope(scope, target_team=team_name)
    except AuditAccessError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    since = _parse_duration(last_duration)
    store = AuditStore()
    rows = store.query_team_usage(team_name, since=since, by_model=by_model)

    if by_model:
        table = Table(title=f"Team: {team_name} — by model")
        table.add_column("Model")
        table.add_column("Requests")
        table.add_column("Tokens In")
        table.add_column("Tokens Out")
        table.add_column("Users")
        for r in rows:
            table.add_row(
                str(r.get("model", "")),
                str(r.get("requests", 0)),
                f"{r.get('tokens_in', 0):,}",
                f"{r.get('tokens_out', 0):,}",
                str(r.get("users", "")),
            )
        console.print(table)
    else:
        r = rows[0] if rows else {}
        console.print(f"[bold]Team: {team_name}[/bold]")
        console.print(f"Requests: {r.get('requests', 0):,}")
        console.print(f"Tokens: {r.get('tokens_in', 0):,} in / {r.get('tokens_out', 0):,} out")
        console.print(f"Active users: {r.get('active_users', 0)}")
        console.print(f"Models: {r.get('model_count', 0)}")


# ---------------------------------------------------------------------------
# audit top
# ---------------------------------------------------------------------------


@audit_group.command("top")
@click.option("--by-tokens", "by_tokens", is_flag=True, default=True, help="Rank by tokens (default).")
@click.option("--by-requests", "by_requests", is_flag=True, help="Rank by request count.")
@click.option("--last", "last_duration", default="7d", help="Time range.")
@click.option("--limit", "limit", default=10, type=int, help="Number of users to show.")
def audit_top(last_duration: str, limit: int, by_tokens: bool, by_requests: bool) -> None:
    """Show top users by token or request consumption."""
    from headroom.audit.access import resolve_scope
    from headroom.audit.store import AuditStore

    identity = _resolve_caller_identity()
    if identity is None:
        click.echo("Error: could not resolve your identity.", err=True)
        raise SystemExit(1)

    since = _parse_duration(last_duration)
    store = AuditStore()
    rows = store.query_top_users(since=since, limit=limit, by_tokens=not by_requests)

    table = Table(title=f"Top {limit} users — last {last_duration}")
    table.add_column("Rank")
    table.add_column("Username")
    table.add_column("Team")
    table.add_column("Requests")
    table.add_column("Tokens In")
    for i, r in enumerate(rows, 1):
        table.add_row(
            str(i),
            str(r.get("username", "")),
            str(r.get("team", "")),
            str(r.get("requests", 0)),
            f"{r.get('tokens_in', 0):,}",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# audit summary
# ---------------------------------------------------------------------------


@audit_group.command("summary")
@click.option("--last", "last_duration", default="24h", help="Time range.")
def audit_summary(last_duration: str) -> None:
    """Show aggregate proxy usage totals."""
    from headroom.audit.store import AuditStore

    since = _parse_duration(last_duration)
    store = AuditStore()
    rows = store.query_summary(since=since)
    r = rows[0] if rows else {}

    total_req = r.get("total_requests", 0)
    total_in = r.get("total_tokens_in", 0) or 0
    total_out = r.get("total_tokens_out", 0) or 0
    cache_hits = r.get("cache_hits", 0)

    console.print(f"[bold]Audit Summary — last {last_duration}[/bold]")
    console.print(f"Total requests: {total_req:,}")
    console.print(f"Total tokens: {total_in:,} in / {total_out:,} out")
    console.print(f"Active users: {r.get('active_users', 0)}")
    console.print(f"Active models: {r.get('active_models', 0)}")
    if total_req > 0:
        console.print(f"Cache hit rate: {cache_hits / total_req * 100:.1f}%")
        saved = r.get("total_tokens_saved", 0) or 0
        total = total_in + total_out + saved
        if total > 0:
            console.print(f"Avg savings: {saved / total * 100:.1f}%")


# ---------------------------------------------------------------------------
# audit search
# ---------------------------------------------------------------------------


@audit_group.command("search")
@click.argument("query")
@click.option("--user", "filter_user", default=None, help="Filter by username.")
@click.option("--team", "filter_team", default=None, help="Filter by team.")
@click.option("--self", "self_scope", is_flag=True, help="Search own requests only.")
@click.option("--model", "filter_model", default=None, help="Filter by model.")
@click.option("--last", "last_duration", default="30d", help="Time range.")
@click.option("--min-score", "min_score", default=0.7, type=float, help="Minimum similarity (0-1).")
def audit_search(
    query: str,
    filter_user: str | None,
    filter_team: str | None,
    self_scope: bool,
    filter_model: str | None,
    last_duration: str,
    min_score: float,
) -> None:
    """Semantic search over request history (via Qdrant embeddings)."""
    from headroom.audit.access import AuditAccessError, enforce_scope, resolve_scope
    from headroom.audit.semantic import SemanticLogger

    identity = _resolve_caller_identity()
    if identity is None:
        click.echo("Error: could not resolve your identity.", err=True)
        raise SystemExit(1)

    user_id, caller_username, role, team = identity
    scope = resolve_scope(user_id, caller_username, role, team)

    if self_scope:
        resolved_user = user_id
    elif filter_user:
        try:
            enforce_scope(scope, target_user=filter_user)
        except AuditAccessError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)
        # Resolve user_id
        from headroom.auth.store import Neo4jAuthStore

        auth = Neo4jAuthStore()
        u = auth.get_user(filter_user)
        resolved_user = u.user_id if u else None
    else:
        # Scope to team if team lead
        resolved_user = None

    resolved_team = filter_team
    if not scope.is_admin and not filter_team:
        resolved_team = scope.allowed_teams[0] if len(scope.allowed_teams) == 1 else None

    try:
        enforce_scope(scope, target_user=filter_user, target_team=filter_team)
    except AuditAccessError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    since = _parse_duration(last_duration)
    semantic = SemanticLogger()

    if not semantic.is_available:
        click.echo(
            "Semantic search is not available — Qdrant is unreachable or fastembed is not installed.\n"
            "Structured queries (user, team, top, summary) are still available."
        )
        return

    results = semantic.search(
        query_text=query,
        user_id=resolved_user,
        team=resolved_team,
        model=filter_model,
        since=since,
        min_score=min_score,
    )

    if not results:
        console.print("No matching requests found.")
        return

    console.print(f"[bold]{len(results)} results[/bold] (similarity > {min_score}):")
    for i, r in enumerate(results, 1):
        console.print(f"\n[bold]{i}.[/bold] [{r.get('username', '?')}] — score: {r.get('score', 0):.2f}")
        console.print(f"  {r.get('summary', '')[:120]}...")
        console.print(f"  model: {r.get('model', '?')} | timestamp: {r.get('timestamp', '?')}")


# ---------------------------------------------------------------------------
# audit purge
# ---------------------------------------------------------------------------


@audit_group.command("purge")
@click.option("--before", "before_date", required=True, help="Purge records before this date (YYYY-MM-DD).")
@click.option("--yes", "skip_confirm", is_flag=True, help="Skip confirmation prompt.")
def audit_purge(before_date: str, skip_confirm: bool) -> None:
    """Remove audit data older than the given date (Neo4j + Qdrant)."""
    try:
        threshold = datetime.strptime(before_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        click.echo("Error: invalid date format. Use YYYY-MM-DD.", err=True)
        raise SystemExit(1)

    if not skip_confirm:
        click.echo(f"Remove all audit data before {before_date}? [y/N] ", nl=False)
        answer = input().strip().lower()
        if answer not in ("y", "yes"):
            click.echo("Aborted.")
            return

    from headroom.audit.semantic import SemanticLogger
    from headroom.audit.store import AuditStore

    store = AuditStore()
    neo4j_count = store.purge_before(threshold)

    semantic = SemanticLogger()
    qdrant_count = semantic.purge_before(threshold)

    click.echo(f"Removed: {neo4j_count} records from Neo4j + {qdrant_count} from Qdrant.")
