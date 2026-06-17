## 1. Package Scaffold

- [x] 1.1 Create `headroom/audit/__init__.py` package with empty init
- [x] 1.2 Create `headroom/audit/models.py` with `RequestLog` dataclass containing: `request_id`, `user_id`, `username`, `team`, `provider`, `model`, `input_tokens`, `output_tokens`, `tokens_saved`, `latency_ms`, `cache_hit`, `status_code`, `timestamp`

## 2. Neo4j Audit Store (`audit-logging` spec)

- [x] 2.1 Add audit methods to `headroom/auth/store.py` (or create `headroom/audit/store.py`): `insert_request_log_batch(entries: list[dict])` using `UNWIND $batch CREATE (r:RequestLog)` with `(:User)-[:MADE_REQUEST]->(:RequestLog)` relationship
- [x] 2.2 Add query methods: `query_user_usage(user_id, since, by_day, by_model)`, `query_team_usage(team, since, by_model)`, `query_top_users(since, limit, by_tokens)`, `query_summary(since)`
- [x] 2.3 Add `purge_before(date)` method to delete RequestLog nodes and Qdrant points older than the given date

## 3. Async Buffer & Flush (`audit-logging` spec)

- [x] 3.1 Create `headroom/audit/buffer.py` with `AuditBuffer` class — an in-memory `collections.deque` with configurable `max_size` (default 5000), `batch_size` (default 50), and `flush_interval_seconds` (default 5)
- [x] 3.2 Implement `enqueue(entry: dict)` — appends to deque, drops oldest with warning if at capacity
- [x] 3.3 Implement `start()` — launches background `asyncio.Task` that flushes when batch_size reached or flush_interval elapsed; flush calls `insert_request_log_batch()` with a retry (1 retry after 1s)
- [x] 3.4 Implement `stop()` — flushes remaining entries and cancels background task

## 4. Qdrant Semantic Logger (`audit-semantic` spec)

- [x] 4.1 Create `headroom/audit/semantic.py` with `SemanticLogger` class — wraps Qdrant client for the `headroom_request_logs` collection
- [x] 4.2 Implement `ensure_collection()` — creates the Qdrant collection with `size: 384`, `distance: Cosine` if it doesn't exist (idempotent)
- [x] 4.3(request_id, user_id, username, team, provider, model, timestamp, summary)` — generates embedding via fastembed, upserts to Qdrant; catches and logs errors (best-effort)
- [x] 4.4es Qdrant with optional filters by user_id, team, model, and time range
- [x] 4.5 Implement `purge_before(date)` — deletes Qdrant points older than the given date

## 5. Request Logging Hook (`audit-logging` + `audit-semantic` specs)

- [x] 5.1 Create.py` with `AuditLogger` class that orchestrates both Neo4j and Qdrant logging from a `RequestOutcome`
- [x] 5.2 Implement` — extracts identity from contextvars (PRD 2), builds Neo4j entry dict, enqueues to AuditBuffer, and (if semantic enabled) generates summary text and calls SemanticLogger
- [x] 5.3 Implement(request_body, model, provider)` — extracts first 200 words of the last user message for embedding
- [x] 5.4 Add_SEMANTIC_ENABLED` env var (default `"true"`) and `--no-audit-semantic` flag support

## 6. Audit CLI (`audit-cli` spec)

- [x] 6.1 Create` with `audit` Click group and shared options: `--last` duration parser, auth key resolution
- [x] 6.2 Implement` subcommand with `--self`, `--by-day`, `--by-model`, `--last` flags, using Rich tables
- [x] 6.3 Implement` subcommand with `--by-model`, `--last` flags
- [x] 6.4 Implement` subcommand with `--by-tokens`/`--by-requests`, `--limit`, `--last` flags
- [x] 6.5 Implement` subcommand with `--last` flag
- [x] 6.6 Implement` subcommand with `--user`, `--team`, `--self`, `--model`, `--min-score`, `--last` flags
- [x] 6.7 Implement` subcommand with `--before`, `--yes` flags
- [x] 6.8 Register in `headroom/cli/main.py` via `_register_commands()`

## 7. Role-Based Access Scope (`audit-access` spec)

- [x] 7.1 Create` with `resolve_scope(user_id, username, role, team)` returning a `Scope` dataclass with `allowed_user_ids`, `allowed_teams`, and `is_admin` fields
- [x] 7.2 Implement(scope, target_user, target_team)` that raises `AuditAccessError` with clear messages: "You can only view your own requests. Use --self." or "You can only view your team's data."
- [x] 7.3 Integrate into all audit CLI subcommands and search queries

## 8. Proxy Integration

- [x] 8.1 Hook.log()` into the proxy server's request completion path (where `RequestOutcome` is emitted), guarded by `if get_current_user() is not None`
- [x] 8.2 Initialize.stop()` on proxy shutdown
- [x] 8.3 Ensure.ensure_collection()` is called at startup when semantic logging is enabled

## 9. Tests

- [x] 9.1 buffer tests
- [x] 9.2 store tests
- [x] 9.3 semantic tests
- [x] 9.4 CLI tests
- [x] 9.5 access tests

## 10. Verification

- [x] 10.1 no-op when auth disabled
- [x] 10.2 CLI help output
- [x] 10.3 E2E flow (deploy-time)
