## ADDED Requirements

### Requirement: Semantic logging to Qdrant
The system SHALL generate an embedding from a short textual summary of each authenticated request and upsert it to the `headroom_request_logs` Qdrant collection. Qdrant logging SHALL be best-effort — if Qdrant is unreachable, Neo4j logging SHALL continue unaffected.

#### Scenario: Embedding generated and stored
- **WHEN** an authenticated request completes
- **THEN** a textual summary (first 200 words of the last user message + model + timestamp) is generated
- **AND** an embedding is computed via fastembed BAAI/bge-small-en-v1.5 (384 dimensions)
- **AND** the embedding is upserted to Qdrant collection `headroom_request_logs` with payload `{request_id, user_id, username, team, provider, model, timestamp, summary}`

#### Scenario: Qdrant unavailable — Neo4j continues
- **WHEN** Qdrant is unreachable during embedding upsert
- **THEN** the error is logged at WARNING level
- **AND** the Neo4j `(:RequestLog)` node is still created normally

#### Scenario: Embedding model not installed
- **WHEN** fastembed is not installed or the model fails to load
- **THEN** Qdrant logging is skipped with an INFO log: "audit-semantic: fastembed not available, skipping Qdrant logging"
- **AND** Neo4j logging continues normally

### Requirement: Semantic search can be disabled
The system SHALL support a `--no-audit-semantic` flag (or `HEADROOM_AUDIT_SEMANTIC_ENABLED=false`) that disables Qdrant logging entirely.

#### Scenario: Semantic logging disabled
- **WHEN** the proxy starts with `--no-audit-semantic`
- **THEN** no embeddings are generated
- **AND** no upserts are made to Qdrant
- **AND** Neo4j logging continues normally

### Requirement: Qdrant collection auto-created
The `headroom_request_logs` collection SHALL be created at startup if it does not exist, with 384-dimensional vectors and Cosine distance.

#### Scenario: Collection creation on first run
- **WHEN** the proxy starts with semantic logging enabled and the `headroom_request_logs` collection does not exist
- **THEN** the collection is created with `size: 384`, `distance: Cosine`

#### Scenario: Collection already exists
- **WHEN** the proxy starts and the `headroom_request_logs` collection already exists
- **THEN** no error is raised and the existing collection is used
