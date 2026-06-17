## 1. Store — Neo4j query for history

- [x] 1.1 Add `get_user_history(user_id, since, limit)` method to `headroom/usage/store.py` that queries `(:RequestLog)` nodes ordered by timestamp DESC
- [x] 1.2 Return list of dicts with fields: `timestamp`, `model`, `input_tokens`, `output_tokens`, `latency_ms`, `summary`
- [x] 1.3 Apply `since` filter using `datetime()` wrapping (match existing pattern in store.py)
- [x] 1.4 Respect access scope: method receives optional `team` parameter for team-lead filtering

## 2. CLI — --history and --limit flags

- [x] 2.1 Add `--history` flag (is_flag, default False) to `usage_user` in `headroom/cli/usage.py`
- [x] 2.2 Add `--limit` option (type=int, default=25, clamp 1-100) to `usage_user`
- [x] 2.3 When `--history` is set, call `store.get_user_history()` instead of aggregate methods
- [x] 2.4 Validate mutual exclusion: `--history` conflicts with `--by-day` and `--by-model`, raise `click.UsageError`
- [x] 2.5 Render history as Rich Table with columns: timestamp, model, tokens (in/out), latency, summary (truncated to 120 chars)

## 3. Summary storage — ensure summaries are written

- [x] 3.1 Verify `headroom/usage/buffer.py` already includes `summary` field in batch data (check `_flush_batch` call to store)
- [x] 3.2 Verify `headroom/usage/store.py` `insert_batch` stores `summary` property on `(:RequestLog)` nodes
- [x] 3.3 If summaries are not persisted, add `summary` field to the UNWIND batch Cypher query

## 4. Access control — scope enforcement

- [x] 4.1 In `usage_user` CLI handler, pass resolved scope to `get_user_history()` 
- [x] 4.2 Ensure developer with `--self` sees only own history
- [x] 4.3 Ensure team lead sees only their team's history when querying team members
- [x] 4.4 Ensure admin sees all

## 5. Tests

- [x] 5.1 Add `test_get_user_history` to `tests/usage/test_store.py` — verify correct ordering and limit
- [x] 5.2 Add `test_usage_user_history` to `tests/usage/test_cli.py` — verify CLI output with `--history`
- [x] 5.3 Add `test_history_access_control` — verify scope enforcement
- [x] 5.4 Add `test_history_by_day_conflict` — verify mutual exclusion error
- [x] 5.5 Run full test suite: `pytest tests/usage/ -v` (target: all passing)
