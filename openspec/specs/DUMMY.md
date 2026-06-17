# PRD 1 — Admin CLI & User Management

## The problem it solves

Today the headroom proxy has no concept of users — anyone with a provider API key (Anthropic, OpenAI, Gemini) can use the proxy, without identification or access control. It's like an office building with no front desk: whoever walks in, walks in.

PRD 1 creates the **front desk** — the admin registers developers, hands out badges (`hr_...` keys), and stores provider keys in a vault (encrypted database). When someone leaves, their badge is revoked with a single command.

## How it works (real flow)

### First-time setup (admin, day one)

```
1. docker compose up -d                          # Neo4j already running
2. export HEADROOM_ENCRYPTION_KEY=$(headroom auth generate-key)
   # Generates the "master key" that protects all provider keys
3. headroom auth init-db
   # Creates database structure: 4 base roles (admin, team_lead, developer, viewer)
4. headroom auth create-user carlos --role admin
   # Registers the first admin
5. headroom auth create-key carlos
   # Generates badge: hr_a7f3b9c2d1e5...
   # ⚠️ This key is shown ONCE — copy it now
```

### Onboarding a new developer (daily flow)

```
1. Bob (team lead) registers the new hire:
   $ headroom auth create-user alice --role developer --team backend
   User created: alice (developer, backend team)

2. Bob generates Alice's key:
   $ headroom auth create-key alice
   Key generated: hr_x1y2z3w4... ← send to Alice on Signal

3. Bob registers provider keys (once per role):
   $ headroom auth set-provider-key developer anthropic
   Enter provider key: ****  ← paste sk-ant-api03-xxx

4. Alice configures Claude Code:
   HEADROOM_BASE_URL=http://proxy:8787
   API key = hr_x1y2z3w4...
   Done! Alice uses the proxy normally.
```

### Someone leaves the team (emergency flow)

```
$ headroom auth revoke-user alice
User alice deactivated. 1 key(s) revoked.
# Immediate effect — Alice's next request returns "access denied"
```

---

## The design decisions (explained)

### Decision 1: Everything via command line (CLI), no website or API

The admin does everything through the terminal — just like `headroom proxy` and `headroom wrap`. No fancy dashboard, no web admin panel.

**Analogy:** It's like managing a Linux server — you use SSH and terminal commands. There's no graphical control panel. Headroom admins are developers, they're comfortable in the terminal.

**Why?** Building a web admin would take 3x longer (frontend + API + auth). The terminal works over SSH, doesn't expose a new port, and reuses everything headroom already has.

**Trade-off:** The admin needs SSH access to the machine. Can't manage from a phone.

---

### Decision 2: Neo4j as the database

User, team, role, and key data lives in Neo4j — the same database headroom already uses for conversation memory.

**Analogy:** Instead of renting a new warehouse, we use an empty room in the existing building. Neo4j is already in docker-compose, already backed up, already monitored.

**Real example:** When the admin runs `headroom auth create-user alice --role developer`, it creates a `(:User {username: "alice", role: "developer"})` node in Neo4j.

**Why?** Zero new infrastructure. Neo4j is already there. And it's great at relationship queries — "which keys does Alice have?", "how many devs in the backend team?".

---

### Decision 3: Fernet encryption for provider keys

Provider keys (Anthropic, OpenAI, Gemini) are stored **scrambled** in the database. If someone steals the database, they can't read the keys without the "master key."

**Analogy:** It's like a single-key safe. You store all the company car keys in the safe. The safe door has a single lock. The key to that lock is `HEADROOM_ENCRYPTION_KEY`. Without it, all you see are locked drawers — even if you break down the room door.

**Real example:**
```
Database (Neo4j):
  Role "developer" → provider_keys: "gAAAAAB..." ← this is the real key, but scrambled

Only the proxy (which has HEADROOM_ENCRYPTION_KEY) can read it:
  Fernet.decrypt("gAAAAAB...") → "sk-ant-api03-xxx" ← real key
```

**Trade-off:** If the admin **loses** `HEADROOM_ENCRYPTION_KEY`, all provider keys are gone. Everything must be re-registered. That's why the `generate-key` command shows the key once and tells you to store it somewhere safe.

---

### Decision 4: SHA-256 hash for access keys (never store the real key)

When the admin generates an `hr_...` key for Alice, the real key is **never stored** in the database. Only a "fingerprint" (SHA-256 hash) of it is kept.

**Analogy:** It's like a hotel that doesn't keep your physical room key — it only keeps a mold of the lock. When the guest inserts the key, the mold matches. But if someone steals the mold, they can't make a new key from it.

**Real example:**
```
Key generated: hr_a7f3b9c2d1e5f8a4b7c3d9e2f6a1b5c8  ← shown ONCE
Hash stored:   9f86d081884c7d659a2feaa0c55ad015...  ← SHA-256, irreversible

When Alice makes a request with hr_a7f3b9...:
  SHA-256("hr_a7f3b9...") → 9f86d081...
  Database: "does anyone have hash 9f86d081...?" → "Yes, Alice, developer, active"
```

**Why?** If the database leaks, the attacker can't use the keys. SHA-256 is irreversible — there's no way to turn `9f86d081...` back into `hr_a7f3b9...`.

---

### Decision 5: UUID identifiers (user_id, key_id)

Every user and key has a unique, immutable identifier (e.g., `u_7f3a...`, `k_abc123...`), separate from the human-readable name.

**Analogy:** It's like a social security number vs a name. Two people can be named "Alice Smith", but each has a unique SSN. In the system, the `username` can change (marriage, typo fix), but the `user_id` is forever.

**Real example:** If Alice changes her username to `alice.johnson`, all her keys and audit records remain linked to `user_id: "u_7f3a..."` — nothing breaks.

**Why?** Data integrity. The username is a "nickname" that can change. The `user_id` is the real identity.

---

### Decision 6: Soft-delete (deactivate instead of erase)

When the admin "removes" a user, they're not deleted from the database — they just get flagged `is_active: false`. All their keys are automatically deactivated too.

**Analogy:** It's like canceling a credit card. The bank doesn't destroy your transaction history — it just blocks the card. Your past purchases remain on record for auditing.

**Real example:**
```
$ headroom auth revoke-user alice
User alice deactivated. 1 key(s) revoked.

In the database:
  (:User {username: "alice", is_active: false})     ← not deleted
  (:ApiKey {key_prefix: "hr_x1y2z3", is_active: false})  ← blocked

If the admin changes their mind:
  $ headroom auth reactivate-user alice
  User alice reactivated.
```

**Why?** Audit history (PRD 3) keeps working. You can see what Alice did before she left. And if her departure was a mistake, just reactivate.

---

### Decision 7: Four roles with fixed permissions

The system comes with 4 ready-made roles:
- **admin**: full access — manages users, teams, keys, providers
- **team_lead**: manages only their team — creates users, generates keys, views consumption
- **developer**: uses the proxy — only sees their own data (`whoami`, `list-keys --self`)
- **viewer**: read-only access to their own data — can't create anything

**Analogy:** It's like access levels at a bank:
- Director (admin): opens any account, views any statement
- Branch manager (team_lead): manages their own branch
- Customer (developer): sees their own account, makes transactions
- Intern (viewer): consult only

**Real example:**
```
# Team lead of "backend" tries to create a user in another team:
$ headroom auth create-user diana --role developer --team frontend
Error: you can only create users in your team (backend).

# Developer tries to list all users:
$ headroom auth list-users
Error: you can only view your own data. Use --self.
```

**Why?** Each role has a clear scope of responsibility. The admin doesn't worry about team leads messing where they shouldn't.

---

### Decision 8: Provider keys per role (not per user)

Provider keys (Anthropic, OpenAI) are configured **on the role**, not on each user. All "developer" users share the same Anthropic key.

**Analogy:** It's like a corporate phone plan. The company has one account with the carrier. All employees use the same plan. Nobody gets an individual SIM.

**Real example:**
```
$ headroom auth set-provider-key developer anthropic
Enter provider key: ****
# All 50 developers now use this same key

# The admin doesn't repeat this 50 times
```

**Why?** Practicality. Small/medium teams share an API key. If per-user keys are ever needed, that's a future evolution.

---

### Decision 9: Secrets never as command arguments

Commands that handle keys or passwords **never** take the value as a CLI argument — they use interactive prompts (typed blind) or files.

**Analogy:** You don't shout your bank password across the branch. You type it on the keypad, hidden.

**What NOT to do:**
```
$ headroom auth set-provider-key developer anthropic --key sk-ant-api03-xxx
# ⚠️ This would leave the key in shell history!
```

**What to DO:**
```
$ headroom auth set-provider-key developer anthropic
Enter provider key: ****     ← typed blind, nothing on screen
Key stored (encrypted).
```

**Why?** Basic security. Shell history (`~/.bash_history`) is plain text. Any key that appears there is compromised.

---

### Decision 10: Keys expire in 90 days

Every `hr_...` key has an expiration date. The default is 90 days. After that, the proxy rejects it with "key expired."

**Analogy:** It's like a password that expires every 3 months and you have to renew it. It's not malice — it limits the damage if a key leaks.

**Real example:**
```
$ headroom auth create-key alice --ttl-days 90
Key generated: hr_a7f3b9... (valid until 2026-09-14)

# 91 days later, Alice tries to use it:
HTTP 401 | {"error": "api_key_expired", "message": "Your key has expired."}

# Bob (team lead) renews:
$ headroom auth create-key alice --ttl-days 90
New key: hr_x1y2z3w4... ← hands it to Alice
```

**Why?** If a key leaks and nobody notices, it stops working on its own after 90 days. No need for the admin to remember to revoke it.

---

## At a glance

| Decision | In one sentence |
|----------|----------------|
| CLI only | Everything via terminal commands — no website, no API |
| Neo4j | Uses the database already in docker-compose |
| Fernet | Provider keys scrambled — only the "master key" can read them |
| SHA-256 hash | Real key never stored — only an irreversible fingerprint |
| UUID | Each user has an internal SSN — name can change, ID can't |
| Soft-delete | Deactivate instead of erasing — history stays for auditing |
| 4 roles | admin (everything), team_lead (team), developer (proxy), viewer (read-only) |
| Keys per role | 50 devs share one Anthropic key — configured once |
| Blind prompts | Passwords and keys never appear on screen or in shell history |
| 90-day expiry | Leaked key stops working on its own — no need for admin to remember |
