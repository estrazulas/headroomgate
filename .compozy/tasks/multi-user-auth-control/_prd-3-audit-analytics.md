# PRD 3: Usage Audit & Analytics

## Overview

With PRD 1 (registered users) and PRD 2 (authenticated requests), every request passing through the proxy has an associated `user_id`. This PRD closes the loop: **recording, storing, and querying** the team's usage history.

Two query layers:
- **Neo4j** (`:RequestLog`): structured queries — "how many tokens did the team consume?", "who uses which model?", "top 5 users by spend"
- **Qdrant** (`headroom_request_logs`): semantic search — "what did the team ask about authentication?", "find requests similar to this error"

Admin and team leads use the `headroom audit` CLI to query. Developers can view their own data.

## Goals

- **Complete traceability**: Every authenticated request generates a record with user_id, provider, model, tokens, latency, and timestamp
- **Zero added latency**: Logging is asynchronous (buffer → background flush)
- **Fast queries**: "Weekly team usage" query returns in < 1 second for teams of up to 50 developers
- **Privacy**: Developer only sees their own requests; team lead sees their team; admin sees everything
- **Semantic search**: Find requests by content similarity, not just exact filters

## User Stories

### Persona 1: Admin (proxy management)

- As an admin, I want to see **usage by user** (`headroom audit user joao --last 7d`) to know who is consuming the most
- As an admin, I want to see **usage by team** (`headroom audit team backend --last 30d`) to compare teams
- As an admin, I want to see **usage by model** (`headroom audit top --by-model`) to identify which models are most used
- As an admin, I want to see **top users by tokens** (`headroom audit top --by-tokens --last 7d`) to identify outliers
- As an admin, I want to **search semantically** (`headroom audit search "authentication error"`) to find requests on a specific topic
- As an admin, I want to see **proxy totals** (`headroom audit summary`) — total requests, tokens, active models

### Persona 2: Team Lead

- As team lead of backend, I want to see **my team's usage** — same commands, but scope restricted to the team
- As team lead, I want to **identify who is struggling** (many error requests? many similar questions?)
- As team lead, I **do not want** to see data from other teams

### Persona 3: Developer

- As a developer, I want to see **my own usage** (`headroom audit user --self --last 7d`) to know how much I consumed
- As a developer, I want to see **my most used models** to understand my habits
- As a developer, I **do not want** to see data from other developers (privacy)

## Core Features

### F1 — Asynchronous Request Logging

Every authenticated request generates a `(:RequestLog)` node in Neo4j. Logging is **asynchronous** — it does not block the response to the client:

```
Request completed
  → RequestOutcome emitted (already exists, with user_id from PRD 2)
  → Queued in buffer (deque, in-memory)
  → Background: flush when buffer reaches 50 entries OR 5 seconds since last flush
  → Batch write to Neo4j: UNWIND $batch CREATE (r:RequestLog {...})
```

Recorded data:
- `request_id`, `user_id`, `username` (denormalized), `provider`, `model`
- `input_tokens`, `output_tokens`, `tokens_saved`, `latency_ms`
- `cache_hit: bool`, `status_code: int`, `timestamp: datetime`
- Relationship `(:User)-[:MADE_REQUEST]->(:RequestLog)`

### F2 — Semantic Logging in Qdrant

In addition to Neo4j, each request generates an embedding in Qdrant for semantic search:

```
Request completed
  → Extract textual summary: first 200 words of the request + model + timestamp
  → Generate embedding (fastembed BAAI/bge-small-en-v1.5, 384 dims, local)
  → Upsert to Qdrant (collection: headroom_request_logs)
  → Payload: { request_id, user_id, username, team, provider, timestamp, summary }
  → Best-effort: if Qdrant fails, Neo4j logging continues to work
```

The embedding is generated **from the summary only**, not the full request — to keep the local CPU cost low.

### F3 — Structured Query CLI

```
$ headroom audit user joao --last 7d
Period: 2026-06-09 → 2026-06-16
Requests: 342
Tokens: 1.2M in / 380k out
Savings: 45k tokens (3.75%)
Models: claude-sonnet-4-6 (274), claude-opus-4 (68)
Cache hits: 23 (6.7%)
Avg latency: 1.2s

$ headroom audit user joao --last 7d --by-day
date        requests   tokens_in   tokens_out   top_model
2026-06-16  48         168k        52k          claude-sonnet-4-6
2026-06-15  52         182k        58k          claude-sonnet-4-6
...

$ headroom audit team backend --last 30d --by-model
model               requests   tokens_in   tokens_out   users
claude-sonnet-4-6    8,421     24.5M       7.2M         3
claude-opus-4        1,204     5.8M        2.1M         2
gpt-5                3,102     9.1M        3.4M         4

$ headroom audit top --by-tokens --last 7d --limit 10
rank  username    team        requests   tokens_in
1     joao        backend     342        1.2M
2     maria       backend     215        890k
3     pedro       frontend    128        450k
...

$ headroom audit summary --last 24h
Total requests: 1,847
Total tokens: 5.2M in / 1.8M out
Active users: 8
Active models: claude-sonnet-4-6, claude-opus-4, gpt-5, gemini-2.5-pro
Cache hit rate: 12.3%
Avg savings: 4.1%
```

### F4 — Semantic Search CLI

```
$ headroom audit search "JWT authentication" --team backend --last 30d
3 requests found (similarity > 0.7):
1. [2026-06-15 14:32] joao — score: 0.94
   "how to implement JWT refresh token in FastAPI..."
   model: claude-sonnet-4-6 | tokens: 3.2k in / 1.1k out

2. [2026-06-10 09:15] maria — score: 0.87
   "debug: JWT token expiring before configured expiry..."
   model: claude-opus-4 | tokens: 5.1k in / 2.3k out

3. [2026-06-02 16:45] joao — score: 0.72
   "which JWT library to use in the FastAPI project..."
   model: claude-sonnet-4-6 | tokens: 1.8k in / 0.9k out

$ headroom audit search "memory leak python" --self --last 90d
1 request found:
1. [2026-05-20 11:03] joao — score: 0.88
   "debugging memory leak in async Python workers..."
   model: claude-opus-4 | tokens: 8.2k in / 3.1k out
```

Supported filters: `--team`, `--user`, `--self`, `--model`, `--last`, `--min-score`.

### F5 — Role-Based Access Scope

```
Developer:    sees only their own requests
Team Lead:    sees requests from their team (cannot see other teams)
Admin:        sees all requests
```

The role is read from the contextvar (PRD 2) and the scope is automatically applied in queries. If a developer attempts `headroom audit user maria --last 7d`, the system returns: `Error: you can only view your own requests. Use --self.`

### F6 — Retention and Cleanup

By default, **infinite retention** (ADR-003). When needed, the admin can purge:

```
$ headroom audit purge --before 2025-01-01
Confirm removal of 12,847 requests before 2025-01-01? [y/N] y
Removed: 12,847 requests from Neo4j + Qdrant.
```

### F7 — Disable Semantic Search

If the proxy's CPU is overloaded, semantic search can be disabled:

```
$ headroom proxy --no-audit-semantic ...
# Neo4j logging only, no embeddings in Qdrant
```

## User Experience

### Primary Flow: Admin Reviews Weekly Usage

```
$ headroom audit summary --last 7d
Total requests: 12,847 | Tokens: 35.2M in / 11.8M out
Active users: 8 | Active models: 4
Cache hit rate: 12.3% | Avg savings: 4.1%

$ headroom audit top --by-tokens --last 7d
rank  username    requests   tokens_in   team
1     joao        2,841      8.2M        backend
2     maria       2,104      6.1M        backend
3     pedro       1,893      5.4M        frontend

# João is consuming a lot — admin investigates
$ headroom audit user joao --last 7d --by-model
model               requests   tokens_in
claude-opus-4        1,894     5.8M        ← expensive model
claude-sonnet-4-6      947     2.4M

# Admin searches what João is asking that requires Opus
$ headroom audit search "architecture design system" --user joao --last 7d
5 requests found — all about system design (justifies Opus usage)
```

### Developer Flow: View My Usage

```
$ headroom audit user --self --last 7d
Your requests: 342
Tokens: 1.2M in / 380k out
Models: claude-sonnet-4-6 (274), claude-opus-4 (68)
```

## High-Level Technical Constraints

- **Neo4j**: `(:RequestLog)` nodes + relationship `(:User)-[:MADE_REQUEST]->(:RequestLog)` (ADR-003)
- **Qdrant**: collection `headroom_request_logs`, 384 dims, Cosine distance (ADR-003)
- **Embeddings**: fastembed BAAI/bge-small-en-v1.5 (local model, same used for relevance scoring — zero added cost)
- **Buffer**: In-memory deque, flush every 50 entries or 5 seconds
- **CLI**: Click, consistent with `headroom auth` (PRD 1)
- **Non-regression**: If auth is disabled, logging is a no-op

## Non-Goals (Out of Scope)

- **Web dashboard** — no graphs or UI (ADR-003)
- **Alerts** — no notifications for anomalous usage or blown budgets
- **Export** — no CSV/JSON export (MVP)
- **Budgets** — no per-user spending limits ($)
- **Request classification** — no automatic categorization (work vs non-work)
- **PII detection** — no detection of sensitive data in requests
- **Billing/invoicing** — no per-request cost tracking

## Phased Rollout Plan

### MVP (Phase 1) — PRD 3

- Asynchronous Neo4j logging (`:RequestLog`)
- Best-effort Qdrant logging (`headroom_request_logs`)
- CLI: `audit user`, `audit team`, `audit top`, `audit summary`
- CLI: `audit search` (semantic search)
- Role-based access scope (developer/team_lead/admin)
- Command `audit purge` for manual cleanup

### Phase 2 (post-MVP)

- CSV/JSON export (`headroom audit export --format csv`)
- Configurable retention (`--audit-retention-days`)
- Anomalous usage alerts (dev spent 3x more than average)

### Phase 3 (long term)

- Web dashboard with graphs
- Budget tracking ($ per request)
- Automatic request classification (work vs non-work)
- Integration with observability tools (Grafana, Datadog)

## Success Metrics

| Metric | Target |
|--------|--------|
| Added latency per request (logging) | 0ms (async — does not block) |
| Flush time (50 entry batch) | < 100ms |
| Query `audit user --last 7d` | < 500ms |
| Query `audit search` (Qdrant) | < 300ms |
| Neo4j vs Qdrant divergence | < 0.1% (best-effort) |
| Embedding cost per request | $0 (local fastembed model, no API call) |

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| **Unlimited database growth** | `audit purge` command for manual cleanup; Phase 2 adds configurable TTL |
| **CPU cost of local embedding** | Only short summary (200 words); can be disabled with `--no-audit-semantic` |
| **Buffer overflow during traffic spikes** | Buffer has a maximum limit (5k entries); if exceeded, drop oldest entries with warning |
| **Data loss on crash** | In-memory buffer — up to 50 entries or 5 seconds may be lost in a crash. Mitigation: acceptable for MVP; Phase 2 adds write-ahead log |
| **Slow query for large teams (100+ devs)** | Neo4j indexes on timestamp, user_id, team; pagination in results |

## Architecture Decision Records

- [ADR-001: Pure Admin CLI](adrs/adr-001.md) — CLI as the sole administration interface
- [ADR-002: Auth middleware as plugin](adrs/adr-002.md) — Auth middleware as a separate extension
- [ADR-003: Dual Audit — Neo4j + Qdrant](adrs/adr-003.md) — Dual query layer (structured + semantic)

## Open Questions

- Should the textual summary for embedding include the full prompt (with system prompt) or just the user message?
- Should `headroom audit export --format csv` be in the MVP or only Phase 2?
- Should the logging buffer be per-worker (if multiple workers) or shared?
- Should there be an `/admin/audit` endpoint (REST API) for integration with external tools?
