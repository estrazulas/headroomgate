## ADDED Requirements

### Requirement: WebSocket handshake authentication
The system SHALL validate the `Authorization: Bearer hr_...` header during the HTTP handshake that precedes a WebSocket upgrade. If the key is invalid or missing, the handshake SHALL be rejected with 401 before the protocol switch occurs.

#### Scenario: Valid key allows WebSocket upgrade
- **WHEN** a client sends a WebSocket upgrade request with a valid `Authorization: Bearer hr_...` header
- **THEN** the proxy resolves the user identity from Neo4j and allows the protocol upgrade

#### Scenario: Missing key rejects WebSocket upgrade
- **WHEN** a client sends a WebSocket upgrade request without an `Authorization` header
- **THEN** the proxy returns 401 and does NOT upgrade the connection

#### Scenario: Invalid key rejects WebSocket upgrade
- **WHEN** a client sends a WebSocket upgrade request with an invalid API key
- **THEN** the proxy returns 401 and does NOT upgrade the connection

### Requirement: Identity propagation to WebSocket session
The system SHALL attach the resolved user identity (user_id, username, role, team) to the WebSocket session object after successful handshake authentication.

#### Scenario: Identity available during WebSocket session
- **WHEN** a WebSocket connection is established after successful auth
- **THEN** the session object carries the user's identity accessible via contextvars

### Requirement: Provider key injection for WebSocket
The system SHALL inject the decrypted provider API key into the upstream WebSocket connection request, using the same path-based provider resolution as HTTP requests.

#### Scenario: Provider key injected for Codex WebSocket
- **WHEN** a WebSocket connection targets `/v1/responses`
- **THEN** the proxy resolves the provider as "openai" and injects the decrypted API key

### Requirement: WebSocket session timeout
The system SHALL enforce a maximum session duration of 30 minutes for WebSocket connections. After the timeout, the proxy SHALL close the connection.

#### Scenario: Session closed after timeout
- **WHEN** a WebSocket connection has been open for 30 minutes
- **THEN** the proxy closes the connection

### Requirement: WebSocket connection logging
The system SHALL log each WebSocket connection as a `(:RequestLog)` node in Neo4j with `transport: "websocket"` and the authenticated user's identity.

#### Scenario: WebSocket connection logged
- **WHEN** a WebSocket upgrade handshake succeeds
- **THEN** a `(:RequestLog)` node is created with `transport: "websocket"`, `user_id`, `username`, `provider`, and `timestamp`
