"""Unit tests for identity contextvars (PRD 2 tasks 3.1-3.2)."""

import asyncio

import pytest

from headroom_auth.identity import (
    clear_current_identity,
    get_current_role,
    get_current_team,
    get_current_user,
    get_current_username,
    set_current_identity,
)


class TestIdentityContextVars:
    """ContextVar-based identity propagation."""

    def test_set_and_get_identity(self) -> None:
        set_current_identity("u_abc123", "joao", "developer", "backend")
        assert get_current_user() == "u_abc123"
        assert get_current_username() == "joao"
        assert get_current_role() == "developer"
        assert get_current_team() == "backend"

    def test_clear_identity(self) -> None:
        set_current_identity("u_xyz", "maria", "admin", "platform")
        clear_current_identity()
        assert get_current_user() is None
        assert get_current_username() is None
        assert get_current_role() is None
        assert get_current_team() is None

    def test_identity_starts_none(self) -> None:
        # Always clear before asserting — other tests may have set it
        clear_current_identity()
        assert get_current_user() is None

    def test_overwrite_identity(self) -> None:
        set_current_identity("u_1", "alice", "viewer", "frontend")
        set_current_identity("u_2", "bob", "developer", "backend")
        assert get_current_user() == "u_2"
        assert get_current_username() == "bob"

    def test_identity_unset_returns_none_for_all_getters(self) -> None:
        clear_current_identity()
        assert get_current_user() is None
        assert get_current_username() is None
        assert get_current_role() is None
        assert get_current_team() is None

    def test_identity_isolation_between_tasks(self) -> None:
        """Each task should see its own identity (simulated via contextvars copy)."""
        import contextvars

        # Simulate what happens with async tasks: each task gets its own
        # copy of the context, so identity set in one doesn't leak to another.
        ctx1 = contextvars.copy_context()
        ctx2 = contextvars.copy_context()

        results: list[tuple[str | None, str | None]] = []

        def task_a() -> None:
            set_current_identity("u_a", "alice", "dev", "t1")
            results.append((get_current_user(), get_current_username()))
            clear_current_identity()

        def task_b() -> None:
            set_current_identity("u_b", "bob", "admin", "t2")
            results.append((get_current_user(), get_current_username()))
            clear_current_identity()

        ctx1.run(task_a)
        ctx2.run(task_b)

        users = {r[0] for r in results}
        assert "u_a" in users
        assert "u_b" in users
