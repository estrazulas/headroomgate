## Context

PRD 1 registered users and API keys. PRD 2 authenticates every request and makes `user_id` available via contextvars. Now every request has an owner — but that identity is ephemeral: it exists for the duration of the request and is then discarded. There is no persisted record of who used the proxy, which models they called, how many tokens they consumed, or what they asked about.

This design adds a dual logging layer — Neo4j for structured analytics queries and Qdrant for semantic search — that records every authenticated request asynchronously so logging never blocks the client response. A new `headroom audit` CLI lets admins and team leads query usage.

## Goals / Non-Goals

**Goals:**
- Record every authenticated request to Neo4j as a `(:RequestLog)` node with zero added client latency (async buffer → batch flush)
- Index a short textual summary of each request in Qdrant for semantic search, best-effort (Neo4j remains source of truth)
- Provide a `headroom audit` CLI with structured queries (user, team, top, summary) and semantic search
- Enforce role-based access scope: developer → self, team lead → team, admin → all
- Enable manual cleanup via `audit purge --before <date>`

**Non-Goals:**
- Web dashboard, alerts, CSV export, budgets, PII detection, per-request cost tracking

## Decisions

### Decision 1: In-memory async buffer with batch flush to Neo4j

Requests are pushed onto a `collections.deque` in-memory buffer. A background `asyncio.Task` flushes when the buffer reaches 50 entries OR 5 seconds have elapsed since the last flush. Flush uses `UNWIND $batch CREATE (r:RequestLog {...})` for a single round-trip to Neo4j.

**Alternatives considered:**
- **Synchronous write per request**: Adds ~5ms Neo4j latency to every client response. Rejected — violates the zero-added-latency goal.
- **External message queue (Redis/Kafka)**: More durable but adds operational complexity. Rejected for MVP — in-memory buffer is acceptable.
- **SQLite write-ahead log**: Durable and zero-dependency, but adds another data store to maintain. Deferred to Phase 2.

**Rationale:** In-memory batching is the simplest approach that meets the zero-latency goal. The trade-off is that up to 50 entries (or 5 seconds of data) may be lost on crash — acceptable for MVP per risk analysis.

### Decision 2: Qdrant best-effort (not transactional with Neo4j)

Each request generates an embedding from a 200-word textual summary. The embedding is upserted to the `headroom_request_logs` Qdrant collection. If Qdrant is unreachable, the error is logged and Neo4j logging continues unaffected.

**Alternatives considered:**
- **Transactional dual-write**: Complex, adds latency, and violates the "Qdrant is optional" principle. Rejected.
- **Neo4j-only semantic search** (via vector index): Neo4j 5.x has vector support, but Qdrant is purpose-built for ANN search and already running. Rejected.

**Rationale:** Qdrant is already provisioned and running for memory. Adding a collection has near-zero marginal cost. Best-effort semantics keep the architecture simple — Neo4j is always the source of truth.

### Decision 3: fastembed BAAI/bge-small-en-v1.5 for embeddings

Uses the same model already in `pyproject.toml` for relevance scoring. Embedding runs locally via ONNX — no API call, zero dollar cost per request. Only the first 200 words of the request are embedded (summary), not the full prompt.

**Alternatives considered:**
- **OpenAI/text-embedding-3-small**: Better quality but adds API latency + cost per request. Rejected.
- **Full prompt embedding**: More accurate but ~5x CPU cost. Rejected — summary is sufficient for semantic search.

**Rationale:** Reuse the existing fastembed dependency. The 200-word summary keeps CPU cost low while providing enough signal for semantic search ("what did the team ask about authentication?").

### Decision 4: `headroom audit` CLI group, consistent with `headroom auth`

Follows the same Click patterns as PRD 1: a top-level `audit` command group with subcommands registered via `main.py::_register_commands()`. Output uses Rich tables (same as `headroom auth list-users`).

Subcommands:
- `audit user <username>` — usage by user, with `--by-day`, `--by-model`, `--last` flags
- `audit team <name>` — usage by team, with `--by-model`, `--last` flags
- `audit top` — top users, with `--by-tokens`, `--limit`, `--last` flags
- `audit summary` — aggregate totals, with `--last` flag
- `audit search <query>` — semantic search via Qdrant, with `--user`, `--team`, `--min-score`, `--last` flags
- `audit purge` — manual cleanup, with `--before` flag

**Alternatives considered:**
- **REST API (`/admin/audit/`)**: Enables external tool integration but adds web surface area. Deferred.
- **Flat commands (`headroom audit-user`)**: Conflicts with the established `headroom auth <subcommand>` pattern.

**Rationale:** Consistent with PRD 1 CLI. Role-based scoping is automatic — `--self` flag for developers, team-scoped for team leads.

### Decision 5: Role-based access scope enforced at query time

The CLI reads `user_id` and `role` from contextvars (set by PRD 2 middleware) or from the CLI's own identity resolution. Query functions accept a `scope` parameter:
- `role == "admin"` → no filter, sees everything
- `role == "team_lead"` → filtered by `team` property on RequestLog
- `role == "developer"` → filtered by `user_id`, or `--self` required

**Alternatives considered:**
- **Neo4j row-level security**: Not natively supported in Neo4j Community. Rejected.
- **Separate database per team**: Overkill for MVP, operational nightmare. Rejected.

**Rationale:** Application-level enforcement is simple, testable, and consistent with the existing role model.

### Decision 6: `(:RequestLog)` schema with denormalized fields

Each `:RequestLog` node stores `username` and `team` denormalized (copied from User at request time) to avoid JOINs in common queries like "top users by tokens". The `(:User)-[:MADE_REQUEST]->(:RequestLog)` relationship enables graph traversal when needed.

**Alternatives considered:**
- **Normalized (only user_id)**: Cleaner but requires a JOIN for every query showing username. Rejected — audit queries are read-heavy; denormalization is the standard optimization.
- **Separate `:Request` and `:TokenUsage` nodes**: Over-normalized for the query patterns. Rejected.

**Rationale:** Pragmatic denormalization for the most common audit queries.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| **Data loss on crash (≤50 entries or 5s)** | Acceptable for MVP. Phase 2 adds write-ahead log (SQLite). |
| **Buffer overflow during traffic spike** | Hard cap at 5000 entries; if exceeded, drop oldest with warning log |
| **Unlimited Neo4j growth** | `audit purge` command for manual cleanup; Phase 2 adds configurable TTL |
| **CPU cost of local embedding** | 200-word summary only; can be disabled with `--no-audit-semantic` |
| **Neo4j vs Qdrant divergence** | Qdrant is best-effort; Neo4j is source of truth. Structured queries always work |
| **Slow queries for large datasets** | Neo4j indexes on `timestamp`, `user_id`, `team`; pagination in CLI output |
| **Embedding model not installed** | Graceful degradation: structured queries work without fastembed |

## Open Questions

- Should the textual summary include the system prompt or just the user message? → **Decision: first 200 words of the last user message only**
- Should `audit export --format csv` be MVP or Phase 2? → **Phase 2 (per PRD)**
- Should the buffer be per-worker or shared? → **Per-worker for MVP; shared buffer (Redis) in Phase 2**
- Should there be an `/admin/audit` REST endpoint? → **Deferred**
