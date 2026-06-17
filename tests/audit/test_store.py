"""Tests for AuditStore Neo4j queries (PRD 3 task 2.1-2.3).

All tests are Neo4j-dependent — skip if unavailable.
"""

import os
from datetime import datetime, timezone

import pytest


def _neo4j_available() -> bool:
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


@pytest.mark.skipif(not _neo4j_available(), reason="Neo4j not available")
class TestAuditStore:
    @pytest.fixture
    def store(self):
        from headroom.audit.store import AuditStore
        return AuditStore()

    def test_insert_batch_empty(self, store) -> None:
        assert store.insert_batch([]) == 0

    def test_insert_batch_and_query_summary(self, store) -> None:
        from headroom.auth.store import Neo4jAuthStore
        auth = Neo4jAuthStore()
        auth.init_db()
        # Ensure user exists
        try:
            auth.create_user("audit_test_user", "developer", "test_team")
        except Exception:
            pass
        user = auth.get_user("audit_test_user")
        assert user is not None

        entries = [{
            "request_id": "req_test_001",
            "user_id": user.user_id,
            "username": user.username,
            "team": user.team,
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "input_tokens": 3200,
            "output_tokens": 1100,
            "tokens_saved": 200,
            "latency_ms": 1200.0,
            "cache_hit": False,
            "status_code": 200,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
        count = store.insert_batch(entries)
        assert count == 1

        # Query back
        rows = store.query_summary()
        assert len(rows) >= 1

    def test_query_user_usage(self, store) -> None:
        from headroom.auth.store import Neo4jAuthStore
        auth = Neo4jAuthStore()
        user = auth.get_user("audit_test_user")
        if user is None:
            pytest.skip("audit_test_user not found")
        rows = store.query_user_usage(user.user_id)
        assert isinstance(rows, list)

    def test_query_top_users(self, store) -> None:
        rows = store.query_top_users(limit=5)
        assert isinstance(rows, list)

    def test_purge_before(self, store) -> None:
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        count = store.purge_before(future)
        assert count >= 0
