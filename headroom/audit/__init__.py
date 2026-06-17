"""Usage audit and analytics — async request logging to Neo4j + Qdrant.

Records every authenticated proxy request for structured queries (Neo4j
``:RequestLog`` nodes) and semantic search (Qdrant embeddings). Logging
is asynchronous via an in-memory buffer so it adds zero client latency.
"""

from __future__ import annotations
