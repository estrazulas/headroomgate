## 1. Package Scaffold

- [x] 1.1 Create `plugins/headroom-auth/pyproject.toml` with `headroom.proxy_extension` entry-point pointing to `headroom_auth:install`, dependencies on `neo4j` and `cryptography`, matching the structure of `plugins/headroom-oauth2/pyproject.toml`
- [x] 1.2 Create `plugins/headroom-auth/src/headroom_auth/__init__.py` with the `install(app, config) -> None` function signature, reading `HEADROOM_AUTH_ENABLED` env var (default `"true"`), and registering the ASGI middleware when enabled

## 2. Validation Cache (`auth-cache` spec)

- [x] 2.1 Create `plugins/headroom-auth/src/headroom_auth/cache.py` with `AuthCache` class — an in-memory dict keyed by SHA-256 hash of the proxy key, each entry storing `(user_id, username, role, team, provider_keys_decrypted, rpm, tpm, cached_at)`
- [x] 2.2 Implement TTL eviction: entries older than `HEADROOM_AUTH_CACHE_TTL` seconds (default 10) are refreshed from Neo4j; entries not accessed for >5 minutes are removed via periodic cleanup
- [x] 2.3 Implement stale cache fallback: when `Neo4jAuthStore` raises an error on cache miss, serve the expired entry if one exists with a warning log; if no entry exists, raise an error that the middleware converts to 503

## 3. Identity Propagation (contextvars)

- [x] 3.1 Create `plugins/headroom-auth/src/headroom_auth/identity.py` with `ContextVar` instances for `_current_user_id`, `_current_username`, `_current_role`, `_current_team`, following the pattern in `headroom/proxy/project_context.py`
- [x] 3.2 Implement `set_current_identity(user_id, username, role, team)` and getter functions: `get_current_user()`, `get_current_username()`, `get_current_role()`, `get_current_team()`

## 4. Provider Key Injection (`provider-injection` spec)

- [x] 4.1 Create `plugins/headroom-auth/src/headroom_auth/provider_injector.py` with `PROVIDER_PATH_MAP` — a dict mapping path prefixes to provider names: `/v1/messages` → `anthropic`, `/v1/chat/completions` → `openai`, `/v1beta/models/` → `gemini`, `/v1internal/` → `cloudcode`
- [x] 4.2 Implement `resolve_provider(path: str) -> str | None` that returns the provider name or `None` for unmatched paths
- [x] 4.3 Implement `inject_provider_key(headers, provider_keys_decrypted, provider)` that decrypts the correct provider key via `FernetCrypto` and replaces the `Authorization` header — returns 502 JSON error if the provider key is missing or decryption fails

## 5. Per-User Rate Limiter (`per-user-rate-limiting` spec)

- [x] 5.1 Create `plugins/headroom-auth/src/headroom_auth/rate_limiter.py` extending `headroom.proxy.rate_limiter.TokenBucketRateLimiter`, parameterized by per-user RPM/TPM from the role
- [x] 5.2 Implement `check_rate_limit(user_id, rpm, tpm, estimated_tokens)` that consults the request and token buckets for the given `user_id`, returns `(allowed, retry_after_seconds)`, and sets `X-RateLimit-*` response headers
- [x] 5.3 Implement 429 response with `Retry-After` header when rate limit is exceeded, with JSON body `{"error": "rate_limit_exceeded", "retry_after_seconds": <seconds>}`

## 6. Auth Middleware (`auth-middleware` spec)

- [x] 6.1 Create `plugins/headroom-auth/src/headroom_auth/middleware.py` with `AuthMiddleware` class — an ASGI middleware following the pattern of `OAuth2Middleware` in `plugins/headroom-oauth2/src/headroom_oauth2/middleware.py`
- [x] 6.2 Implement health check bypass: skip authentication for paths `/livez`, `/readyz`, `/health`, `/metrics` (all methods) and for non-HTTP scope types (`websocket`, `lifespan`)
- [x] 6.3 Implement key extraction and validation: parse `Authorization: Bearer <key>` header, validate `hr_` prefix, compute SHA-256 hash, check cache, query `Neo4jAuthStore.get_key_owner()` on miss, return 401/403 JSON errors for invalid/expired/revoked keys and deactivated users
- [x] 6.4 Implement full request pipeline orchestration in `__call__`: (1) skip non-HTTP/health checks, (2) if auth disabled or no auth header → pass through, (3) validate key → cache/store, (4) set identity contextvars, (5) check rate limit, (6) resolve and inject provider key, (7) forward to upstream, (8) clear identity contextvars after response
- [x] 6.5 Implement auth disabled path: when `HEADROOM_AUTH_ENABLED` is `false`, pass all requests through without validation, identity setup, or key injection

## 7. Plugin Entry Point & Integration

- [x] 7.1 Implement `install(app, config)` in `__init__.py`: read `HEADROOM_AUTH_ENABLED`, validate `HEADROOM_ENCRYPTION_KEY` format at startup (fail-closed on invalid key), instantiate `Neo4jAuthStore`, `FernetCrypto`, `AuthCache`, and register `AuthMiddleware` on the FastAPI app via `app.add_middleware()`
- [x] 7.2 Verify the plugin registers correctly with `headroom.proxy_extension` entry-point discovery: running `headroom proxy --proxy-extension headroom-auth` should load and install the middleware without errors

## 8. Tests

- [x] 8.1 Write tests for `AuthCache` (`tests/auth/test_cache.py`): cache hit, cache miss, TTL expiry, stale fallback when Neo4j mock raises, periodic cleanup of old entries, custom TTL via env var — target ≥8 tests
- [x] 8.2 Write tests for identity contextvars (`tests/auth/test_identity.py`): set and get identity, identity isolation between concurrent requests, identity cleared after request — target ≥5 tests
- [x] 8.3 Write tests for provider injector (`tests/auth/test_provider_injector.py`): path resolution for all 4 providers, unknown path returns None, key injection replaces Authorization header, missing provider key returns 502, decryption failure returns 502 — target ≥8 tests
- [x] 8.4 Write tests for per-user rate limiter (`tests/auth/test_rate_limiter.py`): independent buckets per user_id, role-level limits, 429 response format, Retry-After header, admin unlimited — target ≥8 tests
- [x] 8.5 Write tests for auth middleware (`tests/auth/test_middleware.py`): valid key → success with identity, missing auth header → 401, invalid key format → 401, expired key → 401, deactivated user → 403, health check bypass, WebSocket skip, auth disabled pass-through, rate limit exceeded → 429 — target ≥18 tests
- [x] 8.6 Run full test suite and verify ≥47 new tests pass alongside the existing 51 PRD 1 tests (98+ total)

## 9. Verification

- [x] 9.1 Verify the proxy starts without the auth plugin and serves requests normally (non-regression)
- [x] 9.2 Verify the proxy starts with `--proxy-extension headroom-auth` and `HEADROOM_AUTH_ENABLED=false` — auth middleware registered but requests pass through
- [x] 9.3 Verify end-to-end flow: create user + key via CLI (PRD 1), start proxy with auth plugin, make authenticated request → key validated, provider key injected, rate limit headers present
