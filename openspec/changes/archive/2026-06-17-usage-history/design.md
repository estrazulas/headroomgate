## Context

Today `headroom usage user <name>` shows aggregate statistics (total requests, tokens, models). When an admin spots a high-consumption user, they must guess search terms for `usage search` to discover what the user was working on. The request summaries are already stored in Neo4j (`:RequestLog` nodes have a `summary` property) but there is no CLI path to list them directly.

The `--history` flag fills this gap with a simple Cypher query — no new infrastructure needed.

## Goals / Non-Goals

**Goals:**
- Add `--history` flag to `headroom usage user <username>` showing request details in reverse chronological order
- Each entry shows: timestamp, model, tokens (in/out), latency, and first 120 chars of summary
- Default limit of 25 entries, configurable with `--limit N`

**Non-Goals:**
- Full-text search (use `usage search` for semantic queries)
- Pagination / cursor-based scrolling (MVP)
- Export to CSV/JSON (Phase 2)
- Filtering by model or date within history (use `--last` flag already available)

## Decisions

### Decision 1: Store summary in Neo4j, query directly

**Choice:** Add `summary` field to the existing `(:RequestLog)` node during buffer flush, and query it with a simple Cypher `MATCH ... RETURN ... ORDER BY r.timestamp DESC LIMIT N`.

**Alternatives considered:**
- **Query Qdrant for history**: Adds latency (network round-trip), Qdrant may be disabled (`--no-audit-semantic`), and requires embedding the "query" string just to list entries. Rejected — simpler to use Neo4j.
- **Add separate `:RequestSummary` nodes**: Unnecessary — the summary is small (≤500 chars) and belongs with the request log. Rejected — adds complexity without benefit.

### Decision 2: Rich table output

**Choice:** Use a Rich `Table` with columns: timestamp, model, tokens, and truncated summary. Match the existing `usage user` output style.

**Alternatives considered:**
- **Plain text lines**: Harder to scan visually. Rejected.
- **JSON output with `--json` flag**: Useful for scripting, but keep as future addition. Rejected for MVP.

### Decision 3: Enforce access scope

**Choice:** Reuse the existing `resolve_scope` + `enforce_scope` from `headroom/usage/access.py`. A developer running `--history` sees only their own requests; a team lead sees their team; admin sees all.

No alternative needed — this is the established pattern.

## Risks / Trade-offs

- **Large result sets**: A heavy user may have 500+ requests/week. `--limit` defaults to 25 and maxes at 100. → Acceptable for MVP.
- **Summary quality**: Summaries are first 500 chars of the user message. Some may be truncated or uninformative. → The timestamp + model + token count still provides investigative value.

## Open Questions

- Should `--history` and `--by-day`/`--by-model` be mutually exclusive? Proposed: yes — `--history` replaces aggregate view.
