# Session Bridge — PRD 2: Authenticated Proxy Gateway

## Context for the next session

You are continuing work on the **multi-user auth control** system for the headroom proxy.
The repository is `headroom_sanitizer` (headroom LLM proxy).

### What was completed (PRD 1 — Admin CLI & User Management)

PRD 1 is **fully implemented and tested** on branch `feat/admin-cli-user-management`:

- `headroom/auth/models.py` — User, Role, Team, ApiKey dataclasses
- `headroom/auth/crypto.py` — FernetCrypto class (encrypt, decrypt, validate_key, generate_key)
- `headroom/auth/store.py` — Neo4jAuthStore (14 methods via Cypher)
- `headroom/cli/auth.py` — 16 Click commands (init-db, create-user, whoami, generate-key, etc.)
- `pyproject.toml` — `[auth]` extra with `cryptography` + `neo4j`
- `tests/auth/` — **51 tests passing** (9 models + 7 crypto + 15 store + 20 CLI)
- OpenSpec main specs synced: `openspec/specs/admin-cli/`, `openspec/specs/auth-crypto/`, `openspec/specs/auth-store/`

### What needs to be done (PRD 2 — Authenticated Proxy Gateway)

The PRD is at: `.compozy/tasks/multi-user-auth-control/_prd-2-auth-gateway.md`

PRD 2 needs the **OpenSpec workflow**: propose → align → apply → archive

#### Step 0: Branch
Create branch `feat/auth-proxy-gateway` **from** `feat/admin-cli-user-management`:
```bash
git checkout feat/admin-cli-user-management
git checkout -b feat/auth-proxy-gateway
```

#### Step 1: Create OpenSpec change
Run `/opsx:propose` to create the change for PRD 2.

Key facts for the proposal:
- **What**: ASGI middleware plugin (`plugins/headroom-auth/`) that intercepts every request, validates the proxy key (`hr_...`), resolves identity, injects provider key, and applies per-user rate limits
- **Pattern**: Follows `headroom-oauth2` plugin structure (`plugins/headroom-oauth2/`)
- **Entry point**: `headroom.proxy_extension` group (see `headroom/proxy/extensions.py`)
- **Depends on**: `headroom.auth.store` (Neo4jAuthStore) and `headroom.auth.crypto` (FernetCrypto) from PRD 1
- **Activation**: `--proxy-extension headroom-auth` or `HEADROOM_PROXY_EXTENSIONS=headroom-auth`
- **Non-regression**: When disabled, proxy is identical to original

#### Step 2: Align artifacts
Already aligned from the PRD review session:
- Cache invalidation: TTL 10s (no signal file in MVP)
- WebSocket auth: deferred to PRD 2.1 (`_prd-2.1-websocket-auth.md`)
- All artifacts are in English

#### Step 3: Implement (apply)
The middleware plugin needs:
- `plugins/headroom-auth/pyproject.toml` — package with entry-point
- `plugins/headroom-auth/src/headroom_auth/__init__.py` — `install(app, config)`
- `plugins/headroom-auth/src/headroom_auth/middleware.py` — ASGI middleware
- `plugins/headroom-auth/src/headroom_auth/cache.py` — In-memory validation cache (TTL 10s)
- `plugins/headroom-auth/src/headroom_auth/provider_injector.py` — Provider key injection by path
- `plugins/headroom-auth/src/headroom_auth/rate_limiter.py` — Per-user rate limiter

#### Step 4: Archive
After implementation and tests pass, run `/opsx:archive`.

### Key decisions already made

| Decision | Value |
|----------|-------|
| Language | English for all code, CLI, docs, errors |
| Plugin pattern | `headroom.proxy_extension` (same as headroom-oauth2) |
| Cache TTL | 10 seconds |
| Rate limiter | Token bucket per user_id (extends existing `headroom/proxy/rate_limiter.py`) |
| Encryption | Fernet via `HEADROOM_ENCRYPTION_KEY` |
| Health check bypass | `/livez`, `/readyz`, `/health`, `/metrics` never require auth |
| Identity propagation | `contextvars` (same pattern as `headroom/proxy/project_context.py`) |
| WebSocket auth | NOT in this PRD — see PRD 2.1 |

### Files to read before starting

Core patterns to understand:
- `headroom/proxy/extensions.py` — proxy extension discovery and install
- `plugins/headroom-oauth2/src/headroom_oauth2/__init__.py` — reference plugin
- `headroom/proxy/project_context.py` — contextvars pattern for per-request identity
- `headroom/proxy/rate_limiter.py` — existing token bucket rate limiter
- `headroom/auth/store.py` — Neo4jAuthStore (already implemented)
- `headroom/auth/crypto.py` — FernetCrypto (already implemented)

Planning artifacts:
- `.compozy/tasks/multi-user-auth-control/_prd-2-auth-gateway.md` — PRD
- `.compozy/tasks/multi-user-auth-control/adrs/adr-002.md` — ADR: plugin decision
- `openspec/config.yaml` — project context and rules
- `openspec/specs/auth-crypto/spec.md` — crypto spec (dependency)
- `openspec/specs/auth-store/spec.md` — store spec (dependency)

### To run tests

```bash
# Start Neo4j
docker compose up -d neo4j

# Use the venv
source .venv/bin/activate
export NEO4J_URI="neo4j://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="devpassword"

# Run tests
python -m pytest tests/auth/ -v
```
