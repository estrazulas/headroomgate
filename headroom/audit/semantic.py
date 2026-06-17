"""Qdrant semantic logging for audit requests — best-effort.

Each authenticated request generates a short textual summary which is
embedded via fastembed (BAAI/bge-small-en-v1.5, 384 dims, local ONNX)
and upserted to the ``headroom_request_logs`` Qdrant collection for
semantic search. If Qdrant or fastembed are unavailable, logging
degrades gracefully — Neo4j logging is never affected.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any

log = logging.getLogger("headroom.audit.semantic")

COLLECTION_NAME = "headroom_request_logs"
VECTOR_SIZE = 384


class SemanticLogger:
    """Qdrant semantic log writer — best-effort, local-only embeddings.

    Parameters:
        qdrant_url: Qdrant server URL (default from ``QDRANT_URL`` env).
        enabled: When ``False``, all methods are no-ops.
    """

    def __init__(
        self,
        qdrant_url: str | None = None,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._url = qdrant_url or os.environ.get("QDRANT_URL", "http://localhost:6333")
        self._client: Any = None
        self._embedder: Any = None
        self._embedder_available = False

        if self._enabled:
            self._init_embedder()
            self._init_client()

    # ------------------------------------------------------------------
    # init
    # ------------------------------------------------------------------

    def _init_embedder(self) -> None:
        try:
            from fastembed import TextEmbedding

            self._embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
            self._embedder_available = True
            log.info("audit-semantic: fastembed loaded (BAAI/bge-small-en-v1.5)")
        except Exception as exc:
            log.info(
                "audit-semantic: fastembed not available, Qdrant logging disabled: %s",
                exc,
            )
            self._embedder_available = False

    def _init_client(self) -> None:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._client = QdrantClient(url=self._url)
        except Exception as exc:
            log.warning("audit-semantic: Qdrant client init failed: %s", exc)
            self._client = None

    @property
    def is_available(self) -> bool:
        return self._enabled and self._embedder_available and self._client is not None

    # ------------------------------------------------------------------
    # collection
    # ------------------------------------------------------------------

    def ensure_collection(self) -> None:
        """Create the Qdrant collection if it doesn't exist (idempotent)."""
        if not self.is_available:
            return
        try:
            from qdrant_client.models import Distance, VectorParams

            collections = self._client.get_collections()
            names = [c.name for c in collections.collections]
            if COLLECTION_NAME not in names:
                self._client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
                log.info("audit-semantic: created Qdrant collection '%s'", COLLECTION_NAME)
        except Exception as exc:
            log.warning("audit-semantic: ensure_collection failed: %s", exc)

    # ------------------------------------------------------------------
    # log
    # ------------------------------------------------------------------

    def log_request(
        self,
        request_id: str,
        user_id: str,
        username: str,
        team: str,
        provider: str,
        model: str,
        timestamp: datetime,
        summary: str,
    ) -> None:
        """Embed *summary* and upsert to Qdrant. No-op if unavailable."""
        if not self.is_available:
            return
        if not summary.strip():
            return
        try:
            embeddings = list(self._embedder.embed([summary]))
            if not embeddings:
                return
            vector = embeddings[0].tolist()

            from qdrant_client.models import PointStruct

            point = PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload={
                    "request_id": request_id,
                    "user_id": user_id,
                    "username": username,
                    "team": team,
                    "provider": provider,
                    "model": model,
                    "timestamp": timestamp.isoformat(),
                    "summary": summary[:500],
                },
            )
            self._client.upsert(
                collection_name=COLLECTION_NAME,
                points=[point],
            )
        except Exception as exc:
            log.warning("audit-semantic: log_request failed for %s: %s", request_id, exc)

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    def search(
        self,
        query_text: str,
        user_id: str | None = None,
        team: str | None = None,
        model: str | None = None,
        since: datetime | None = None,
        limit: int = 10,
        min_score: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Semantic search over logged requests. Returns empty list if unavailable."""
        if not self.is_available:
            return []
        try:
            embeddings = list(self._embedder.embed([query_text]))
            if not embeddings:
                return []
            vector = embeddings[0].tolist()

            from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

            must_conditions = []
            if user_id:
                must_conditions.append(
                    FieldCondition(key="user_id", match=MatchValue(value=user_id))
                )
            if team:
                must_conditions.append(
                    FieldCondition(key="team", match=MatchValue(value=team))
                )
            if model:
                must_conditions.append(
                    FieldCondition(key="model", match=MatchValue(value=model))
                )
            if since:
                must_conditions.append(
                    FieldCondition(
                        key="timestamp",
                        range=Range(gte=since.isoformat()),
                    )
                )

            query_filter = Filter(must=must_conditions) if must_conditions else None

            results = self._client.search(
                collection_name=COLLECTION_NAME,
                query_vector=vector,
                query_filter=query_filter,
                limit=limit,
                score_threshold=min_score,
            )

            return [
                {
                    "score": r.score,
                    "request_id": r.payload.get("request_id"),
                    "username": r.payload.get("username"),
                    "team": r.payload.get("team"),
                    "provider": r.payload.get("provider"),
                    "model": r.payload.get("model"),
                    "timestamp": r.payload.get("timestamp"),
                    "summary": r.payload.get("summary"),
                }
                for r in results
                if r.payload
            ]
        except Exception as exc:
            log.warning("audit-semantic: search failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # purge
    # ------------------------------------------------------------------

    def purge_before(self, before_date: datetime) -> int:
        """Delete Qdrant points older than *before_date*. Returns count deleted."""
        if not self.is_available:
            return 0
        try:
            from qdrant_client.models import Filter, FieldCondition, Range

            # Qdrant doesn't support DELETE with filters in all versions.
            # We use scroll + delete by id.
            records = self._client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="timestamp",
                            range=Range(lt=before_date.isoformat()),
                        )
                    ]
                ),
                limit=1000,
            )
            point_ids = [p.id for p in records[0] if p.id]
            if point_ids:
                self._client.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=point_ids,
                )
            return len(point_ids)
        except Exception as exc:
            log.warning("audit-semantic: purge_before failed: %s", exc)
            return 0
