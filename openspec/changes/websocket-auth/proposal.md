## Why

PRD 2 (Auth Proxy Gateway) covers authentication for HTTP REST requests. WebSocket
connections (`/v1/responses` for Codex relay) have a different model: the API key
only appears in the initial HTTP handshake, and the connection stays open for minutes
or hours. When Codex relay support is activated, WebSocket connections would bypass
authentication entirely — every Codex user would have unauthenticated, unlogged
access to the proxy.

This change adds auth validation at the WebSocket handshake so that every connection
is authenticated, identity is resolved, and connections are logged for audit.

## What Changes

- Validate `Authorization: Bearer hr_...` header during WebSocket handshake
- Resolve user identity from Neo4j before upgrading to WebSocket
- Inject provider key into the upstream WebSocket connection
- Enforce a max session timeout (30 min) to limit the window for key revocation
- Log WebSocket connections as `(:RequestLog)` nodes with `transport: "websocket"`

## Capabilities

### New Capabilities

- `websocket-auth`: Authenticate WebSocket handshakes and log connections

## Impact

- `plugins/headroom-auth/src/headroom_auth/middleware.py` — extend to intercept WebSocket upgrade
- `headroom/proxy/server.py` — add WebSocket handshake hook
- `tests/auth/test_middleware.py` — add WebSocket auth tests

## Non-goals

- Rate limiting per WebSocket event (complex, deferred)
- Cutting active sessions on key revocation (MVP accepts session continues until timeout)
- Provider support beyond OpenAI for WebSocket (Codex only)

## Status: Deferred

Implementation is deferred until the Codex relay is activated in Headroom.
All infrastructure (auth middleware, Neo4j store, identity contextvars) already exists.
Estimated work: ~2 hours.
