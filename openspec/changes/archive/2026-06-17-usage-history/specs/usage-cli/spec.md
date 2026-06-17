## MODIFIED Requirements

### Requirement: Audit user subcommand
The system SHALL provide `headroom usage user <username>` to show usage by a specific user. When `--history` is not present, aggregate statistics are shown (total requests, tokens, models). When `--history` is present, a chronological list of individual requests is shown instead. The `--self` flag resolves the caller's own identity.

Flags:
- `--last <duration>`: filter by time window (e.g., `7d`, `24h`, `30m`)
- `--by-day`: show daily aggregate breakdown (mutually exclusive with `--history`)
- `--by-model`: show per-model aggregate breakdown (mutually exclusive with `--history`)
- `--history`: show individual request history instead of aggregates
- `--limit <N>`: max entries when `--history` is used (default 25, max 100)

#### Scenario: Show user usage summary (no change)
- **WHEN** admin runs `headroom usage user alice --last 7d`
- **THEN** output shows: total requests, input/output tokens, tokens saved, models used with counts, cache hit rate, and average latency

#### Scenario: Show user usage by day (no change)
- **WHEN** admin runs `headroom usage user alice --last 7d --by-day`
- **THEN** output shows a daily breakdown with date, requests, tokens_in, tokens_out, and saved per day

#### Scenario: Show user usage by model (no change)
- **WHEN** admin runs `headroom usage user alice --last 7d --by-model`
- **THEN** output shows a model breakdown with model name, requests, and tokens_in per model

#### Scenario: Developer uses --self (no change)
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
