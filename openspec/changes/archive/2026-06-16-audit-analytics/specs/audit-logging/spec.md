## ADDED Requirements

### Requirement: Async request logging to Neo4j
The system SHALL record every authenticated request as a `(:RequestLog)` node in Neo4j. Logging SHALL be asynchronous — the response to the client SHALL NOT be blocked by the Neo4j write.

#### Scenario: Request logged asynchronously
- **WHEN** an authenticated request completes with user_id "u_joao", provider "anthropic", model "claude-sonnet-4-6", 3200 input tokens, 1100 output tokens, 200ms latency, cache hit
- **THEN** a `(:RequestLog)` node is created with `user_id: "u_joao"`, `username: "joao"`, `provider: "anthropic"`, `model: "claude-sonnet-4-6"`, `input_tokens: 3200`, `output_tokens: 1100`, `latency_ms: 200`, `cache_hit: true`, `status_code: 200`, and `timestamp` set to UTC now
- **AND** the response to the client is returned before the Neo4j write completes

#### Scenario: Relationship links user to request log
- **WHEN** a `(:RequestLog)` node is created for user_id "u_joao"
- **THEN** a `(:User {user_id: "u_joao"})-[:MADE_REQUEST]->(:RequestLog)` relationship is created

#### Scenario: Unauthenticated requests are not logged
- **WHEN** an unauthenticated request completes (no user_id in contextvar)
- **THEN** no `(:RequestLog)` node is created

### Requirement: In-memory buffer with batch flush
The system SHALL accumulate `(:RequestLog)` entries in an in-memory deque buffer and flush them to Neo4j in batch when the buffer reaches 50 entries or 5 seconds have elapsed since the last flush.

#### Scenario: Flush on buffer size
- **WHEN** the buffer accumulates 50 entries
- **THEN** all 50 entries are written to Neo4j in a single `UNWIND $batch CREATE` Cypher query
- **AND** the buffer is cleared

#### Scenario: Flush on time elapsed
- **WHEN** the buffer has 10 entries and 5 seconds have elapsed since the last flush
- **THEN** all 10 entries are written to Neo4j

#### Scenario: Buffer overflow drops oldest entries
- **WHEN** the buffer exceeds 5000 entries (hard cap)
- **THEN** the oldest entries are dropped with a warning log

#### Scenario: Neo4j flush failure retries
- **WHEN** a batch flush to Neo4j fails
- **THEN** the system retries once after 1 second
- **AND** if the retry fails, the entries are dropped with an error log

### Requirement: RequestLog schema
Each `(:RequestLog)` node SHALL include: `request_id`, `user_id`, `username` (denormalized), `team` (denormalized), `provider`, `model`, `input_tokens`, `output_tokens`, `tokens_saved`, `latency_ms`, `cache_hit`, `status_code`, and `timestamp`.

#### Scenario: Complete RequestLog node
- **WHEN** a request log is created
- **THEN** all schema fields are populated from the RequestOutcome and identity contextvar
