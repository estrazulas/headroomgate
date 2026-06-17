## Why

The `headroom usage user <name>` command today returns only aggregate statistics
(total requests, tokens, models used). When an admin or team lead spots an
outlier — a developer consuming 2× more tokens than the team average — they must
guess what the developer was working on and craft a semantic search query
(`"debug crash error"`) to find the relevant sessions. Guessing is slow,
error-prone, and misses context.

The `--history` flag closes this investigation loop: with one command the admin
sees the **chronological list** of what a user asked, when, with which model,
and how many tokens each request consumed — no guessing required.

## What Changes

- Add `--history` flag to `headroom usage user <username>` command
- When `--history` is present, show request summaries in reverse chronological
  order (most recent first) instead of aggregate statistics
- Each history entry shows: timestamp, model, input/output tokens, latency,
  and the first 120 characters of the request summary
- Default limit of 25 entries; configurable with `--limit N`

## Capabilities

### New Capabilities

### Modified Capabilities

- `usage-cli`: `headroom usage user` gains `--history` and `--limit` flags
- `usage-logging`: store request summaries in Neo4j `:RequestLog` nodes for
  direct retrieval without requiring semantic search

## Impact

- `headroom/cli/usage.py` — new `--history`/`--limit` flags on `usage_user` command
- `headroom/usage/store.py` — new `get_user_history()` method
- `headroom/audit/buffer.py` — include summary text in batch flush (already stored)
- No breaking changes: `usage user <name> --last 7d` continues to show aggregates

## Non-goals

- Full-text search over request history (use `usage search` for semantic queries)
- Pagination beyond `--limit` (MVP)
- Export to CSV/JSON (future phase)
