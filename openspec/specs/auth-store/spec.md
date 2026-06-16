# auth-store

Neo4j schema and data access layer for multi-user access control.

## Purpose

Provide persistence for users, roles, teams, and API keys in Neo4j using Cypher via `GraphDatabase.driver`. Reuses the same driver pattern as `DirectMem0Adapter`. All operations are idempotent where possible (MERGE for creation, soft-delete for revocation).

## Requirements

### Requirement: Database initialization
The system SHALL provide an `init-db` command that creates Neo4j constraints and base roles. The operation MUST be idempotent — running it multiple times SHALL NOT fail or duplicate data. The command SHALL ask for confirmation if an existing schema is detected.

#### Scenario: First initialization
- **WHEN** admin runs `headroom auth init-db` on a Neo4j instance without auth constraints
- **THEN** the system creates uniqueness constraints for `User.user_id`, `User.username`, `Role.name`, and `ApiKey.key_hash`
- **AND** creates 4 base roles: `admin`, `team_lead`, `developer`, `viewer`

#### Scenario: Re-initialization with confirmation
- **WHEN** admin runs `headroom auth init-db` on an already-initialized instance
- **THEN** the system detects existing roles and prompts "Auth schema may already be initialized. Re-run init-db to verify constraints? [y/N]"
- **AND** existing roles are not duplicated

#### Scenario: Skip confirmation with --yes
- **WHEN** admin runs `headroom auth init-db --yes`
- **THEN** the system runs idempotently without prompting

### Requirement: User CRUD operations
The system SHALL support creating, listing, deactivating, and reactivating users. Each user MUST belong to exactly one role and one team.

#### Scenario: Create user
- **WHEN** admin runs `headroom auth create-user joao --role developer --team backend`
- **THEN** a `:User` node is created with `user_id` (UUIDv4), `username: "joao"`, `role: "developer"`, `team: "backend"`, `is_active: true`, and `created_at` timestamp

#### Scenario: Create duplicate user
- **WHEN** admin tries to create a user with an existing username
- **THEN** the system returns an error message "username 'joao' already exists" and exits with non-zero code

#### Scenario: List users
- **WHEN** admin runs `headroom auth list-users`
- **THEN** the system displays a table with columns: username, role, team, is_active, and key count for every user

#### Scenario: List users filtered by team
- **WHEN** admin runs `headroom auth list-users --team backend`
- **THEN** the system displays only users belonging to team "backend"

#### Scenario: Revoke user
- **WHEN** admin runs `headroom auth revoke-user joao`
- **THEN** the `:User` node for "joao" has `is_active` set to `false`
- **AND** all `:ApiKey` nodes owned by "joao" have `is_active` set to `false`
- **AND** a confirmation message shows the username and number of keys revoked

#### Scenario: Reactivate user
- **WHEN** admin runs `headroom auth reactivate-user joao`
- **THEN** the `:User` node for "joao" has `is_active` set to `true`
- **AND** previously revoked keys remain inactive (must be re-created)

### Requirement: Team CRUD operations
The system SHALL support creating, listing, and removing teams. Teams group users for access control scoping.

#### Scenario: Create team
- **WHEN** admin runs `headroom auth create-team backend`
- **THEN** a `:Team` node is created with `name: "backend"` and `created_at` timestamp

#### Scenario: List teams
- **WHEN** admin runs `headroom auth list-teams`
- **THEN** the system displays a table with columns: team name, member count, and active member count

#### Scenario: Add user to team
- **WHEN** admin runs `headroom auth add-user-to-team joao backend`
- **THEN** the `:User` node for "joao" has `team` set to "backend"

### Requirement: API key lifecycle
The system SHALL generate proxy API keys with prefix `hr_`, store their SHA-256 hash, and support listing and revocation. Keys SHALL expire after a configurable TTL (default: 90 days).

#### Scenario: Generate key
- **WHEN** admin runs `headroom auth create-key joao`
- **THEN** the system generates a random 256-bit token with prefix `hr_`
- **AND** stores the SHA-256 hash in an `:ApiKey` node with `key_prefix` (first 8 chars), `user_id` of "joao", `is_active: true`, `created_at`, and `expires_at` (now + 90 days)
- **AND** displays the full key exactly once with a warning to copy it now

#### Scenario: Generate key with custom TTL
- **WHEN** admin runs `headroom auth create-key joao --ttl-days 30`
- **THEN** the `:ApiKey.expires_at` is set to `created_at + 30 days`

#### Scenario: List keys for a user
- **WHEN** admin runs `headroom auth list-keys --user joao`
- **THEN** the system displays a table with columns: key_id, key_prefix, status (active/expired/revoked), and expires_at for every key owned by "joao"
- **AND** the full key is NEVER displayed

#### Scenario: Revoke key
- **WHEN** admin runs `headroom auth revoke-key k_abc123`
- **THEN** the `:ApiKey` node with `key_id: "k_abc123"` has `is_active` set to `false`
- **AND** the user associated with the key is NOT deactivated

### Requirement: Provider key storage
The system SHALL store provider API keys (Anthropic, OpenAI, Gemini, etc.) encrypted at rest using Fernet symmetric encryption. Provider keys SHALL be validated with a test request before storage. The encryption key SHALL be read from the `HEADROOM_ENCRYPTION_KEY` environment variable.

#### Scenario: Store provider key
- **WHEN** admin runs `headroom auth set-provider-key developer anthropic` and enters a valid key via interactive prompt
- **THEN** the system validates the key with a test request to the provider
- **AND** encrypts the key with Fernet using `HEADROOM_ENCRYPTION_KEY`
- **AND** stores the encrypted value in the `provider_keys` property of the `:Role {name: "developer"}` node
- **AND** confirms "Key anthropic stored for role 'developer' (encrypted)"

#### Scenario: Store key without encryption key set
- **WHEN** admin runs `headroom auth set-provider-key` without `HEADROOM_ENCRYPTION_KEY` set
- **THEN** the system returns an error "HEADROOM_ENCRYPTION_KEY is not set" and exits with non-zero code

#### Scenario: Reject invalid key
- **WHEN** admin runs `headroom auth set-provider-key developer anthropic` with an invalid key
- **THEN** the system returns an error "Error: anthropic API key is invalid" and does NOT store the key

#### Scenario: List provider keys for a role
- **WHEN** admin runs `headroom auth list-provider-keys developer`
- **THEN** the system displays a table of provider names and their configuration status (configured / not configured) for role "developer"
- **AND** decrypted key values are NEVER displayed

#### Scenario: Overwrite existing provider key
- **WHEN** admin runs `headroom auth set-provider-key developer anthropic` for a provider that already has a key configured
- **THEN** the system overwrites the existing encrypted key with the new one
- **AND** confirms "Key anthropic updated for role 'developer' (encrypted)"

### Requirement: Role management
The system SHALL support creating and listing roles. Base roles (admin, team_lead, developer, viewer) SHALL be pre-created by `init-db`.

#### Scenario: List roles
- **WHEN** admin runs `headroom auth list-roles`
- **THEN** the system displays a table with columns: role name and description for all roles

#### Scenario: Create custom role
- **WHEN** admin runs `headroom auth create-role intern --description "Intern with limited access"`
- **THEN** a `:Role` node is created with `name: "intern"` and `description: "Intern with limited access"`

### Requirement: Identity verification
The system SHALL provide a `whoami` command that resolves a proxy API key to its owner. The key SHALL be read via interactive prompt (with echo disabled), NEVER as a command-line argument.

#### Scenario: Resolve valid key
- **WHEN** admin runs `headroom auth whoami` and enters a valid key at the prompt
- **THEN** the system displays username, role, team, and status for the key's owner
- **AND** exits with code 0

#### Scenario: Resolve invalid key
- **WHEN** admin runs `headroom auth whoami` and enters an invalid or revoked key
- **THEN** the system displays "Key not found or revoked" and exits with non-zero code

#### Scenario: Resolve via piped input
- **WHEN** admin runs `echo "hr_a7f3b9c2..." | headroom auth whoami --stdin`
- **THEN** the system reads the key from stdin and displays the resolved identity
- **AND** the key never appears in the process list or shell history

### Requirement: Encryption key generation
The system SHALL provide a `generate-key` command that generates a valid Fernet key for use as `HEADROOM_ENCRYPTION_KEY`.

#### Scenario: Generate encryption key
- **WHEN** admin runs `headroom auth generate-key`
- **THEN** the system outputs a 32-byte base64-encoded Fernet key
- **AND** displays instructions to export it as `HEADROOM_ENCRYPTION_KEY`
