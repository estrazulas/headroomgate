# admin-cli

Command-line interface (`headroom auth`) for managing users, roles, teams, API keys, and provider keys in the headroom multi-user auth system.

## Purpose

Provide administrators with a Click-based CLI that talks directly to Neo4j — no proxy dependency, no REST API, no web UI. Supports role-based access control so team leads and developers can run commands scoped to their permissions.

## Requirements

### Requirement: CLI group registration
The system SHALL register `headroom auth` as a Click command group under the main `headroom` CLI. The group SHALL be available when the `headroom-ai` package is installed with the `[auth]` extra.

#### Scenario: Command help
- **WHEN** user runs `headroom auth --help`
- **THEN** the system displays available subcommands: init-db, create-user, list-users, revoke-user, reactivate-user, create-team, list-teams, add-user-to-team, create-key, list-keys, revoke-key, set-provider-key, list-provider-keys, create-role, list-roles, whoami, generate-key

#### Scenario: Missing required arguments
- **WHEN** user runs `headroom auth create-user` without required arguments
- **THEN** Click displays usage information and the missing argument name

### Requirement: Access control by role
The CLI SHALL enforce access control based on the identity of the user executing the command. Identity is resolved from the `HEADROOM_AUTH_USER` environment variable or the `--as-user` flag.

#### Scenario: Admin access
- **WHEN** admin runs any `headroom auth` command
- **THEN** the command executes without role-based restrictions

#### Scenario: Team lead access
- **WHEN** team_lead of "backend" runs `headroom auth create-user`
- **THEN** the `--team` argument defaults to "backend" and cannot be changed

#### Scenario: Team lead cross-team restriction
- **WHEN** team_lead of "backend" runs `headroom auth list-users --team frontend`
- **THEN** the system returns an error "Access denied: you can only manage team 'backend'"

#### Scenario: Developer access
- **WHEN** developer runs `headroom auth create-user`
- **THEN** the system returns an error "Access denied: only admin and team_lead can create users"

### Requirement: Neo4j connection
The CLI SHALL connect to Neo4j using the same configuration as the memory backend: `NEO4J_URI` env var or `neo4j://localhost:7687` default, `NEO4J_USER` or `neo4j`, `NEO4J_PASSWORD` or empty.

#### Scenario: Successful connection
- **WHEN** Neo4j is running at the configured URI
- **THEN** the CLI connects and executes commands

#### Scenario: Connection failure
- **WHEN** Neo4j is not reachable
- **THEN** the CLI displays a connection error with the attempted URI, user, and troubleshooting hint
- **AND** exits with non-zero code

### Requirement: Output formats
The CLI SHALL support human-readable table output (default) and machine-readable JSON output (`--json` flag) for list commands.

#### Scenario: Table output
- **WHEN** user runs `headroom auth list-users`
- **THEN** the system displays a formatted table with aligned columns

#### Scenario: JSON output
- **WHEN** user runs `headroom auth list-users --json`
- **THEN** the system outputs a JSON array of user objects

### Requirement: Error messages
The CLI SHALL provide clear, actionable error messages in English (consistent with the existing headroom CLI). Errors SHALL include the specific constraint or value that failed.

#### Scenario: Duplicate username
- **WHEN** creating a user with an existing username
- **THEN** the system outputs "Error: username 'joao' already exists. Use 'list-users' to check."

#### Scenario: Invalid role
- **WHEN** creating a user with a non-existent role
- **THEN** the system outputs "Error: role 'superadmin' does not exist. Use 'list-roles' to see available roles."
