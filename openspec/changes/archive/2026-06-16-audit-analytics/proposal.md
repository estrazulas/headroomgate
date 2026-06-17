## Why

With PRD 1 (user registration) and PRD 2 (authenticated requests), every request through the proxy has an associated `user_id`. But there is no way to answer operational questions like "who consumed the most tokens this week?", "which models is the backend team using?", or "what were developers asking about authentication?". This change closes the loop by recording, storing, and querying team usage history — giving admins and team leads visibility into proxy consumption through the same CLI they already use for auth management.

## What Changes

- **Async request logging to Neo4j** — every authenticated request creates a `(:RequestLog)` node with `user_id`, provider, model, token counts, latency, cache hit, and timestamp, linked via `(:User)-[:MADE_REQUEST]->(:RequestLog)`. Logging is asynchronous (in-memory buffer → batch flush) so it adds zero latency to the client response.
- **Semantic logging to Qdrant** — each request also generates a 384-dim embedding (fastembed BAAI/bge-small-en-v1.5) from a short textual summary, upserted to the `headroom_request_logs` collection. Best-effort: if Qdrant fails, Neo4j logging continues.
- **`headroom audit` CLI group** — structured queries (`audit user`, `audit team`, `audit top`, `audit summary`) and semantic search (`audit search "JWT authentication"`) with filters by team, user, model, and time range
- **Role-based access scope** — developers see only their own requests (`--self`), team leads see their team, admins see everything. Scope is read from the contextvar set by PRD 2.
- **Retention management** — `audit purge --before <date>` for manual cleanup of old log data
- **Disable flag** — `--no-audit-semantic` flag to skip Qdrant logging when CPU is constrained

## Capabilities

### New Capabilities

- `audit-logging`: Asynchronous `(:RequestLog)` persistence to Neo4j with in-memory buffer (flush every 50 entries or 5 seconds), zero added client latency, and relationship `(:User)-[:MADE_REQUEST]->(:RequestLog)`
- `audit-semantic`: Best-effort Qdrant logging with local fastembed embeddings (384 dims, from 200-word summary), collection `headroom_request_logs`, can be disabled via `--no-audit-semantic`
- `audit-cli`: `headroom audit` Click group with `audit user`, `audit team`, `audit top`, `audit summary`, `audit search`, `audit purge` subcommands, consistent with `headroom auth` CLI pattern
- `audit-access`: Role-based query scoping — developer sees self only, team lead sees their team, admin sees all — enforced via identity contextvar from PRD 2

### Modified Capabilities

None. PRD 3 adds new capabilities without changing the requirements of existing specs. The `user_id` contextvar from `auth-middleware` is consumed as-is through its public getter API.

## Non-Goals

- **Web dashboard** — no graphs or UI; CLI only (consistent with PRD 1/2)
- **Alerts** — no notifications for anomalous usage or blown budgets
- **CSV/JSON export** — deferred to Phase 2
- **Per-user budgets** — no spending limits ($)
- **Request classification** — no automatic categorization (work vs non-work)
- **PII detection** — no detection of sensitive data in prompts
- **Billing/invoicing** — no per-request cost tracking
- **Configurable retention TTL** — `audit purge` is manual; automatic TTL deferred to Phase 2

## Impact

- **New files**: `headroom/audit/` package (buffer, logger, Qdrant writer, CLI), `headroom/cli/audit.py` (Click group)
- **Existing code reused**: `headroom/auth/store.py` (Neo4jAuthStore for querying), `headroom_auth/identity.py` (contextvar getters), `headroom/proxy/server.py` (RequestOutcome hook point)
- **Dependencies**: `neo4j`, `fastembed`, `qdrant-client` — all already in `pyproject.toml` as optional dependencies; no new third-party packages
- **Integration point**: Hooks into the existing `RequestOutcome` emission in the proxy server, reading `user_id` from the contextvar set by PRD 2's auth middleware
- **Breaking changes**: None. When auth is disabled (no user_id), logging is a no-op
