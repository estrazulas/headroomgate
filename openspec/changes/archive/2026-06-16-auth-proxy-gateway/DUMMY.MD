# PRD 2 — Authenticated Proxy Gateway

## The problem it solves

PRD 1 registered users and generated badges (`hr_...` keys). But there's no **security guard** at the door — the proxy accepts every request, badge or not. It's like having an HR list of employees but no one checking IDs at the entrance.

PRD 2 puts a guard at the door: every incoming request gets its badge checked. If valid, the guard lets them through AND **swaps their employee badge for the real provider key** automatically. The developer never even sees the Anthropic key — they use their headroom badge and the proxy handles the rest.

## How it works (real flow)

### Alice uses Claude Code (without knowing any of this)

```
1. Alice configures Claude Code:
   HEADROOM_BASE_URL=http://proxy:8787
   API key = hr_a7f3b9c2d1e5...  ← badge that Carlos (team lead) gave her

2. Alice types: "claude, explain this code to me"

3. What happens UNDER THE HOOD:

   Claude Code → POST /v1/messages
   Authorization: Bearer hr_a7f3b9c2d1e5...

   ┌─────────────────────────────────────────────────┐
   │  GUARD (auth middleware)                        │
   │  ✓ Badge valid? SHA-256("hr_a7f3...") → Alice  │
   │  ✓ Alice active? Yes                            │
   │  ✓ Rate limit? 42/60 requests remaining         │
   │  ✓ Path /v1/messages → provider "anthropic"     │
   └─────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────┐
   │  WAITER (provider injection)                    │
   │  Swaps Bearer hr_a7f3... → Bearer sk-ant-api03- │
   └─────────────────────────────────────────────────┘

   Proxy → Anthropic: POST /v1/messages
   Authorization: Bearer sk-ant-api03-xxx  ← real key

4. Response comes back to Alice normally.
   Extra headers: X-RateLimit-Remaining: 41

   Alice never noticed the key swap happened.
```

### Error flow: expired key

```
Alice makes a request → 401 Unauthorized
{"error": "api_key_expired",
 "message": "Your key has expired. Contact your team lead to renew."}

Alice tells Carlos → Carlos generates a new key:
$ headroom auth create-key alice --ttl-days 90
New key: hr_x1y2z3w4...

Alice updates Claude Code and continues.
```

---

## The design decisions (explained)

### Decision 1: Middleware as a separate plugin (not in proxy core)

Authentication is an **external module** (`plugins/headroom-auth/`), not baked into the proxy. It only activates when the admin enables it with `--proxy-extension headroom-auth`.

**Analogy:** It's like a metal detector at a shopping mall entrance. The mall works without it — all stores operate normally. But when it's on, everyone goes through screening. If it breaks, turn it off and the mall keeps running.

**Real example:**
```
# Proxy WITHOUT auth (original behavior):
$ headroom proxy --port 8787
# Any request goes through — same as always

# Proxy WITH auth:
$ headroom proxy --port 8787 --proxy-extension headroom-auth
# Every request goes through the guard first
```

**Why?** Zero risk. If auth has a problem, remove `--proxy-extension` and the proxy reverts to normal. Zero lines of the original proxy code were changed.

**Trade-off:** 6 extra files to maintain. But the isolation is worth it.

---

### Decision 2: 10-second cache (don't query the database every request)

When the guard checks a badge, they **remember** the result for 10 seconds. If the same badge shows up again within that window, no database query is needed.

**Analogy:** It's like the building security guard who already knows you. You show your badge once. The next few times you walk by that hour, they just nod — no need to check the employee list again.

**Real example:**
```
Request 1 (14:32:00): hr_a7f3b9... → query Neo4j → "Alice, developer, active"
                      Store in cache: hash_a7f3 → (Alice, developer, keys...)

Request 2 (14:32:03): hr_a7f3b9... → cache hit (3 seconds) → NO Neo4j query
                      Instant response (0.2ms)

Request 3 (14:32:12): hr_a7f3b9... → cache expired (12 seconds) → query Neo4j
                      Refresh cache with fresh result
```

**Why?** Without cache, every request would hit Neo4j (~5ms). With cache, 95%+ of requests go straight through (0.2ms). Alice feels zero latency.

**Trade-off:** If the admin **revokes** Alice's key, she can still get through for up to 10 seconds (until cache expires). This 10s window is acceptable for MVP — nobody is going to exploit your system in 10 seconds.

---

### Decision 3: If the database goes down, stale cache saves the day

When Neo4j is unreachable, the proxy doesn't stop. It keeps accepting requests **with expired cache entries** until the database comes back.

**Analogy:** It's like a security guard whose radio broke but still lets familiar faces through — "I remember you, go ahead." If a complete stranger shows up (empty cache), they're told to wait.

**Real example:**
```
Neo4j goes down (14:35)

Alice's request: cache HAS entry (stale) → "OK, let her through"
Bob's request:   cache HAS entry (stale) → "OK, let him through"
Diana's request: cache EMPTY (first time today) → 503 "service unavailable"

Neo4j comes back (14:36)

Diana's next request → normal query, cache updates, business as usual
```

---

### Decision 4: Individual turnstile per user (rate limiting)

Each user has their own "quota" of requests per minute. If Alice makes 60 requests in 1 minute, her quota runs out — but Bob keeps going normally. The quota is inherited from the role: developer = 60/min, team_lead = 120/min.

**Analogy:** It's like subway turnstiles. Each person has their own ticket. If Alice uses up all her rides, Bob is not affected — he has his own ticket.

**Real example:**
```
Alice (developer, 60 RPM):
  Request #60 → X-RateLimit-Remaining: 0
  Request #61 → 429 Too Many Requests | Retry-After: 23s

Bob (developer, 60 RPM):
  Request #30 → X-RateLimit-Remaining: 29  ← independent bucket!
```

**Why?** One dev running a test loop shouldn't take down the proxy for everyone else. Each person has their own bucket. The bucket is "leaky" — it refills on its own over time, so if Alice pauses for a few seconds, her quota starts coming back.

---

### Decision 5: Automatic key swap (provider injection)

The developer **never sees the real Anthropic key**. They use their `hr_...` badge and the proxy swaps it for the real key before forwarding to the provider. The swap is based on the **request path**: `/v1/messages` → Anthropic, `/v1/chat/completions` → OpenAI.

**Analogy:** It's like a waiter at a fancy restaurant. You don't go into the kitchen to place your order — you tell the waiter. They write it down, go to the kitchen, and hand the real ticket to the chef. You never even see the kitchen.

**Real example:**
```
Claude Code sends:
  POST /v1/messages
  Authorization: Bearer hr_a7f3b9...

Proxy detects "/v1/messages" → provider "anthropic"
Proxy opens the vault: role "developer" → anthropic_key (encrypted)
Proxy decrypts with HEADROOM_ENCRYPTION_KEY → "sk-ant-api03-xxx"

Proxy forwards:
  POST https://api.anthropic.com/v1/messages
  Authorization: Bearer sk-ant-api03-xxx
```

**Why?** Security. The real key never leaves the proxy. If Alice's laptop is stolen, the attacker finds no provider keys — only the `hr_...` badge, which can be revoked with a single command.

---

### Decision 6: Identity wristband (contextvars)

After the guard lets someone through, they put a **temporary wristband** on the request. Any downstream system (audit, metrics, logs) can read "this request is from Alice, developer, backend team."

**Analogy:** It's like the wristband at a hospital. At reception, they check your ID and put a wristband on you. After that, any nurse or doctor looks at your wristband and knows who you are — no need to ask for ID again.

**Real example:**
```python
# In the auth middleware:
set_current_identity("u_alice", "alice", "developer", "backend")

# Later, in the audit logger:
user = get_current_user()     # "u_alice"
role = get_current_role()     # "developer"
team = get_current_team()     # "backend"
```

**Why?** Each module (audit, metrics, rate limiting) doesn't need to query the database again. The identity is already in the request context — instant read.

---

### Decision 7: Service door with no badge check

Endpoints `/livez`, `/readyz`, `/health`, `/metrics` **never** require a badge. They're used by Kubernetes to check if the proxy is alive, and by Prometheus to collect metrics.

**Analogy:** It's like the service entrance of a building. Employees come through the front door (with badges). But the fire inspector, the electric meter reader, and the garbage collector use the service entrance — it makes no sense to badge-check them.

**Real example:**
```
Kubernetes:  GET /livez → 200 OK  ← no Authorization header, no problem
Prometheus:  GET /metrics → 200 OK ← no Authorization header, no problem
Developer:   POST /v1/messages → 401 "where's your badge?" ← blocked
```

---

### Decision 8: Bad config = proxy refuses to start

If `HEADROOM_ENCRYPTION_KEY` is missing or wrong, the proxy **refuses to start**. It shows the error immediately — no limping along with a broken leg.

**Analogy:** It's like a car that won't start if the parking brake is engaged. Better to not move at all than to drive two blocks and discover you can't stop.

**Real example:**
```
$ headroom proxy --proxy-extension headroom-auth
Error: headroom-auth: HEADROOM_ENCRYPTION_KEY is invalid or not set.
Generate one with: headroom auth generate-key
# Proxy does NOT start — clear message on what to fix
```

**Why?** If it started with a bad key, every single request from Alice would fail with 502 ("can't decrypt the provider key"). Breaking at startup is better than 500 broken requests later.

---

## At a glance

| Decision | In one sentence |
|----------|----------------|
| Separate plugin | Auth is an external module — if it breaks, turn it off and the proxy keeps going |
| 10-second cache | Remember the badge for 10s — 95% of requests skip the database |
| Stale cache fallback | Database down? Let familiar faces through anyway |
| Individual turnstile | Each dev has their own quota — one person's burst doesn't hurt others |
| Automatic key swap | Dev uses hr_... badge — proxy swaps for the real provider key |
| Identity wristband | Identity stays on the request — audit and metrics read it without querying the DB |
| Service door | Health checks and metrics never require a badge |
| Refuse to start broken | Bad encryption key? Proxy won't even boot — clear error upfront |
