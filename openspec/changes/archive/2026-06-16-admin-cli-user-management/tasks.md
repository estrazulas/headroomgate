## 1. Package and data models

- [x] 1.1 Create `headroom/auth/__init__.py` package with lazy imports for store and crypto
- [x] 1.2 Create `headroom/auth/models.py` with dataclasses: `User`, `Role`, `Team`, `ApiKey` (fields per spec auth-store)
- [x] 1.3 Create `headroom/auth/crypto.py` with `FernetCrypto` class: `encrypt()`, `decrypt()`, `validate_key()`, `generate_key()` (per spec auth-crypto)
- [x] 1.4 Add `cryptography` to `pyproject.toml` optional dependencies `[auth]` if not already present

## 2. Neo4j schema and store

- [x] 2.1 Create `headroom/auth/store.py` with `Neo4jAuthStore.__init__()` connecting via `GraphDatabase.driver` (reuse pattern from `direct_mem0.py`)
- [x] 2.2 Implement `init_db()` — creates uniqueness constraints for `User.user_id`, `User.username`, `Role.name`, `ApiKey.key_hash` (idempotent)
- [x] 2.3 Implement `init_db()` role creation — 4 base roles: admin, team_lead, developer, viewer
- [x] 2.4 Implement `create_user()`, `get_user()`, `list_users()`, `update_user_status()` with Cypher MERGE/MATCH
- [x] 2.5 Implement `create_team()`, `list_teams()`, `add_user_to_team()` with `:Team` nodes
- [x] 2.6 Implement `create_key()` — generate `hr_<random>`, SHA-256 hash, store `:ApiKey` node with TTL
- [x] 2.7 Implement `list_keys()`, `revoke_key()`, `get_key_owner()` — key lookup by hash
- [x] 2.8 Implement `set_provider_key()` — encrypt via Fernet, store in `Role.provider_keys` JSON
- [x] 2.9 Implement `list_provider_keys()` — show configured providers without decrypted values
- [x] 2.10 Implement `create_role()`, `list_roles()`
- [x] 2.11 Implement `close()` — close Neo4j driver

## 3. CLI commands

- [x] 3.1 Create `headroom/cli/auth.py` with Click group `headroom auth`
- [x] 3.2 Register auth group in `headroom/cli/main.py`
- [x] 3.3 Implement `init-db` command — calls `Neo4jAuthStore.init_db()`
- [x] 3.4 Implement `create-user`, `list-users`, `revoke-user`, `reactivate-user` commands
- [x] 3.5 Implement `create-team`, `list-teams`, `add-user-to-team` commands
- [x] 3.6 Implement `create-key`, `list-keys`, `revoke-key` commands (key displayed once via click.echo)
- [x] 3.7 Implement `set-provider-key` — interactive prompt via `click.prompt(hide_input=True)` or `--stdin` flag
- [x] 3.8 Implement `list-provider-keys`, `create-role`, `list-roles` commands
- [x] 3.9 Implement `whoami` command — resolve key to user identity (key via prompt, never --key)
- [x] 3.10 Implement `generate-key` command — output Fernet key with export instructions
- [x] 3.11 Add `--json` flag to all list commands for machine-readable output
- [x] 3.12 Add `--as-user` / `HEADROOM_AUTH_USER` env var for role-based access control in CLI
- [x] 3.13 Enforce role-based restrictions: team_lead scoped to own team, developer read-only

## 4. Error handling and UX

- [x] 4.1 Connection error message with URI, user, and troubleshooting hint when Neo4j unreachable
- [x] 4.2 Missing `HEADROOM_ENCRYPTION_KEY` error with `generate-key` hint
- [x] 4.3 Duplicate username/role/team errors with suggestion to use list command
- [x] 4.4 English error messages consistent with existing headroom CLI style (language decision: English for all CLI output per openspec/config.yaml)
- [x] 4.5 Confirmation messages after create/revoke operations with entity details

## 5. Tests

- [x] 5.1 Unit tests for `auth/models.py` — dataclass validation, defaults
- [x] 5.2 Unit tests for `auth/crypto.py` — encrypt/decrypt roundtrip, wrong key, corrupted token, validate_key
- [x] 5.3 Integration tests for `auth/store.py` — init_db idempotency, CRUD for users/roles/teams/keys against test Neo4j
- [x] 5.4 Integration tests for `headroom/cli/auth.py` — Click test runner for all 15+ subcommands
- [x] 5.5 Test: `init-db` idempotency (run twice, verify no duplicates)
- [x] 5.6 Test: soft-delete — revoked user's keys are also revoked
- [x] 5.7 Test: provider key roundtrip — store then verify can decrypt with correct key
- [x] 5.8 Test: role-based access — team_lead cannot manage other teams, developer cannot create users
