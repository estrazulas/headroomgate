"""Integration tests for Neo4jAuthStore (tasks 5.3, 5.5, 5.6, 5.7).

Requires Neo4j to be running (docker compose up -d neo4j).
Skip if NEO4J_URI is not reachable.
"""

import os
import sys

import pytest

from headroom.auth.crypto import FernetCrypto
from headroom.auth.store import AuthStoreError, Neo4jAuthStore


def _neo4j_available() -> bool:
    """Check if Neo4j is reachable."""
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


@pytest.fixture
def store() -> Neo4jAuthStore:
    """Create a store and clean up auth nodes after the test."""
    s = Neo4jAuthStore()
    s.init_db()
    return s


@pytest.mark.skipif(not _neo4j_available(), reason="Neo4j not available")
class TestNeo4jAuthStore:
    """Task 5.3 — CRUD for users/roles/teams/keys."""

    def test_init_db_idempotency(self, store: Neo4jAuthStore) -> None:
        """Task 5.5 — init-db idempotency."""
        result1 = store.init_db()
        result2 = store.init_db()
        # Both calls should succeed — second is idempotent
        assert result1["constraints_created"] >= 4
        assert result2["constraints_created"] >= 4
        # Base roles exist
        roles = store.list_roles()
        assert len(roles) >= 4

    def test_create_and_get_user(self, store: Neo4jAuthStore) -> None:
        store.create_user("testuser1", "developer", "test_team")
        user = store.get_user("testuser1")
        assert user is not None
        assert user.username == "testuser1"
        assert user.role == "developer"
        assert user.team == "test_team"

    def test_list_users(self, store: Neo4jAuthStore) -> None:
        store.create_user("u_list_a", "developer", "backend")
        store.create_user("u_list_b", "developer", "frontend")
        users = store.list_users()
        assert len(users) >= 2

    def test_list_users_filtered_by_team(self, store: Neo4jAuthStore) -> None:
        store.create_user("u_team_a", "developer", "backend")
        store.create_user("u_team_b", "developer", "frontend")
        users = store.list_users(team="backend")
        usernames = [u["username"] for u in users]
        assert "u_team_a" in usernames

    def test_update_user_status_revoke(self, store: Neo4jAuthStore) -> None:
        """Task 5.6 — soft-delete: revoked user's keys are also revoked."""
        store.create_user("revoke_test", "developer", "test_team")
        store.create_key("revoke_test")
        result = store.update_user_status("revoke_test", is_active=False)
        assert result is not None
        assert result["keys_revoked"] >= 1
        user = store.get_user("revoke_test")
        assert user is not None
        assert user.is_active is False

    def test_update_user_status_reactivate(self, store: Neo4jAuthStore) -> None:
        store.create_user("react_test", "developer", "test_team")
        store.update_user_status("react_test", is_active=False)
        store.update_user_status("react_test", is_active=True)
        user = store.get_user("react_test")
        assert user is not None
        assert user.is_active is True

    def test_create_and_list_teams(self, store: Neo4jAuthStore) -> None:
        store.create_team("backend_test")
        store.create_team("frontend_test")
        teams = store.list_teams()
        team_names = [t["name"] for t in teams]
        assert "backend_test" in team_names
        assert "frontend_test" in team_names

    def test_add_user_to_team(self, store: Neo4jAuthStore) -> None:
        store.create_team("new_team")
        store.create_user("team_user", "developer", "old_team")
        store.add_user_to_team("team_user", "new_team")
        user = store.get_user("team_user")
        assert user is not None
        assert user.team == "new_team"

    def test_create_and_list_keys(self, store: Neo4jAuthStore) -> None:
        store.create_user("key_user", "developer", "test_team")
        raw_key, api_key = store.create_key("key_user")
        assert raw_key.startswith("hr_")
        assert len(raw_key) > 40
        keys = store.list_keys(username="key_user")
        assert len(keys) >= 1
        assert keys[0]["key_prefix"] == raw_key[:10]

    def test_revoke_key(self, store: Neo4jAuthStore) -> None:
        store.create_user("revoke_key_user", "developer", "test_team")
        _, api_key = store.create_key("revoke_key_user")
        result = store.revoke_key(api_key.key_id)
        assert result is not None
        assert result["key_prefix"] is not None

    def test_get_key_owner(self, store: Neo4jAuthStore) -> None:
        store.create_user("owner_user", "developer", "test_team")
        raw_key, _ = store.create_key("owner_user")
        owner = store.get_key_owner(raw_key)
        assert owner is not None
        assert owner["username"] == "owner_user"
        assert owner["role"] == "developer"

    def test_get_key_owner_invalid_key(self, store: Neo4jAuthStore) -> None:
        result = store.get_key_owner("hr_invalid_key_never_created")
        assert result is None

    def test_provider_key_roundtrip(self, store: Neo4jAuthStore) -> None:
        """Task 5.7 — provider key roundtrip."""
        encryption_key = FernetCrypto.generate_key()
        os.environ["HEADROOM_ENCRYPTION_KEY"] = encryption_key
        try:
            store.set_provider_key("developer", "anthropic", "sk-ant-test123")
            provider_keys = store.list_provider_keys("developer")
            providers = [p["provider"] for p in provider_keys]
            assert "anthropic" in providers

            decrypted = store.get_provider_key("developer", "anthropic")
            assert decrypted == "sk-ant-test123"
        finally:
            del os.environ["HEADROOM_ENCRYPTION_KEY"]

    def test_create_and_list_roles(self, store: Neo4jAuthStore) -> None:
        store.create_role("test_role", "A test role")
        roles = store.list_roles()
        role_names = [r["name"] for r in roles]
        assert "test_role" in role_names
        assert "admin" in role_names

    def test_close(self, store: Neo4jAuthStore) -> None:
        store.close()
        # Close is idempotent
        store.close()
