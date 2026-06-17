"""Tests for SemanticLogger (PRD 3 tasks 4.1-4.5).

Tests that don't need Qdrant/fastembed are always run.
Qdrant-dependent tests are skipped when unavailable.
"""

import os
from datetime import datetime, timezone

import pytest


def _qdrant_available() -> bool:
    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=url, timeout=2)
        client.get_collections()
        return True
    except Exception:
        return False


class TestSemanticLoggerDisabled:
    """Tests that work without Qdrant."""

    def test_disabled_logger_is_not_available(self) -> None:
        from headroom.audit.semantic import SemanticLogger
        logger = SemanticLogger(enabled=False)
        assert logger.is_available is False

    def test_disabled_log_request_is_noop(self) -> None:
        from headroom.audit.semantic import SemanticLogger
        logger = SemanticLogger(enabled=False)
        # Should not raise
        logger.log_request(
            request_id="r1", user_id="u1", username="alice", team="t",
            provider="anthropic", model="claude", timestamp=datetime.now(timezone.utc),
            summary="test summary",
        )

    def test_disabled_search_returns_empty(self) -> None:
        from headroom.audit.semantic import SemanticLogger
        logger = SemanticLogger(enabled=False)
        results = logger.search("test query")
        assert results == []

    def test_disabled_purge_returns_zero(self) -> None:
        from headroom.audit.semantic import SemanticLogger
        logger = SemanticLogger(enabled=False)
        count = logger.purge_before(datetime(2099, 1, 1, tzinfo=timezone.utc))
        assert count == 0

    def test_disabled_ensure_collection_is_noop(self) -> None:
        from headroom.audit.semantic import SemanticLogger
        logger = SemanticLogger(enabled=False)
        # Should not raise
        logger.ensure_collection()


@pytest.mark.skipif(not _qdrant_available(), reason="Qdrant not available")
class TestSemanticLoggerLive:
    @pytest.fixture
    def logger(self):
        from headroom.audit.semantic import SemanticLogger
        return SemanticLogger(enabled=True)

    def test_ensure_collection_idempotent(self, logger) -> None:
        logger.ensure_collection()
        logger.ensure_collection()  # second call should not fail

    def test_log_and_search(self, logger) -> None:
        if not logger.is_available:
            pytest.skip("fastembed not available")
        now = datetime.now(timezone.utc)
        logger.log_request(
            request_id="r_test", user_id="u_test", username="testuser",
            team="qa", provider="anthropic", model="claude-sonnet-4-6",
            timestamp=now, summary="debugging a memory leak in Python async workers",
        )
        results = logger.search("memory leak", min_score=0.5, limit=5)
        assert isinstance(results, list)
