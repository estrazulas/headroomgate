## Context

PRD 2 middleware (`AuthMiddleware`) intercepts HTTP requests via ASGI. WebSocket
connections go through an HTTP handshake first (with `Upgrade: websocket` header),
then switch protocols. The auth check must happen BEFORE the protocol switch.

## Decisions

### Decision 1: Auth at handshake, not per-event

**Choice:** Validate the API key once during the HTTP→WebSocket upgrade handshake.
The resolved identity is attached to the WebSocket session object and reused for
the lifetime of the connection.

**Alternatives considered:**
- **Per-message auth**: Each WebSocket frame carries an auth token. Adds latency
  to every message and requires protocol changes. Rejected — overkill for MVP.
- **No auth**: WebSocket connections bypass auth entirely. Rejected — creates an
  unauthenticated backdoor.

**Why?** The handshake is the natural auth point — it's an HTTP request before the
upgrade, so the existing `_extract_auth_header` logic works unchanged. Identity
lives on the session object for the connection lifetime.

### Decision 2: Max session timeout (30 minutes)

**Choice:** Hard-limit WebSocket sessions to 30 minutes. After timeout, the proxy
closes the connection. The client must re-handshake with a valid key.

**Alternatives considered:**
- **Unlimited sessions**: Revoked keys would have an indefinite window. Rejected.
- **Active revocation poll**: Periodically check if the key is still valid during
  the session. Adds Neo4j query overhead. Rejected for MVP.

**Why?** 30 minutes is long enough for a typical Codex session, short enough that
a revoked key is blocked within a reasonable window.

### Decision 3: Log as RequestLog with transport field

**Choice:** Create a `(:RequestLog)` node with `transport: "websocket"` at connection
time. Do not create per-event logs (too many).

**Alternatives considered:**
- **Per-event logging**: One RequestLog per WebSocket message. Would flood Neo4j.
  Rejected.
- **No logging**: WebSocket connections invisible to audit. Rejected.

**Why?** One log entry per connection gives the admin visibility into who used
Codex and when, without overwhelming the database.

## Risks

- **Session timeout may interrupt long sessions**: Mitigated by 30-minute default.
- **Revoked keys have a window**: A key revoked at T+0 continues working until the
  session ends at T+30. Acceptable for MVP.

## Open Questions

- Should the session timeout be configurable via env var?
- Should WebSocket connections count toward rate limits?
