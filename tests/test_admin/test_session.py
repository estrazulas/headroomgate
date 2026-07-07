"""Unit tests for AdminSessionStore (Task 9.1)."""

import asyncio

import pytest

from headroom.admin.session import AdminSessionStore


@pytest.fixture
def session_store() -> AdminSessionStore:
    """Create a session store with short TTL for testing."""
    return AdminSessionStore(ttl_seconds=60, cleanup_interval=5)


@pytest.mark.asyncio
class TestAdminSessionStore:
    """Task 9.1 — Unit tests for AdminSessionStore."""

    async def test_create_and_get_session(self, session_store: AdminSessionStore) -> None:
        """Create a session and resolve it."""
        token = await session_store.create(
            {"user_id": "u_test", "username": "testuser", "role": "admin"}
        )
        assert isinstance(token, str)
        assert len(token) == 64  # 256-bit hex

        data = await session_store.get(token)
        assert data is not None
        assert data["username"] == "testuser"
        assert data["role"] == "admin"

    async def test_get_missing_session(self, session_store: AdminSessionStore) -> None:
        """Non-existent token returns None."""
        result = await session_store.get("nonexistenttoken123")
        assert result is None

    async def test_get_expired_session(self) -> None:
        """Expired session returns None."""
        store = AdminSessionStore(ttl_seconds=0)  # expires immediately
        token = await store.create({"user_id": "u_expire", "username": "expired", "role": "viewer"})
        # Small delay to ensure expiry
        await asyncio.sleep(0.01)
        data = await store.get(token)
        assert data is None

    async def test_delete_session(self, session_store: AdminSessionStore) -> None:
        """Deleting a session removes it."""
        token = await session_store.create(
            {"user_id": "u_del", "username": "del", "role": "developer"}
        )
        deleted = await session_store.delete(token)
        assert deleted is True

        # Should no longer resolve
        data = await session_store.get(token)
        assert data is None

    async def test_delete_missing_session(self, session_store: AdminSessionStore) -> None:
        """Deleting a non-existent session returns False."""
        deleted = await session_store.delete("nonexistent")
        assert deleted is False

    async def test_cleanup_expired(self) -> None:
        """Background cleanup removes expired sessions."""
        store = AdminSessionStore(ttl_seconds=0, cleanup_interval=1)
        token1 = await store.create({"user_id": "u1", "username": "u1", "role": "admin"})
        token2 = await store.create({"user_id": "u2", "username": "u2", "role": "developer"})
        await asyncio.sleep(0.05)

        # Both should be gone (immediate TTL)
        assert await store.get(token1) is None
        assert await store.get(token2) is None

    async def test_multiple_sessions(self, session_store: AdminSessionStore) -> None:
        """Multiple independent sessions work correctly."""
        t1 = await session_store.create({"username": "alice"})
        t2 = await session_store.create({"username": "bob"})
        t3 = await session_store.create({"username": "charlie"})

        assert (await session_store.get(t1))["username"] == "alice"
        assert (await session_store.get(t2))["username"] == "bob"
        assert (await session_store.get(t3))["username"] == "charlie"

        await session_store.delete(t2)
        assert await session_store.get(t2) is None
        assert (await session_store.get(t1))["username"] == "alice"
        assert (await session_store.get(t3))["username"] == "charlie"

    async def test_active_count(self, session_store: AdminSessionStore) -> None:
        """Active count reflects the number of non-expired sessions."""
        assert session_store.active_count == 0
        await session_store.create({"username": "a"})
        assert session_store.active_count == 1
        await session_store.create({"username": "b"})
        assert session_store.active_count == 2

    async def test_concurrent_access(self, session_store: AdminSessionStore) -> None:
        """Concurrent create/get/delete operations don't corrupt state."""

        async def _worker(name: str) -> str:
            token = await session_store.create({"username": name})
            data = await session_store.get(token)
            assert data is not None
            assert data["username"] == name
            await session_store.delete(token)
            assert await session_store.get(token) is None
            return token

        results = await asyncio.gather(*[_worker(f"user_{i}") for i in range(10)])
        assert len(results) == 10
        assert len(set(results)) == 10  # all unique
