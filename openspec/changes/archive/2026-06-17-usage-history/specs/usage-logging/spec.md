## ADDED Requirements

### Requirement: Request summary stored in Neo4j
The system SHALL store the first 500 characters of the user's request message as a `summary` property on each `(:RequestLog)` node in Neo4j. The summary enables direct history listing without requiring Qdrant semantic search.

#### Scenario: Summary stored during batch flush
- **WHEN** the audit buffer flushes a batch of authenticated requests to Neo4j
- **THEN** each `(:RequestLog)` node includes a `summary` property containing the first 500 characters of the user's request message

#### Scenario: Summary truncated for long requests
- **WHEN** a user's request message exceeds 500 characters
- **THEN** the `summary` property contains only the first 500 characters

#### Scenario: Summary empty for requests without user message
- **WHEN** an authenticated request has no user message (e.g., system-only prompts)
- **THEN** the `summary` property is set to an empty string
