## 1. Middleware — WebSocket handshake interception

- [ ] 1.1 Extend `AuthMiddleware` to inspect WebSocket upgrade requests (scope type "websocket")
- [ ] 1.2 Extract and validate `Authorization: Bearer hr_...` header during handshake
- [ ] 1.3 Return 401 before protocol switch for missing/invalid keys

## 2. Identity — session attachment

- [ ] 2.1 Resolve user identity via `Neo4jAuthStore.resolve_key_identity()` during handshake
- [ ] 2.2 Attach resolved identity to WebSocket session scope
- [ ] 2.3 Set contextvars so downstream components see the authenticated user

## 3. Provider injection — upstream WebSocket

- [ ] 3.1 Resolve provider from request path using existing `resolve_provider()` 
- [ ] 3.2 Inject decrypted provider key into upstream WebSocket connection headers
- [ ] 3.3 Handle missing provider key gracefully (return error before upgrade)

## 4. Session timeout — max duration

- [ ] 4.1 Start a 30-minute timer when WebSocket connection is established
- [ ] 4.2 Close the WebSocket connection when the timer expires
- [ ] 4.3 Log session close reason (timeout vs client disconnect)

## 5. Audit logging — RequestLog for WebSocket

- [ ] 5.1 Create `(:RequestLog)` node with `transport: "websocket"` on successful handshake
- [ ] 5.2 Include user_id, username, provider, model, and timestamp
- [ ] 5.3 Create `(:User)-[:MADE_REQUEST]->(:RequestLog)` relationship

## 6. Tests

- [ ] 6.1 Test valid key allows WebSocket upgrade
- [ ] 6.2 Test missing key returns 401
- [ ] 6.3 Test invalid key returns 401
- [ ] 6.4 Test identity is attached to WebSocket session
- [ ] 6.5 Test session timeout closes connection
- [ ] 6.6 Test RequestLog node created with transport: websocket
