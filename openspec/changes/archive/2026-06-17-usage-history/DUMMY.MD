# PRD 3.1 — Request History: See what each user asked

## The problem it solves

Carlos is the admin of a company that uses the Headroom proxy. Every Monday
he checks the dashboard and sees that João consumed 1.2 million tokens last
week — twice as much as Maria, who works on the same team. Carlos wants to
know **what João was working on** that consumed so much.

Today Carlos has to **guess** search terms and try the semantic search:
`headroom usage search "debug crash" --user joao`. If he guesses wrong, he
finds nothing. He has no way to simply **list** João's requests and see the
story unfold chronologically. It's like having a credit card bill that only
shows the total amount — you can't see which purchases made the bill so high.

The `--history` flag turns the usage command into an **itemized statement**.
One command, no guessing.

## How it works (real flow)

Carlos spots an outlier on the dashboard:

```
$ headroom usage top --by-tokens --last 7d

  rank  username    team        requests   tokens_in
  1     joao        backend     342        1.2M      ← ⚠️ 2× the team average
  2     maria       backend     215        890k
  3     pedro       frontend    128        450k
```

He opens João's history:

```
$ headroom usage user joao --history --last 7d

  João — last 7 days (showing 25 of 342)
  ┌─────────────────────┬──────────────────┬──────────┬────────┬────────────────────────────┐
  │ Timestamp            │ Model            │ Tokens   │ Latency│ Summary                    │
  ├─────────────────────┼──────────────────┼──────────┼────────┼────────────────────────────┤
  │ 2026-06-17 14:32     │ claude-opus-4    │ 8.2k/3.1k│ 4.5s   │ debugging memory leak in   │
  │                     │                  │          │        │ async Python workers...    │
  ├─────────────────────┼──────────────────┼──────────┼────────┼────────────────────────────┤
  │ 2026-06-17 10:15     │ claude-sonnet-4-6│ 1.2k/0.5k│ 1.2s   │ how to implement JWT       │
  │                     │                  │          │        │ refresh token in FastAPI...│
  ├─────────────────────┼──────────────────┼──────────┼────────┼────────────────────────────┤
  │ 2026-06-16 16:45     │ claude-opus-4    │ 5.1k/2.3k│ 3.8s   │ debug: JWT token expiring  │
  │                     │                  │          │        │ before configured expiry...│
  └─────────────────────┴──────────────────┴──────────┴────────┴────────────────────────────┘
```

Carlos sees immediately: João spent the week debugging production crashes,
all on Opus (the expensive model). He schedules a 1:1 to understand if the
bugs are resolved and suggests starting debug sessions on Sonnet first.

## The design decisions (explained)

### Decision 1: Store the request summary alongside the log

**Analogy:** When a restaurant takes your order, they write both the table
number AND what you ordered on the same slip — not in two separate filing
cabinets.

When the proxy logs a request to Neo4j, it already stores who made it,
which model, and how many tokens. Now it also stores the first 500
characters of what the user asked. Everything lives in the same
`(:RequestLog)` node — one query shows the full picture.

**Real example:**
```
(:RequestLog) {
  username: "joao",
  model: "claude-opus-4",
  input_tokens: 8200,
  summary: "debugging memory leak in async Python workers..."
}
```

**Why?** Querying Neo4j for the history is a single Cypher `MATCH` — no
need to call Qdrant, generate embeddings, or guess search terms. It works
even when semantic search is disabled.

**Trade-off:** Summaries are at most 500 characters. If someone asks a
very long question, you only see the beginning. But it's enough to
understand the topic, and the full request is always available in the
proxy logs if deeper investigation is needed.

---

### Decision 2: Show history as a table, not a wall of text

**Analogy:** Your bank statement is a table — date, description, amount —
not a paragraph. You scan it in seconds.

The `--history` output is a Rich table with columns: timestamp, model,
tokens, latency, and summary. Carlos scans 25 rows in a few seconds and
spots patterns immediately.

**Real example:** The table shown in the flow above. Same style as
`headroom usage top` and `headroom auth list-users` — consistent with the
rest of the CLI.

**Why?** A table is scannable. Carlos doesn't need to read every summary —
he can look at the model column and see "Opus, Opus, Opus..." in half a
second. The pattern jumps out visually.

**Trade-off:** Tables don't work well in scripts. A future `--json` flag
can solve that for automated tooling.

---

### Decision 3: Default to 25 entries, let the admin ask for more

**Analogy:** When you check your email inbox, you see the 25 most recent
messages. If you need older ones, you scroll or search.

The `--history` flag shows 25 entries by default. Carlos can ask for up to
100 with `--limit 100`. This keeps the output manageable in the terminal.

**Real example:**
```bash
headroom usage user joao --history --last 7d --limit 50
```

**Why?** Most investigations need only the recent context. Showing 342
entries by default would flood the terminal and be unusable. The limit
gives control without overwhelming.

---

### Decision 4: Reuse existing access control

**Analogy:** The same keycard that opens your office floor opens the
break room — not the CEO's office. Access rules are consistent everywhere.

The `--history` flag reuses the exact same `resolve_scope` and
`enforce_scope` functions that `usage user`, `usage team`, and
`usage search` already use. A developer sees only their own history.
A team lead sees their team. An admin sees everything.

**Real example:**
```
$ headroom usage user maria --history --last 7d
Error: you can only view your own requests. Use --self.
```

**Why?** No new security code to write or audit. The scope system from
PRD 3 already works.

## At a glance

| Decision | In one sentence |
|----------|----------------|
| Summary in Neo4j | Request description lives in the same database row as the token count |
| Table output | A scannable table like a bank statement, not a text wall |
| Default 25 entries | Show the most recent 25, let admin ask for up to 100 |
| Reuse access control | Same rules as the rest of the system — dev sees self, lead sees team, admin sees all |
