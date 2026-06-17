# PRD 3 — Usage Audit & Analytics

## The problem it solves

The proxy already knows **who** is making each request (PRD 2). But that information disappears the moment the request ends. The admin can't answer basic questions like: "how much did the backend team consume this week?", "which model is being used the most?", "what was Alice asking about that burned so many tokens?".

PRD 3 **records everything** — every question, every response, who made it, which model, how many tokens. And it lets you search by similarity: "find requests similar to 'memory leak debugging'".

## How it works (real flow)

### Alice uses the proxy (invisible recording)

```
1. Alice: "claude, explain microservices architecture to me"

2. Proxy authenticates (PRD 2) → sends to Anthropic → response comes back

3. Now TWO things happen IN THE BACKGROUND
   (Alice doesn't wait — her response was already delivered):

   ┌─────────────────────────────────────────────┐
   │  BOX A: Neo4j (structured record)           │
   │  "alice (backend) used claude-sonnet-4-6    │
   │   at 14:32, 3200 tokens in, 1100 out,       │
   │   cache miss, latency 1.2s"                 │
   └─────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────┐
   │  BOX B: Qdrant (smart search)               │
   │  Turns "explain microservices architecture"  │
   │  into a list of 384 numbers (embedding)       │
   │  for similarity search later                 │
   └─────────────────────────────────────────────┘
```

### Admin investigates weekly consumption

```
$ headroom audit summary --last 7d
Total: 12,847 requests | 35.2M tokens in | 11.8M out
Active users: 8 | Active models: 4
Cache hit rate: 12.3% | Average savings: 4.1%

$ headroom audit top --by-tokens --last 7d
1. alice     backend    2,841 reqs    8.2M tokens
2. bob       backend    2,104 reqs    6.1M tokens
3. carlos    frontend   1,893 reqs    5.4M tokens

# Alice consumed a lot — admin investigates what she was asking:
$ headroom audit search "architecture design system" --user alice
3 results (similarity > 0.7):
1. [score 0.94] "explain microservices architecture with Kafka..."
2. [score 0.87] "compare design patterns for distributed systems..."
3. [score 0.72] "best practices for event sourcing..."

# Admin understands: Alice is doing architecture design —
# justifies using the expensive model (Opus)
```

### Developer checks their own usage

```
$ headroom audit user --self --last 7d
Your requests: 342
Tokens: 1.2M in / 380k out
Models: claude-sonnet-4-6 (274), claude-opus-4 (68)
Cache hits: 23 (6.7%)
Average latency: 1.2s
```

---

## The design decisions (explained)

### Decision 1: In-memory queue (don't write directly to the database)

Each request does **not** write directly to Neo4j. It just "drops a slip of paper into a box" (in-memory queue). A background process grabs 50 slips at once and writes them to the database.

**Analogy:** It's like a supermarket checkout. If every customer went to the warehouse to grab their own items, the line would grind to a halt. Instead, products are already up front — the warehouse is restocked in batches overnight.

**Real example:**
```
Alice's request finishes → "slip" drops into the box
Bob's request finishes → "slip" drops into the box
... (48 requests later)
Box reaches 50 slips → writes EVERYTHING to Neo4j at once
   UNWIND $batch CREATE (:RequestLog {...}), (:RequestLog {...}), ...
Done — 50 records in a single database trip
```

**Why?** Writing to Neo4j takes ~5ms. If synchronous, every request from Alice would be 5ms slower. With the queue, Alice gets her response and the recording happens later.

**Trade-off:** If the proxy crashes, we lose at most 50 records (or 5 seconds of data). For an audit system, losing 5 seconds of history in a crash is acceptable — the production database needs ACID, audit can be "eventually consistent."

---

### Decision 2: Two databases — Neo4j for numbers, Qdrant for smart search

Each request generates **two** records:
- **Neo4j**: "alice, 3200 tokens, claude-sonnet-4-6, 14:32" ← for structured queries (SQL-like)
- **Qdrant**: 384 numbers (embedding) representing what she asked ← for similarity search

**Analogy:** It's like a library with two systems:
- **Traditional catalog** (Neo4j): title, author, publisher, year. Exact search: "books by author X in 2025".
- **Subject index** (Qdrant): "show me books similar to this one." If you liked "Pride and Prejudice", it finds "Sense and Sensibility" even without sharing the exact words.

**Real example:**
```
Neo4j: "how many tokens did the backend team spend this week?"
  → exact query: team="backend", timestamp > 7 days ago, SUM(tokens)
  → answer: 35.2M tokens

Qdrant: "find requests similar to 'debugging memory leak'"
  → turns "debugging memory leak" into 384 numbers
  → compares with the 384 numbers of every stored request
  → finds requests about "leak", "allocation", "pointer"
  → even without containing the exact phrase "memory leak"
```

**Why?** Structured queries (totals, rankings, aggregations) are impossible in Qdrant. Semantic search ("similar to X") is impossible in Neo4j. One complements the other.

---

### Decision 3: If Qdrant goes down, Neo4j keeps going

Qdrant is **"nice to have"**. If it's unreachable, Neo4j keeps recording normally. Semantic search becomes unavailable, but all structured queries still work.

**Analogy:** It's like a restaurant that delivers via Uber Eats. If the driver gets a flat tire, the kitchen keeps cooking — you just can't get delivery. You'll have to eat at the restaurant.

**Real example:**
```
Qdrant goes down.

Admin: $ headroom audit user alice --last 7d
→ Works! (queries Neo4j)

Admin: $ headroom audit search "microservices"
→ "Semantic search unavailable — Qdrant is not reachable.
   Structured queries (user, team, top, summary) are still available."

Qdrant comes back. Next request generates an embedding normally.
```

**Why?** It makes no sense to take down the primary feature (number auditing) because of the secondary one (semantic search).

---

### Decision 4: Local embeddings (no paid API call)

Turning text into numbers (embedding) is done **locally**, with a model that runs on the CPU. No external API call.

**Analogy:** It's like having a calculator in your desk drawer instead of calling an accountant every time you need to do math. The calculator is simple, but it works. And it's free.

**Real example:**
```
Alice's request: "debugging memory leak in async Python workers"
       ↓ fastembed (local model, runs on CPU)
Vector: [0.23, -0.45, 0.78, ... 384 numbers]
       ↓ stored in Qdrant

Cost: $0.00 (no API call, no GPU)
Time: ~10ms on local CPU
```

**Why?** If we used OpenAI's API (`text-embedding-3-small`), every single request would cost money and add network latency. fastembed is free and already installed (headroom uses it for another feature).

**Trade-off:** The local embedding quality is lower than OpenAI's. But for semantic search like "what did the team ask about authentication?", the local model is good enough. We're not doing surgical precision search.

---

### Decision 5: Each person sees only what they're allowed to

- **Developer** (Alice): sees only her own requests
- **Team Lead** (Bob): sees his team's requests (backend)
- **Admin** (Carlos): sees everything

**Analogy:** It's like bank access levels:
- Account holder: sees their own account
- Branch manager: sees all accounts at the branch
- Director: sees all branches

**Real example:**
```
# Alice (developer) trying to snoop:
$ headroom audit user bob --last 7d
Error: You can only view your own requests. Use --self.

# Alice viewing her own data:
$ headroom audit user --self --last 7d
Your requests: 342 | Tokens: 1.2M in / 380k out
```

**Why?** Privacy. Alice doesn't need to know what Bob asked. And Bob (team lead) shouldn't see frontend team data.

---

### Decision 6: Redundant data on purpose (denormalization)

Each request record stores `username: "alice"` and `team: "backend"` — even though that info already exists on the `:User` node in Neo4j. It's a **deliberate copy**.

**Analogy:** It's like a restaurant order ticket. Instead of writing "customer #42 ordered steak", the kitchen sticks a post-it with "Alice, table 3, steak". When the waiter delivers, they don't need to look up the customer database.

**Without denormalization (bad — 11 queries):**
```
Query: "top 5 users by tokens"
1. Find the 5 RequestLogs with the most tokens → 5 user_ids
2. For each user_id, ANOTHER query to fetch the username
3. For each user_id, YET ANOTHER query to fetch the team
Total: 1 + 5 + 5 = 11 database trips
```

**With denormalization (good — 1 query):**
```
Query: "top 5 users by tokens"
1. Find the 5 RequestLogs with the most tokens
   → username and team are ALREADY on the record
Total: 1 database trip
```

**Why?** Performance. Audit queries are far more frequent than writes. It's worth spending a bit more storage to make queries instant.

---

### Decision 7: Manual cleanup (for now)

The admin cleans up old data with `headroom audit purge --before 2025-01-01`. There's no automatic age-based cleanup (yet).

**Analogy:** It's like your basement. You store everything there and, once a year, do a spring cleaning. In the future, you might hire a service to clean automatically every 6 months.

**Real example:**
```
$ headroom audit purge --before 2025-01-01
Remove all audit data before 2025-01-01? [y/N] y
Removed: 12,847 records from Neo4j + Qdrant.
```

**Why?** For MVP, the admin decides when to clean. Phase 2 adds configurable TTL ("auto-delete records older than 90 days").

---

## At a glance

| Decision | In one sentence |
|----------|----------------|
| In-memory queue | Recording is async — Alice never waits for the database write |
| Neo4j + Qdrant | Numbers in Neo4j, smart search in Qdrant — each does what it's good at |
| Qdrant "nice to have" | If it goes down, Neo4j keeps going — only semantic search disappears temporarily |
| Local embeddings | No API cost — uses a free model on the CPU |
| Role-scoped views | Developer sees self, team lead sees team, admin sees everything |
| Redundant data | Name and team are copied onto the record — queries don't need to join |
| Manual cleanup | Admin decides when to purge — Phase 2 automates it |
