"""Neo4j-backed persistence for request audit logs.

Reuses the same ``GraphDatabase.driver`` pattern as ``headroom/auth/store.py``.
All writes are idempotent batch operations via ``UNWIND $batch CREATE``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


class AuditStoreError(Exception):
    """Raised when a Neo4j audit operation fails."""


class AuditStore:
    """Read/write operations for ``(:RequestLog)`` nodes.

    Shares the same Neo4j connection parameters as ``Neo4jAuthStore``
    (``NEO4J_URI``, ``NEO4J_USER``, ``NEO4J_PASSWORD``).
    """

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        self._uri = uri or os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
        self._user = user or os.environ.get("NEO4J_USER", "neo4j")
        self._pwd = password or os.environ.get("NEO4J_PASSWORD", "")
        self._driver: Any = None

    def _get_driver(self) -> Any:
        if self._driver is not None:
            return self._driver
        try:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                self._uri, auth=(self._user, self._pwd)
            )
            return self._driver
        except ImportError:
            raise AuditStoreError(
                "Neo4j driver (neo4j package) is not installed."
            ) from None
        except Exception as exc:
            raise AuditStoreError(
                f"Failed to connect to Neo4j at {self._uri}."
            ) from exc

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def _run(self, cypher: str, params: dict | None = None) -> list[dict[str, Any]]:
        driver = self._get_driver()
        with driver.session() as session:
            result = session.run(cypher, params or {})
            records: list[dict[str, Any]] = []
            for record in result:
                row: dict[str, Any] = {}
                for key, value in dict(record).items():
                    row[key] = value
                records.append(row)
            return records

    # ------------------------------------------------------------------
    # batch write
    # ------------------------------------------------------------------

    def insert_batch(self, entries: list[dict[str, Any]]) -> int:
        """Insert a batch of ``(:RequestLog)`` nodes with ``:MADE_REQUEST`` relationships.

        Returns the number of nodes created.
        """
        if not entries:
            return 0
        self._run(
            """
            UNWIND $batch AS entry
            CREATE (r:RequestLog {
                request_id: entry.request_id,
                user_id: entry.user_id,
                username: entry.username,
                team: entry.team,
                provider: entry.provider,
                model: entry.model,
                input_tokens: entry.input_tokens,
                output_tokens: entry.output_tokens,
                tokens_saved: entry.tokens_saved,
                latency_ms: entry.latency_ms,
                cache_hit: entry.cache_hit,
                status_code: entry.status_code,
                timestamp: datetime(entry.timestamp)
            })
            WITH r, entry
            MATCH (u:User {user_id: entry.user_id})
            CREATE (u)-[:MADE_REQUEST]->(r)
            """,
            {"batch": entries},
        )
        return len(entries)

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------

    def query_user_usage(
        self,
        user_id: str,
        since: datetime | None = None,
        by_day: bool = False,
        by_model: bool = False,
    ) -> list[dict[str, Any]]:
        """Aggregate usage for a specific user."""
        if by_day:
            return self._run(
                """
                MATCH (r:RequestLog {user_id: $user_id})
                WHERE $since IS NULL OR r.timestamp >= $since
                RETURN date(r.timestamp) AS date,
                       COUNT(r) AS requests,
                       SUM(r.input_tokens) AS tokens_in,
                       SUM(r.output_tokens) AS tokens_out,
                       SUM(r.tokens_saved) AS tokens_saved
                ORDER BY date DESC
                """,
                {"user_id": user_id, "since": since.isoformat() if since else None},
            )
        if by_model:
            return self._run(
                """
                MATCH (r:RequestLog {user_id: $user_id})
                WHERE $since IS NULL OR r.timestamp >= $since
                RETURN r.model AS model,
                       COUNT(r) AS requests,
                       SUM(r.input_tokens) AS tokens_in,
                       SUM(r.output_tokens) AS tokens_out
                ORDER BY requests DESC
                """,
                {"user_id": user_id, "since": since.isoformat() if since else None},
            )
        return self._run(
            """
            MATCH (r:RequestLog {user_id: $user_id})
            WHERE $since IS NULL OR r.timestamp >= $since
            RETURN COUNT(r) AS requests,
                   SUM(r.input_tokens) AS tokens_in,
                   SUM(r.output_tokens) AS tokens_out,
                   SUM(r.tokens_saved) AS tokens_saved,
                   COUNT(DISTINCT r.model) AS model_count,
                   SUM(CASE WHEN r.cache_hit THEN 1 ELSE 0 END) AS cache_hits,
                   AVG(r.latency_ms) AS avg_latency_ms
            """,
            {"user_id": user_id, "since": since.isoformat() if since else None},
        )

    def query_team_usage(
        self,
        team: str,
        since: datetime | None = None,
        by_model: bool = False,
    ) -> list[dict[str, Any]]:
        """Aggregate usage for a team."""
        if by_model:
            return self._run(
                """
                MATCH (r:RequestLog {team: $team})
                WHERE $since IS NULL OR r.timestamp >= $since
                RETURN r.model AS model,
                       COUNT(r) AS requests,
                       SUM(r.input_tokens) AS tokens_in,
                       SUM(r.output_tokens) AS tokens_out,
                       COUNT(DISTINCT r.user_id) AS users
                ORDER BY requests DESC
                """,
                {"team": team, "since": since.isoformat() if since else None},
            )
        return self._run(
            """
            MATCH (r:RequestLog {team: $team})
            WHERE $since IS NULL OR r.timestamp >= $since
            RETURN COUNT(r) AS requests,
                   SUM(r.input_tokens) AS tokens_in,
                   SUM(r.output_tokens) AS tokens_out,
                   SUM(r.tokens_saved) AS tokens_saved,
                   COUNT(DISTINCT r.user_id) AS active_users,
                   COUNT(DISTINCT r.model) AS model_count
            """,
            {"team": team, "since": since.isoformat() if since else None},
        )

    def query_top_users(
        self,
        since: datetime | None = None,
        limit: int = 10,
        by_tokens: bool = True,
    ) -> list[dict[str, Any]]:
        """Rank users by token or request consumption."""
        order = "SUM(r.input_tokens) DESC" if by_tokens else "COUNT(r) DESC"
        cypher = (
            "MATCH (r:RequestLog) "
            "WHERE $since IS NULL OR r.timestamp >= $since "
            "RETURN r.user_id AS user_id, r.username AS username, "
            "r.team AS team, COUNT(r) AS requests, "
            "SUM(r.input_tokens) AS tokens_in "
            f"ORDER BY {order} "
            "LIMIT $limit"
        )
        return self._run(
            cypher,
            {
                "since": since.isoformat() if since else None,
                "limit": limit,
            },
        )

    def query_summary(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Aggregate proxy-wide totals."""
        return self._run(
            """
            MATCH (r:RequestLog)
            WHERE $since IS NULL OR r.timestamp >= $since
            RETURN COUNT(r) AS total_requests,
                   SUM(r.input_tokens) AS total_tokens_in,
                   SUM(r.output_tokens) AS total_tokens_out,
                   SUM(r.tokens_saved) AS total_tokens_saved,
                   COUNT(DISTINCT r.user_id) AS active_users,
                   COUNT(DISTINCT r.model) AS active_models,
                   SUM(CASE WHEN r.cache_hit THEN 1 ELSE 0 END) AS cache_hits
            """,
            {"since": since.isoformat() if since else None},
        )

    # ------------------------------------------------------------------
    # purge
    # ------------------------------------------------------------------

    def purge_before(self, before_date: datetime) -> int:
        """Delete ``(:RequestLog)`` nodes older than *before_date*.

        Returns the number of nodes deleted.
        """
        result = self._run(
            """
            MATCH (r:RequestLog)
            WHERE r.timestamp < $before
            DETACH DELETE r
            RETURN COUNT(r) AS deleted
            """,
            {"before": before_date.isoformat()},
        )
        return result[0]["deleted"] if result else 0
