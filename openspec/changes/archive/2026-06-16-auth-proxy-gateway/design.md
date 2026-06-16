## Context

The headroom proxy runs as a FastAPI application with an established extension system (`headroom.proxy_extension` entry-point group, see `headroom/proxy/extensions.py`). The `headroom-oauth2` plugin at `plugins/headroom-oauth2/` is the reference implementation: it registers an ASGI middleware that transforms the `Authorization` header on every request.

PRD 1 delivered the persistence layer: `Neo4jAuthStore` (14 Cypher methods in `headroom/auth/store.py`), `FernetCrypto` (encrypt/decrypt in `headroom/auth/crypto.py`), and data models (`User`, `Role`, `ApiKey` in `headroom/auth/models.py`). These are production-tested with 51 passing tests.

PRD 2 must wire these components into the request pipeline as an opt-in extension, ensuring zero behavior change when the plugin is not activated.

## Goals / Non-Goals

**Goals:**

- Authenticate every incoming request (except health checks) by validating `hr_...` proxy keys against Neo4j
- Resolve user identity (username, role, team) and store it in `contextvars` for downstream consumers
- Decrypt and inject the correct provider API key based on request path
- Apply per-user rate limits with standard `X-RateLimit-*` response headers
- Cache validation results in memory with TTL to minimize Neo4j load
- Gracefully degrade when Neo4j is unreachable (use stale cache entries)
- Follow the existing `headroom.proxy_extension` pattern exactly — `install(app, config) -> None`

**Non-Goals:**

- WebSocket authentication (PRD 2.1)
- Redis-based shared cache (Phase 2)
- Custom per-user rate limits (role-level only in MVP)
- Per-model access control
- SSO / OIDC / JWT

## Decisions

### Decision 1: Auth middleware as a separate plugin (`headroom.proxy_extension`)

The auth middleware is packaged as `plugins/headroom-auth/`, registering an entry-point in the `headroom.proxy_extension` group. Activated via `--proxy-extension headroom-auth` or `HEADROOM_PROXY_EXTENSIONS=headroom-auth`.

**Alternatives considered:**

- **Built-in middleware in `server.py`**: Less boilerplate, but couples auth to proxy core. The extension pattern exists precisely to avoid this coupling. Rejected.
- **External auth service (sidecar)**: Maximum decoupling, but adds HTTP round-trip latency per request and one more service to deploy. Overengineered for MVP. Rejected.

**Rationale:** Consistent with `headroom-oauth2`. Total isolation — when not activated, the proxy is identical to the original. Any developer who understands the oauth2 plugin understands auth.

### Decision 2: ASGI middleware (not FastAPI `@app.middleware("http")`)

The middleware is a plain ASGI class with `__call__(self, scope, receive, send)`, matching `OAuth2Middleware`. It inspects `scope["type"]` to skip non-HTTP requests (WebSocket, lifespan) and `scope["path"]` to skip health checks.

**Alternatives considered:**

- **FastAPI `@app.middleware("http")` decorator**: Simpler API, but `install()` would need a reference to the `app` object at decoration time. ASGI middleware gives us full control over scope mutation (header replacement) before routing.
- **Starlette `BaseHTTPMiddleware`**: Adds overhead from the request/response wrapper. Plain ASGI avoids this.

**Rationale:** Match the oauth2 plugin pattern exactly. ASGI gives direct access to scope headers for injection and avoids the performance penalty of `BaseHTTPMiddleware`.

### Decision 3: In-memory cache with TTL (10s default)

A dictionary keyed by SHA-256 hash of the proxy key, storing a dataclass with `(user_id, username, role, provider_keys_decrypted, rpm, tpm, expires_at)`. Entries older than TTL are refreshed from Neo4j. If Neo4j is unreachable, stale entries are served with a warning log.

**Alternatives considered:**

- **Redis**: Shared across workers, instant invalidation. Rejected for MVP — adds operational complexity (one more service). Phase 2 will add Redis.
- **No cache, query Neo4j every request**: Simplest code, but ~5ms Neo4j latency on every request is unacceptable at scale. Rejected.
- **functools.lru_cache**: No TTL support, no invalidation. Rejected.

**Rationale:** The 10s TTL is a deliberate trade-off — a revoked key may remain valid for up to 10 seconds. The PRD 2 risk analysis accepts this window for MVP. A signal-file or internal endpoint for immediate invalidation can be added in Phase 2 if needed.

### Decision 4: Token bucket rate limiter keyed by `user_id`

Reuse the existing `TokenBucketRateLimiter` from `headroom/proxy/rate_limiter.py`. Instead of keying by IP or API key, the auth middleware passes `user_id` as the bucket key. RPM and TPM limits are read from the user's role (`Role.default_rpm`, `Role.default_tpm`).

**Alternatives considered:**

- **New rate limiter implementation**: Duplicates code. Rejected.
- **Sliding window**: More precise but more complex. The existing token bucket is sufficient for MVP. Phase 3 may add sliding window.

**Rationale:** Extend, don't rewrite. The token bucket is already production-tested in headroom. Per-user_id keying gives each user an independent bucket, so one user's burst doesn't affect others.

### Decision 5: `contextvars` for identity propagation

Store `user_id`, username, role, and team in `contextvars.ContextVar` instances, following the exact pattern of `headroom/proxy/project_context.py` (`_current_project`).

**Alternatives considered:**

- **`request.state` (Starlette)**: Ties identity to the Request object — not accessible from non-request contexts (background tasks, WebSocket handlers). Rejected.
- **`threading.local`**: Breaks with async — multiple requests share the same thread. Rejected.

**Rationale:** `contextvars` is the Python standard for async-safe request-scoped state. The project_context module already proves the pattern within this codebase.

### Decision 6: Provider key injection by path mapping

A static mapping of path prefixes to provider names:

| Path prefix | Provider |
|-------------|----------|
| `/v1/messages` | `anthropic` |
| `/v1/chat/completions` | `openai` |
| `/v1beta/models/` | `gemini` |
| `/v1internal/` | `cloudcode` |

The resolved provider name is used to look up the encrypted key from the role's `provider_keys` JSON dict, decrypt it via `FernetCrypto`, and inject it into the `Authorization` header.

**Alternatives considered:**

- **Header-based detection** (x-api-key, x-goog-api-key): More flexible but fragile — depends on client behavior. Rejected for MVP; fallback detection can be added for unmatched paths.
- **Dynamic provider resolution from request body**: Requires buffering/parsing the body, which adds latency and complexity. Rejected.

**Rationale:** The path-based mapping matches headroom's existing routing (`proxy_routes.py`) and covers 100% of current LLM API traffic.

### Decision 7: Error response format

All auth errors return JSON with a consistent error format:

```json
{"error": "<error_code>", "message": "<human-readable>"}
```

Status codes: 401 (key missing/invalid/expired), 403 (user deactivated), 429 (rate limited), 502 (upstream auth failure).

**Alternatives considered:**

- **Plain text responses**: Simpler but harder for clients to parse programmatically.
- **Anthropic/OpenAI error format**: Provider-specific formats leak implementation details. Generic JSON is neutral.

**Rationale:** Consistent with headroom's existing error responses. The `error` field enables programmatic handling; the `message` field is human-readable for debugging.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| **HEADROOM_ENCRYPTION_KEY is wrong** | Explicit error at startup: "HEADROOM_ENCRYPTION_KEY is invalid — provider keys cannot be decrypted" |
| **Race condition: key revoked but cache still active** | Cache TTL of 10s limits the window to 10 seconds max. MVP accepts this window. |
| **Multi-worker: inconsistent cache across workers** | MVP with single worker; Phase 2 migrates to Redis |
| **Provider key removed but cache still has it** | Same TTL-based invalidation; low TTL mitigates |
| **Rate limit too restrictive** | Per-role metrics allow calibration; limits adjustable via CLI |
| **Neo4j connection pool exhaustion** | Reuse the existing Neo4j driver pattern with connection pooling. The cache reduces query volume by ~100x (1 query per key per 10s vs 1 per request). |

## Migration Plan

1. **Deploy**: Install `headroom-auth` package alongside the proxy, add `--proxy-extension headroom-auth` to the launch command
2. **Rollback**: Remove `--proxy-extension headroom-auth` — the proxy reverts to anonymous mode instantly
3. **Gradual rollout**: The `HEADROOM_AUTH_ENABLED` flag (read at plugin init time) allows enabling auth on a subset of instances first
4. **No database migration needed**: Reuses the existing Neo4j schema from PRD 1

## Open Questions

- Is the current rate limiter (token bucket) sufficient or do we need sliding window for better precision? → **Deferred to Phase 3 metrics**
- Should there be a "bypass" mode for debugging (header `x-headroom-auth-bypass: <admin-key>`)? → **Deferred to post-MVP**
- Cache TTL default: 10s is reasonable for key validation. Should it be lower for provider key changes? → **10s applies to both; same TTL for simplicity**
- Should the rate limiter be called within the auth middleware or as a separate middleware? → **Within auth middleware (simplifies ordering, per ADR-002)**
