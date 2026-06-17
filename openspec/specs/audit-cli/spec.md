# usage-cli

`headroom usage` Click command group for querying usage audit and analytics.

## Purpose

Provide structured queries (`audit user`, `audit team`, `audit top`, `audit summary`), semantic search (`audit search`), and manual cleanup (`audit purge`) via CLI, consistent with the `headroom auth` pattern from PRD 1. Identity is resolved from PRD 2 contextvars (inside proxy) or `HEADROOM_API_KEY` env var (direct CLI). Output uses Rich tables.

## Requirements

### Requirement: CLI group registration
The system SHALL register a `headroom usage` Click command group in `headroom/cli/audit.py`, following the same pattern as `headroom auth` from PRD 1.

#### Scenario: Audit group appears in help
- **WHEN** user runs `headroom --help`
- **THEN** `audit` appears as a command group with description "Query usage audit and analytics"

#### Scenario: Audit subcommands list
- **WHEN** user runs `headroom usage --help`
- **THEN** subcommands `user`, `team`, `top`, `summary`, `search`, and `purge` are listed

### Requirement: Audit user subcommand
The system SHALL provide `headroom usage user <username>` to show usage by a specific user. When `--history` is not present, aggregate statistics are shown (total requests, tokens, models). When `--history` is present, a chronological list of individual requests is shown instead. The `--self` flag resolves the caller's own identity.

Flags:
- `--last <duration>`: filter by time window (e.g., `7d`, `24h`, `30m`)
- `--by-day`: show daily aggregate breakdown (mutually exclusive with `--history`)
- `--by-model`: show per-model aggregate breakdown (mutually exclusive with `--history`)
- `--history`: show individual request history instead of aggregates
- `--limit <N>`: max entries when `--history` is used (default 25, max 100)

#### Scenario: Show user usage summary
- **WHEN** admin runs `headroom usage user alice --last 7d`
- **THEN** output shows: total requests, input/output tokens, tokens saved, models used with counts, cache hit rate, and average latency

#### Scenario: Show user usage by day
- **WHEN** admin runs `headroom usage user alice --last 7d --by-day`
- **THEN** output shows a daily breakdown with date, requests, tokens_in, tokens_out, and saved per day

#### Scenario: Show user usage by model
- **WHEN** admin runs `headroom usage user alice --last 7d --by-model`
- **THEN** output shows a model breakdown with model name, requests, and tokens_in per model

#### Scenario: Developer uses --self
- **WHEN** developer runs `headroom usage user --self --last 7d`
- **THEN** output shows the developer's own usage

#### Scenario: Show user request history
- **WHEN** admin runs `headroom usage user alice --history --last 7d`
- **THEN** output shows a table with columns: timestamp, model, input tokens, output tokens, latency, and summary (first 120 chars)
- **AND** entries are ordered by timestamp descending (most recent first)
- **AND** a maximum of 25 entries are shown by default

#### Scenario: History with custom limit
- **WHEN** admin runs `headroom usage user alice --history --last 7d --limit 10`
- **THEN** output shows at most 10 entries

#### Scenario: History enforces access scope
- **WHEN** developer runs `headroom usage user maria --history --last 7d`
- **THEN** the system returns an access error because the developer can only view their own requests

#### Scenario: History with --self
- **WHEN** developer runs `headroom usage user --self --history --last 7d`
- **THEN** output shows the developer's own request history

#### Scenario: --history and --by-day are mutually exclusive
- **WHEN** user runs `headroom usage user alice --history --by-day`
- **THEN** the system returns an error stating the flags are mutually exclusive

### Requirement: Audit team subcommand
The system SHALL provide `headroom usage team <team_name>` to show usage aggregated by team, with flags `--last <duration>` and `--by-model`.

#### Scenario: Show team usage
- **WHEN** admin runs `headroom usage team backend --last 30d`
- **THEN** output shows: total requests, input/output tokens, active users count, and models used

#### Scenario: Show team usage by model
- **WHEN** admin runs `headroom usage team backend --last 30d --by-model`
- **THEN** output shows model breakdown with model, requests, tokens_in, tokens_out, and users count per model

### Requirement: Audit top subcommand
The system SHALL provide `headroom usage top` to show top users by tokens or requests, with flags `--by-tokens`, `--by-requests`, `--last <duration>`, and `--limit <N>`.

#### Scenario: Top users by tokens
- **WHEN** admin runs `headroom usage top --by-tokens --last 7d --limit 5`
- **THEN** output shows ranked list: rank, username, team, requests, and tokens_in

#### Scenario: Default limit
- **WHEN** admin runs `headroom usage top --by-tokens --last 7d` without `--limit`
- **THEN** the default limit of 10 users is shown

### Requirement: Audit summary subcommand
The system SHALL provide `headroom usage summary` to show aggregate proxy usage, with flag `--last <duration>`.

#### Scenario: Show proxy summary
- **WHEN** admin runs `headroom usage summary --last 24h`
- **THEN** output shows: total requests, total tokens (in/out), active users count, active models, cache hit rate, and average savings percentage

### Requirement: Audit search subcommand
The system SHALL provide `headroom usage search <query>` for semantic search via Qdrant, with flags `--user`, `--team`, `--model`, `--last <duration>`, `--min-score <0.0-1.0>`, and `--self`.

#### Scenario: Semantic search across all users
- **WHEN** admin runs `headroom usage search "JWT authentication" --last 30d`
- **THEN** Qdrant is queried for similar embeddings in `headroom_request_logs`
- **AND** results are shown ranked by similarity score with timestamp, username, summary snippet, model, and token counts

#### Scenario: Semantic search filtered by team
- **WHEN** admin runs `headroom usage search "memory leak" --team backend --min-score 0.7`
- **THEN** only results from the backend team are shown with similarity > 0.7

#### Scenario: Semantic search with self scope
- **WHEN** developer runs `headroom usage search "debug" --self --last 90d`
- **THEN** only the developer's own requests are searched

#### Scenario: Qdrant unavailable
- **WHEN** Qdrant is unreachable during audit search
- **THEN** the CLI returns an error message indicating semantic search is unavailable but structured queries still work

### Requirement: Audit purge subcommand
The system SHALL provide `headroom usage purge --before <date>` for manual cleanup of old audit data from both Neo4j and Qdrant.

#### Scenario: Purge with confirmation
- **WHEN** admin runs `headroom usage purge --before 2025-01-01`
- **THEN** the system prompts for confirmation
- **AND** on confirmation, removes matching `(:RequestLog)` nodes from Neo4j and embeddings from Qdrant
- **AND** reports the count of removed records

#### Scenario: Purge skip confirmation
- **WHEN** admin runs `headroom usage purge --before 2025-01-01 --yes`
- **THEN** the purge proceeds without prompting

### Requirement: Duration flag parsing
The `--last` flag SHALL accept human-readable durations: `Nh` (hours), `Nd` (days), `Nw` (weeks), and `Nm` (months, 30-day approximation).

#### Scenario: Parse hours
- **WHEN** `--last 24h` is specified
- **THEN** queries filter for the last 24 hours

#### Scenario: Parse days
- **WHEN** `--last 7d` is specified
- **THEN** queries filter for the last 7 days

#### Scenario: Invalid duration
- **WHEN** `--last foo` is specified
- **THEN** the CLI returns an error: "Invalid duration 'foo'. Use format: 24h, 7d, 2w, 3m."
