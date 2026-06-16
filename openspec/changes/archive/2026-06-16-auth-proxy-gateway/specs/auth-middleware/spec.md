## ADDED Requirements

### Requirement: Middleware authenticates every HTTP request
The auth middleware SHALL intercept every incoming HTTP request and validate the `Authorization: Bearer <key>` header. The middleware SHALL skip authentication for WebSocket and lifespan ASGI scope types.

#### Scenario: Valid key on proxied endpoint
- **WHEN** a request arrives at `POST /v1/messages` with `Authorization: Bearer hr_a7f3b9c2d1e5...`
- **THEN** the middleware resolves the user identity from Neo4j
- **AND** stores `user_id`, username, role, and team in contextvars
- **AND** allows the request to proceed to the upstream handler

#### Scenario: Missing auth header
- **WHEN** a request arrives without an `Authorization` header
- **THEN** the middleware returns HTTP 401 with `{"error": "missing_auth_header", "message": "Authorization header is required"}`

#### Scenario: Malformed auth header
- **WHEN** a request arrives with `Authorization: Basic abc123` (not Bearer)
- **THEN** the middleware returns HTTP 401 with `{"error": "invalid_auth_scheme", "message": "Authorization scheme must be Bearer"}`

#### Scenario: Invalid key format
- **WHEN** a request arrives with `Authorization: Bearer invalid` (key does not have `hr_` prefix)
- **THEN** the middleware returns HTTP 401 with `{"error": "invalid_key_format", "message": "API key must start with hr_"}`

#### Scenario: Key not found in database
- **WHEN** a request arrives with a valid-format `hr_...` key that is not in Neo4j
- **THEN** the middleware returns HTTP 401 with `{"error": "invalid_api_key", "message": "API key is not valid"}`

#### Scenario: Expired key
- **WHEN** a request arrives with a key whose `expires_at` is in the past
- **THEN** the middleware returns HTTP 401 with `{"error": "api_key_expired", "message": "Your key has expired. Contact your team lead to renew."}`

#### Scenario: Deactivated key
- **WHEN** a request arrives with a key whose `is_active` is `false`
- **THEN** the middleware returns HTTP 401 with `{"error": "api_key_revoked", "message": "API key has been revoked"}`

#### Scenario: Deactivated user
- **WHEN** a request arrives with a valid key but the owning user's `is_active` is `false`
- **THEN** the middleware returns HTTP 403 with `{"error": "user_deactivated", "message": "Your account has been deactivated"}`

#### Scenario: WebSocket request is skipped
- **WHEN** an ASGI event arrives with `scope["type"]` equal to `"websocket"`
- **THEN** the middleware passes the event through without authentication

### Requirement: Health check endpoints bypass authentication
The auth middleware SHALL NOT require authentication for `GET /livez`, `GET /readyz`, `GET /health`, and `GET /metrics`.

#### Scenario: Health check without auth header
- **WHEN** a request arrives at `GET /livez` without an `Authorization` header
- **THEN** the middleware allows the request to proceed without authentication

#### Scenario: Metrics without auth header
- **WHEN** a request arrives at `GET /metrics` without an `Authorization` header
- **THEN** the middleware allows the request to proceed without authentication

### Requirement: Auth plugin is opt-in via extension system
The auth middleware SHALL be packaged as a `headroom.proxy_extension` plugin at `plugins/headroom-auth/`. When the plugin is not activated (`--proxy-extension headroom-auth` is absent), the proxy SHALL operate identically to the original — no auth checks, no header modification, no performance change.

#### Scenario: Proxy without auth plugin
- **WHEN** the proxy starts without `--proxy-extension headroom-auth`
- **THEN** all requests are processed without authentication
- **AND** no auth-related middleware runs

#### Scenario: Plugin activated via CLI flag
- **WHEN** the proxy starts with `--proxy-extension headroom-auth`
- **THEN** the `install` function is called with the FastAPI app and ProxyConfig
- **AND** the auth middleware is registered in the middleware stack

#### Scenario: Plugin activated via env var
- **WHEN** the proxy starts with `HEADROOM_PROXY_EXTENSIONS=headroom-auth`
- **THEN** the auth middleware is registered in the middleware stack

### Requirement: Identity propagation via contextvars
After successful authentication, the middleware SHALL store `user_id`, username, role, and team in `contextvars.ContextVar` instances accessible throughout the request lifecycle.

#### Scenario: Identity available downstream
- **WHEN** a request is authenticated as user "joao" in role "developer" and team "backend"
- **THEN** `get_current_user()` returns `"joao"`
- **AND** `get_current_role()` returns `"developer"`
- **AND** `get_current_team()` returns `"backend"`

#### Scenario: Identity cleared after request
- **WHEN** an authenticated request completes
- **THEN** subsequent requests start with no identity set

### Requirement: Auth disabled flag as no-op
When the environment variable `HEADROOM_AUTH_ENABLED` is set to `false`, the middleware SHALL pass all requests through without authentication, matching the behavior of the unmodified proxy.

#### Scenario: Auth disabled
- **WHEN** the proxy starts with `HEADROOM_AUTH_ENABLED=false`
- **THEN** all requests proceed without key validation
- **AND** no auth headers are modified
- **AND** identity contextvars remain unset
