# PRD 2: Authenticated Proxy Gateway

## Overview

Today the headroom proxy accepts any incoming request — without identity verification, without access control. PRD 1 addressed user registration and API keys. This PRD implements the **authentication runtime** — the middleware that intercepts every request, validates the proxy key, resolves the user, injects the provider key, and applies per-user rate limits.

With this PRD, the proxy transitions from an anonymous intermediary to a **gateway with verified identity**.

## Goals

- **Transparent authentication**: The developer uses the proxy exactly as today — the only difference is that instead of the provider key, they use the proxy key (`hr_...`)
- **Imperceptible latency**: Key validation + identity resolution adds < 5ms at p95
- **Resilience**: If Neo4j goes down, the proxy continues to operate with local cache (TTL 10s)
- **Isolation**: When auth is disabled (`HEADROOM_AUTH_ENABLED=false`), the proxy is identical to the original
- **Individual rate limits**: Each user has their own RPM/TPM bucket, inherited from their role

## User Stories

### Persona 1: Developer (daily proxy user)

- As a developer, I want to **use my LLM client normally** (Claude Code, Cursor, etc.) by pointing `HEADROOM_BASE_URL` at the proxy and using my `hr_...` key
- As a developer, I want to receive a **clear error** (401) if my key is invalid or expired, so I know I need to renew
- As a developer, I want to receive a **clear error** (403) if my user was deactivated, so I can talk to my team lead
- As a developer, I want to see **rate limit headers** in responses (`X-RateLimit-Remaining`) to know how many requests I can still make
- As a developer, I want to receive **429 with Retry-After** when I hit my limit, to know when to retry
- As a developer, I **don't want** to worry about which provider is behind the scenes — the proxy resolves it automatically

### Persona 2: Admin (proxy operator)

- As an admin, I want to **enable/disable auth** with a flag (`--auth` / `HEADROOM_AUTH_ENABLED`) without recompiling or redeploying
- As an admin, I want the proxy to **reject requests without an auth header** (401) when auth is active
- As an admin, I want **health checks** (`/livez`, `/readyz`, `/health`, `/metrics`) to work without authentication
- As an admin, I want to see in **logs** which user made each request (`user_id` field)
- As an admin, I want the **rate limit** for each role to be configurable (default: developer = 60 RPM / 100k TPM)

### Persona 3: Developer without a key (rejected user)

- As a user without a valid key, I want a **clear 401 error** with an informative message (not a stack trace)
- As a user with an expired key, I want a **401 with "key expired" message** so I know it's not a configuration error

## Core Features

### F1 — Per-Request Authentication

The middleware intercepts every request (except health checks) and validates the proxy key:

```
Request: Authorization: Bearer hr_a7f3b9c2d1e5...
  → SHA-256("hr_a7f3b9c2d1e5...")
  → Cache hit? Use cached result (TTL 10s)
  → Cache miss? Query Neo4j:
      MATCH (k:ApiKey {key_hash: $hash, is_active: true})
      WHERE k.expires_at IS NULL OR k.expires_at > datetime()
      MATCH (k)-[:OWNS_KEY]->(u:User {is_active: true})
      MATCH (u)-[:HAS_ROLE]->(r:Role)
      RETURN u.user_id, u.username, u.role, u.team, r.provider_keys, r.default_rpm, r.default_tpm
  → Cache miss + Neo4j unavailable? Use stale cache with warning log
  → Key not found or expired? 401
  → User inactive? 403
  → Success: user_id + role + provider_keys stored in contextvars
```

### F2 — Provider Key Injection

With the user resolved, the middleware determines which provider to use and injects the key:

```
Request path: /v1/messages → provider = "anthropic"
  → Decrypt provider_keys["anthropic"] with HEADROOM_ENCRYPTION_KEY
  → Replace header Authorization: Bearer hr_xxx with Bearer sk-ant-api03-xxx
  → Request proceeds to upstream with the real provider key

Request path: /v1/chat/completions → provider = "openai"
  → Decrypt provider_keys["openai"]
  → Replace header Authorization: Bearer sk-proj-xxx
  → Request proceeds to upstream
```

Automatic mapping (same behavior as today):

| Path | Provider |
|------|----------|
| `/v1/messages` | anthropic |
| `/v1/chat/completions` | openai |
| `/v1beta/models/*` | gemini |
| `/v1internal/*` | cloudcode |
| other paths | detected by header (x-api-key, x-goog-api-key, etc.) |

### F3 — Per-User Rate Limiting

Individual rate limit, inherited from the role. Example:

```
Role "developer": 60 RPM, 100k TPM
  → João (developer): individual bucket, 60 RPM
  → Maria (developer): individual bucket, 60 RPM
  → João's burst does not affect Maria

Role "intern": 20 RPM, 30k TPM
  → Pedro (intern): lower limit
```

Response headers:
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 42
X-RateLimit-Reset: 1700000000
```

When the limit is reached:
```
HTTP 429 Too Many Requests
Retry-After: 15
{"error": "rate limit exceeded", "retry_after_seconds": 15}
```

### F4 — Validation Cache

In-memory local cache to avoid querying Neo4j on every request:

- **TTL**: 10 seconds (configurable: `HEADROOM_AUTH_CACHE_TTL`)
- **Cache key**: SHA-256 of the proxy key (already the hash, so O(1) lookup)
- **Entry**: user_id, username, role, provider_keys (decrypted), RPM/TPM limits
- **Invalidation**: Cache naturally expires after TTL — a revoked key stops being accepted within 10 seconds max. Signal file or endpoint will be considered in Phase 2 if needed.
- **Fallback**: If Neo4j is down and the entry expired, use stale entry + warning log

### F5 — Health Check Bypass

Endpoints that NEVER require authentication:
- `GET /livez`
- `GET /readyz`
- `GET /health`
- `GET /metrics`

These endpoints use system authentication (prometheus, k8s probes) and have no `Authorization` header.

### F6 — Propagated Identity (contextvars)

After authentication, `user_id` and metadata are stored in `contextvars` for downstream consumption:

```python
# Accessible throughout the request pipeline:
current_user_id = get_current_user()   # "joao"
current_username = get_current_username()  # "joao"
current_role = get_current_role()      # "developer"
current_team = get_current_team()      # "backend"
```

This powers:
- **PRD 3**: Audit trail (RequestLog in Neo4j with user_id)
- **PRD 3**: Qdrant (embedding with user_id)
- **Metrics**: Prometheus with `user` label
- **Logs**: `user_id` field in PERF logs

## User Experience

### Primary Flow: Developer Makes an Authenticated Request

```
1. João configures Claude Code:
   HEADROOM_BASE_URL=http://proxy:8787
   API key = hr_a7f3b9c2d1e5...  (received from admin)

2. João uses Claude Code normally:
   "claude, explain this code"

3. What happens:
   Claude Code → POST /v1/messages
   Authorization: Bearer hr_a7f3b9c2d1e5...

   proxy:
     ✓ Validates key (cache hit, 0.2ms)
     ✓ Resolves: João, developer, team backend
     ✓ Rate limit: 42/60 remaining
     ✓ Provider: anthropic
     ✓ Injects real key: Bearer sk-ant-api03-xxx
     → Upstream Anthropic

   response:
     X-RateLimit-Remaining: 41
     ← Claude's response
```

### Error Flow: Expired Key

```
João makes request → 401 Unauthorized
{"error": "api_key_expired", "message": "Your key has expired. Contact your team lead to renew."}

João tells Maria (team lead) → Maria runs:
$ headroom auth create-key joao --ttl-days 90
New key: hr_x1y2z3w4...

João updates Claude Code and continues.
```

### Error Flow: Rate Limit

```
João makes request #61 in the minute → 429 Too Many Requests
Retry-After: 23
{"error": "rate_limit_exceeded", "retry_after_seconds": 23}

João waits 23 seconds and the next request goes through.
```

## High-Level Technical Constraints

- **Middleware**: ASGI middleware as a `headroom.proxy_extension` plugin (ADR-002)
- **Cache**: In-memory, TTL 10s, no Redis in MVP
- **Rate limiter**: Token bucket (already exists in `headroom/proxy/rate_limiter.py`), extended to key by `user_id`
- **Encryption**: Fernet for provider keys (same `HEADROOM_ENCRYPTION_KEY` from PRD 1)
- **Non-regression**: `HEADROOM_AUTH_ENABLED=false` → middleware is no-op, proxy identical to original
- **Observability**: Prometheus metrics with `user` label, logs with `user_id` field

## Non-Goals (Out of Scope)

- **SSO / OIDC / JWT** — no federated authentication (MVP)
- **MFA / 2FA** — no second authentication factor
- **IP allowlisting** — no IP or CIDR restrictions
- **Per-model access control** — all developers in a role access the same models
- **WebSocket auth** — Codex relay WebSocket auth is deferred to PRD 2.1
- **Request auditing** — Neo4j and Qdrant logging is PRD 3
- **Budgets** — per-user/team spending limits (out of scope, could be a future PRD)

## Phased Rollout Plan

### MVP (Phase 1) — PRD 2

- Auth middleware as `headroom-auth` plugin
- Key validation (SHA-256 + Neo4j)
- User → role → provider_keys resolution
- Automatic provider key injection by path
- Per-user_id rate limit with `X-RateLimit-*` headers
- Local cache (TTL 10s) with fallback when Neo4j is down
- Health check bypass (`/livez`, `/readyz`, `/health`, `/metrics`)
- user_id propagation via contextvars
- Rate limit headers in responses
- 401 errors with informative messages (invalid key, expired key, inactive user)

### Phase 2 (post-MVP)

- Shared cache via Redis (for multi-worker/multi-instance)
- Customizable rate limits per role via CLI (PRD 1 Phase 3)
- Per-model rate limits (e.g. expensive model has lower limit)
- WebSocket auth for Codex relay (PRD 2.1)

### Phase 3 (long term)

- SSO/JWT via external identity provider
- IP allowlisting per key
- Per-model access control (role X only accesses models Y and Z)
- Rate limit with sliding window (more precise than token bucket)

## Success Metrics

| Metric | Target |
|--------|--------|
| Auth latency (cache hit) | < 1ms p95 |
| Auth latency (cache miss, Neo4j query) | < 5ms p95 |
| False positive rate (valid key rejected) | 0% |
| Availability during Neo4j failure | 100% (cache) |
| Requests rejected by rate limit | < 1% of total requests |
| Auth activation time (toggle flag + restart) | < 2 seconds |

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| **HEADROOM_ENCRYPTION_KEY is wrong** | Explicit error at startup: "HEADROOM_ENCRYPTION_KEY is invalid — provider keys could not be decrypted" |
| **Race condition: key revoked but cache still active** | Cache TTL of 10s limits the window to 10 seconds max. MVP accepts this window. Phase 2 may add signal file for immediate invalidation. |
| **Multi-worker: inconsistent cache across workers** | MVP with single worker; Phase 2 migrates to Redis when needed |
| **Provider key removed but cache still has it** | Same invalidation mechanism; low TTL mitigates |
| **Rate limit too restrictive (developers complain)** | Per-role metrics allow calibration; limits adjustable via CLI |

## Architecture Decision Records

- [ADR-001: Pure Admin CLI](adrs/adr-001.md) — CLI as the sole administration interface
- [ADR-002: Auth middleware as plugin](adrs/adr-002.md) — Auth middleware as a separate extension

## Open Questions

- ~~Should cache invalidation be synchronous (internal HTTP endpoint) or asynchronous (signal file)?~~ **Resolved**: MVP uses short TTL (10s) as the invalidation mechanism. Signal file or endpoint can be added in Phase 2 if the 10s window is unacceptable.
- Should there be a "bypass" mode for debugging (header `x-headroom-auth-bypass: <admin-key>`)?
- ~~Should WebSocket auth (Codex relay) be a separate PRD 2.1 or included in the MVP?~~ **Resolved**: Separate PRD 2.1. Codex relay is not yet active. See `_prd-2.1-websocket-auth.md`.
- Is the current rate limiter (token bucket) sufficient or do we need sliding window for better precision?
