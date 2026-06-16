## Why

The headroom proxy currently accepts every incoming request without identity verification. PRD 1 addressed user registration and API key storage, but the runtime authentication layer — the middleware that actually enforces "who is making this request" — does not exist yet. Without it, API keys are stored but never validated at request time, and the proxy cannot enforce per-user rate limits or inject provider keys. This change delivers the authentication runtime, transforming headroom from an anonymous proxy into an identity-gated gateway.

## What Changes

- **New plugin `headroom-auth`** — an ASGI middleware registered via the `headroom.proxy_extension` entry-point, following the same pattern as the existing `headroom-oauth2` plugin
- **Per-request key validation** — every incoming `Authorization: Bearer hr_...` header is SHA-256 hashed and validated against Neo4j (`Neo4jAuthStore` from PRD 1), resolving the user, role, and provider keys
- **In-memory validation cache** — a TTL-based cache (default 10s) avoids querying Neo4j on every request; cache misses fall back to stale entries when Neo4j is unreachable
- **Provider key injection** — the middleware replaces the proxy key with the real provider key (Anthropic, OpenAI, Google, CloudCode) based on the request path, decrypting with `FernetCrypto` from PRD 1
- **Per-user rate limiting** — extends the existing `TokenBucketRateLimiter` to key buckets by `user_id` instead of IP, inheriting RPM/TPM limits from the user's role
- **Health check bypass** — `/livez`, `/readyz`, `/health`, `/metrics` never require authentication
- **Identity propagation** — `user_id`, username, role, and team are stored in `contextvars` for downstream consumers (audit logs, metrics, PRD 3)
- **Non-regression guarantee** — when `HEADROOM_AUTH_ENABLED=false` or the plugin is not activated, the proxy operates identically to the original (zero performance or behavioral change)

## Capabilities

### New Capabilities

- `auth-middleware`: Per-request authentication middleware that validates `hr_...` proxy keys, resolves user identity from Neo4j, and rejects unauthorized requests with 401/403
- `provider-injection`: Automatic provider resolution by request path (`/v1/messages` → anthropic, `/v1/chat/completions` → openai, etc.) and decryption + injection of the real upstream API key
- `per-user-rate-limiting`: Token bucket rate limiter keyed by `user_id` with `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` response headers and 429 with `Retry-After` when exhausted
- `auth-cache`: In-memory TTL-based validation cache with fallback to stale entries when Neo4j is unavailable, configurable via `HEADROOM_AUTH_CACHE_TTL`

### Modified Capabilities

None. PRD 2 adds new capabilities without changing the requirements of `admin-cli`, `auth-crypto`, or `auth-store`. The existing store and crypto modules are reused as-is through their public APIs.

## Non-Goals

- **SSO / OIDC / JWT** — no federated authentication in MVP
- **MFA / 2FA** — no second authentication factor
- **IP allowlisting** — no IP or CIDR restrictions per key
- **Per-model access control** — all users in a role access the same models
- **WebSocket auth** — Codex relay WebSocket authentication is deferred to PRD 2.1
- **Request auditing** — Neo4j and Qdrant logging is PRD 3
- **Redis / shared cache** — in-memory only for MVP; multi-worker shared cache is Phase 2
- **Custom rate limits per user** — limits are role-level only in MVP

## Impact

- **New files**: `plugins/headroom-auth/` package (pyproject.toml, `__init__.py`, `middleware.py`, `cache.py`, `provider_injector.py`, `rate_limiter.py`)
- **Existing code reused**: `headroom/auth/store.py` (Neo4jAuthStore), `headroom/auth/crypto.py` (FernetCrypto), `headroom/auth/models.py` (User, Role, ApiKey), `headroom/proxy/rate_limiter.py` (TokenBucketRateLimiter)
- **Proxy entry-point**: Registers in `headroom.proxy_extension` group — activated via `--proxy-extension headroom-auth` or `HEADROOM_PROXY_EXTENSIONS=headroom-auth`
- **Dependencies**: `cryptography` (fernet) and `neo4j` (already declared in PRD 1's `[auth]` extra); no new third-party dependencies
- **Breaking changes**: None. Auth is opt-in; the proxy is unchanged when the plugin is not activated
