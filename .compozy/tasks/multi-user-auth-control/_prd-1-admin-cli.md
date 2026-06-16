# PRD 1: Admin CLI & User Management

## Overview

Today the headroom proxy has no concept of users — anyone with a provider API key (Anthropic, OpenAI, Gemini) can use the proxy, without identification or access control. For a team to use the proxy securely, it is necessary to:

- Register **who** the team's developers are
- Issue **credentials** (proxy API keys) for each one
- Store **provider keys** securely in the proxy (not on developer machines)
- Group users into **teams** with **roles** that define what each can do
- Enable immediate **revocation** of access when someone leaves the team

This PRD describes the **administration module** — the tool the admin uses to manage users, teams, roles, proxy API keys, and provider keys.

## Goals

- **Initial setup time**: Admin completes `init-db` + first 3 users in under 5 minutes
- **New dev onboarding**: Admin creates a user and issues a key in under 30 seconds
- **Revocation**: Block a user's access with a single command, with immediate effect
- **Security**: Provider keys are never stored in plaintext in the database
- **Zero regression**: The admin module does not affect the proxy when auth is disabled

## User Stories

### Persona 1: Admin (proxy operator)

- As an admin, I want to **initialize the database** with a single command (`init-db`) to create constraints, indexes, and the initial admin role
- As an admin, I want to **create users** with username and role to register each team developer
- As an admin, I want to **list users** filtered by role, team, and status to audit who has access
- As an admin, I want to **revoke users** (soft-delete) to block access when someone leaves
- As an admin, I want to **create and manage teams** (e.g. "backend", "frontend") to group developers by area
- As an admin, I want to **generate API keys** for any user and view prefixes (without the full key)
- As an admin, I want to **revoke API keys** individually without deactivating the user
- As an admin, I want to **store provider keys** (Anthropic, OpenAI, Gemini, etc.) per role in encrypted form
- As an admin, I want to **list which providers** are configured for each role (without seeing the decrypted value)
- As an admin, I want to **create new roles** with custom names and descriptions

### Persona 2: Team Lead (technical leader)

- As team lead of "backend", I want to **create users** only in my team
- As team lead, I want to **generate and revoke API keys** only for users in my team
- As team lead, I want to **list users in my team** with status and consumption
- As team lead, I **do not want** to create/revoke users in other teams
- As team lead, I **do not want** to manage provider keys (admin only)

### Persona 3: Developer (proxy end user)

- As a developer, I want to **see my own key** (prefix + status) without being able to create or revoke
- As a developer, I want to **list available providers** for my role

## Core Features

### F1 — Database Initialization (`init-db`)

Creates uniqueness constraints in Neo4j (user_id, username, role name, key_hash) and the initial `admin` role. Idempotent — running it again does not break anything. Example:

```
$ headroom auth init-db
Schema initialized: 4 constraints created, role 'admin' ready.
```

### F2 — User CRUD

Create, list, deactivate (soft-delete), and reactivate users. Each user belongs to one role and one team. Example:

```
$ headroom auth create-user joao --role developer --team backend
User created: joao (developer, team backend, id: u_7f3a...)

$ headroom auth list-users
username    role        team        is_active   keys
estrazulas  admin       —           yes         1
joao        developer   backend     yes         0
maria       team_lead   backend     yes         2
pedro       developer   frontend    no          0

$ headroom auth list-users --team backend
(username: joao, maria)

$ headroom auth revoke-user joao
User joao deactivated. 1 key(s) revoked.
```

### F3 — Team CRUD

Create, list, and remove teams. Teams are labels that group users. Example:

```
$ headroom auth create-team backend
Team created: backend

$ headroom auth list-teams
team        members   active_members
backend     2         2
frontend    1         0

$ headroom auth add-user-to-team joao backend
# shortcut, can also be done at create-user time
```

### F4 — Proxy API Key Management (`hr_...`)

Generate keys (random token with `hr_` prefix), list (prefix + status, never the full key), revoke individually (soft-delete), and check expiration. Example:

```
$ headroom auth create-key joao
API key generated (copy now — will not be displayed again):
hr_a7f3b9c2d1e5f8a4b7c3d9e2f6a1b5c8

$ headroom auth list-keys --user joao
key_id      prefix      status    expires_at
k_abc123    hr_a7f3b9   active    2026-09-14 (90 days)

$ headroom auth revoke-key k_abc123
Key hr_a7f3b9 revoked.
```

- Keys expire after 90 days by default (configurable by admin: `--ttl-days N`)
- Key is displayed **once** at creation time; afterwards only the SHA-256 hash exists in the database
- Prefix (8 chars) serves for visual identification — the developer recognizes "my key starts with hr_a7f3b9"

### F5 — Encrypted Provider Key Storage

LLM provider API keys (Anthropic, OpenAI, Gemini, etc.) are stored in the `Role` node, encrypted with Fernet using `HEADROOM_ENCRYPTION_KEY`. Example:

```
$ headroom auth set-provider-key developer anthropic
Enter provider key: [hidden input]
Key anthropic stored for role 'developer' (encrypted).

$ headroom auth list-provider-keys developer
provider      status
anthropic     configured
openai        not configured
gemini        configured
```

- The key never appears in plaintext after storage (only the admin with `HEADROOM_ENCRYPTION_KEY` can decrypt it)
- `list-provider-keys` shows which providers have keys, without revealing values
- Supports multiple providers per role (each role can have Anthropic + OpenAI + Gemini simultaneously)
- `set-provider-key` with an existing provider = overwrites (key rotation)

### F6 — Role Management

Create, list, and remove roles. Each role defines a set of permissions and limits inherited by its members. Example:

```
$ headroom auth create-role developer --description "Dev with access to all providers"
Role created: developer

$ headroom auth create-role intern --description "Intern, limited access"
Role created: intern

$ headroom auth list-roles
role          description
admin         Full access — manages users, roles, providers
team_lead     Manages users in their team
developer     Uses the proxy with configured providers
viewer        Read-only access to own data (whoami, list-keys --self)
```

The 4 base roles (admin, team_lead, developer, viewer) are created by `init-db`. Additional roles can be created by the admin.

### F7 — Identity Verification

Quick command to verify which user a key belongs to (useful for debugging). The key is read via interactive prompt, never as a CLI argument:

```
$ headroom auth whoami
Enter proxy key: ****
Username: joao
Role: developer
Team: backend
Status: active
```

## User Experience

### Primary Flow: Initial Setup (admin, first time)

```
1. docker compose up -d                    # Neo4j + Qdrant already running
2. export HEADROOM_ENCRYPTION_KEY=$(headroom auth generate-key)
   # or: openssl rand -base64 32
3. headroom auth init-db
   → Constraints + 4 base roles + "default" team
4. headroom auth create-user estrazulas --role admin --team default
5. headroom auth create-key estrazulas
   → Copy hr_xxx...
6. headroom auth set-provider-key developer anthropic
   → Paste sk-ant-api03-xxx...
7. headroom auth set-provider-key developer openai
   → Paste sk-proj-xxx...
```

### Daily Flow: New Developer Onboarding

```
1. headroom auth create-user joao --role developer --team backend
2. headroom auth create-key joao
   → Deliver hr_xxx... to João (Signal, 1Password, etc.)
3. João configures: HEADROOM_BASE_URL=http://proxy:8787
4. João uses Claude Code / Cursor normally
```

### Incident Flow: Developer Leaves the Team

```
1. headroom auth revoke-user joao
   → "User joao deactivated. 1 key(s) revoked."
2. Immediate effect — João's next request returns 401
3. Audit trail remains accessible (João's history is preserved)
```

### Error Feedback

- Commands that require `HEADROOM_ENCRYPTION_KEY` display a clear error if not set:
  ```
  Error: HEADROOM_ENCRYPTION_KEY is not set.
  Generate one with: headroom auth generate-key
  ```
- Attempt to create a duplicate user: `Error: username 'joao' already exists`
- Expired key: CLI shows `expired` in `list-keys` and middleware returns 401

## High-Level Technical Constraints

- **Storage**: Neo4j (already present in docker-compose.yml for memory)
- **Encryption**: Fernet (symmetric encryption, Python stdlib via `cryptography`)
- **Interface**: Click CLI (same framework as `headroom proxy` and `headroom wrap`)
- **Non-regression**: All `headroom auth` commands work with the proxy stopped (CLI talks directly to Neo4j)
- **Secrets**: Provider keys never in positional arguments — always stdin or interactive prompt

## Non-Goals (Out of Scope)

- **Web UI** — no graphical admin interface (ADR-001)
- **REST API** — no HTTP endpoints for user management (ADR-001)
- **SSO / OIDC / LDAP** — no external identity provider integration (MVP)
- **SCIM provisioning** — no automatic user provisioning
- **Notifications** — no alerts for expiring keys or blown budgets
- **Billing / chargeback** — no per-user cost tracking (deferred to PRD 3)
- **Automatic key rotation** — keys are rotated manually via `set-provider-key`
- **Per-team provider segregation** — provider keys are per role, not per team

## Phased Rollout Plan

### MVP (Phase 1) — PRD 1

- Commands: `init-db`, `create-user`, `list-users`, `revoke-user`
- Commands: `create-key`, `list-keys`, `revoke-key`
- Commands: `set-provider-key`, `list-provider-keys`
- Commands: `create-role`, `list-roles`
- Commands: `create-team`, `add-user-to-team`
- Command: `whoami` for identity verification
- Command: `generate-key` to generate `HEADROOM_ENCRYPTION_KEY`
- Command: `reactivate-user` to reactivate a deactivated user
- Keys expire after 90 days (default)
- 4 base roles: admin, team_lead, developer, viewer

### Phase 2 (post-MVP)

- Customizable TTL per key at creation time (`--ttl-days`)
- Command: `rotate-key` to renew an expired key (same user, new key)

### Phase 3 (long term)

- Custom roles with granular permissions (e.g. "can only use Anthropic, not OpenAI")
- Per-role rate/token limits configurable via CLI (`--rpm`, `--tpm`)
- Admin action history (`:AdminAction` in Neo4j — who created/revoked whom, when)

## Success Metrics

| Metric | Target |
|--------|--------|
| Initial setup time (init-db + 3 users) | < 5 minutes |
| Onboarding time (create-user + create-key) | < 30 seconds |
| Revocation time (revoke-user to effect) | Immediate (next request) |
| Usage errors (failed commands due to poor UX) | < 5% of executions |
| Security | 0 provider keys in plaintext in the database |

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| **Admin loses `HEADROOM_ENCRYPTION_KEY`** | Document key backup; `generate-key` displays the key once with an explicit warning |
| **Key leaks into shell history** | Sensitive commands use interactive prompt (`getpass`), never `--api-key` as an argument |
| **CLI depends on direct Neo4j access** | Document that the CLI needs network connectivity to Neo4j (localhost in docker-compose, or VPN) |
| **Admin forgets to set HEADROOM_ENCRYPTION_KEY** | Explicit error; `generate-key` displays `export` instructions |
| **Large team (100+ devs) — slow CLI** | `list-users` with pagination (`--limit`, `--offset`); large lists truncated with `--json` for scripting |

## Architecture Decision Records

- [ADR-001: Pure Admin CLI](adrs/adr-001.md) — CLI as the sole administration interface, no REST API or Web UI in MVP

## Open Questions

- ~~What CLI commands should the `viewer` role have access to?~~ **Resolved**: viewer only accesses own data: `whoami` and `list-keys --self`. Cannot see other users.
- ~~Should `init-db` ask for confirmation before dropping/re-initializing existing schema?~~ **Resolved**: Yes. `init-db` is idempotent (does not drop anything), but asks for confirmation if an existing schema is detected: "Auth schema already initialized. Re-run init-db to verify constraints? [y/N]".
- ~~Should provider keys be validated at `set-provider-key` time (with a test request to the provider)?~~ **Resolved**: Yes. `set-provider-key` makes a test request to the provider (e.g. `GET https://api.anthropic.com/v1/messages` with the key) before encrypting and storing. If the key is invalid, it returns an immediate error: "Error: anthropic API key is invalid or has insufficient permissions."
- Should there be a `headroom auth backup` command to export user/role data (without encrypted keys)? (deferred to Phase 2)
