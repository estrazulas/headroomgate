## ADDED Requirements

### Requirement: Role-based access scope for audit queries
The system SHALL enforce role-based access scope on all audit queries. The scope SHALL be: admin sees all requests, team lead sees their team's requests, developer sees only their own requests.

#### Scenario: Admin sees everything
- **WHEN** admin runs any `headroom audit` query
- **THEN** no scope filter is applied — all requests are included

#### Scenario: Team lead sees only their team
- **WHEN** team lead of "backend" runs `headroom audit user joao --last 7d`
- **THEN** the query is scoped to `team: "backend"` — if joao is not in backend, no results are returned

#### Scenario: Developer sees only self
- **WHEN** developer "joao" runs `headroom audit user maria --last 7d`
- **THEN** the system returns an error: "You can only view your own requests. Use --self."

#### Scenario: Developer uses --self successfully
- **WHEN** developer "joao" runs `headroom audit user --self --last 7d`
- **THEN** the query is scoped to `user_id: "u_joao"`

### Requirement: Identity resolution for CLI
The audit CLI SHALL resolve the caller's identity from the contextvar set by PRD 2 middleware. When running outside the proxy (direct CLI), identity SHALL be resolved from the `HEADROOM_API_KEY` environment variable.

#### Scenario: Identity from contextvar in proxy context
- **WHEN** `headroom audit` is called within the proxy process
- **THEN** `user_id`, username, role, and team are read from contextvars (set by auth middleware)

#### Scenario: Identity from env var for direct CLI
- **WHEN** `headroom audit` is called directly (not within proxy) with `HEADROOM_API_KEY=hr_...`
- **THEN** the key is validated against Neo4j and identity is resolved

### Requirement: Scope applied to semantic search
The same role-based scope SHALL apply to `audit search` queries. Qdrant results SHALL be filtered by user_id or team before returning.

#### Scenario: Semantic search scoped by role
- **WHEN** developer runs `headroom audit search "authentication" --last 30d`
- **THEN** results are filtered to only the developer's own requests, regardless of what Qdrant returns

### Requirement: Scope error messages
Access violations SHALL return clear error messages indicating the restriction and the correct flag to use.

#### Scenario: Cross-user access denied
- **WHEN** developer tries to view another user's data
- **THEN** error message: "You can only view your own requests. Use --self."

#### Scenario: Cross-team access denied
- **WHEN** team lead of "backend" tries to view "frontend" team data
- **THEN** error message: "You can only view your team's data. Requested team 'frontend' is outside your scope."
