# E2E UI Testing with Playwright

The admin interface and dashboard have Playwright-based end-to-end tests
that verify real browser interaction flows.

## Prerequisites

```bash
# Install Playwright system browsers (first time only)
playwright install chromium
```

## Running E2E Tests

Before running E2E tests:

1. The **proxy must be running** (`headroom proxy` or systemd service)
2. **Neo4j must be up** (`docker compose up -d neo4j`)
3. A valid **admin `hr_*` API key** is needed

```bash
HEADROOM_ADMIN_URL="http://localhost:8787" \
HEADROOM_E2E_KEY="hr_<your-admin-key>" \
uv run python -m pytest tests/test_admin/test_e2e.py -v --timeout=120
```

The default `HEADROOM_ADMIN_URL` is `http://localhost:8000`. Adjust if your
proxy runs on a different port.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HEADROOM_ADMIN_URL` | `http://localhost:8000` | Base URL of the running proxy |
| `HEADROOM_E2E_KEY` | `hr_admin_test_key_placeholder` | Admin API key for login |

## What the Tests Cover

### Admin Full Workflow (`test_full_admin_workflow`)

1. Login with API key → redirected to `/manage/users`
2. Navigate to Teams → create a team → verify it appears
3. Navigate to Users → create a user → verify it appears
4. Navigate to API Keys → generate a key → verify the "copy now" notice
5. Revoke the key → verify revocation

### Team Lead Scope (`test_team_lead_flows`)

1. Login as admin
2. Verify the Teams link behaviour (hidden or accessible depending on role)

### Usage Dashboard (`test_usage_dashboard`)

1. Login → navigate to Usage
2. Verify summary cards appear
3. Verify time window selector (24h / 7d / 30d)
4. Switch time windows
5. Verify User History and Search Requests sections exist

## Cleaning Up Test Data

After running E2E (or integration) tests, test users/keys/teams accumulate
in Neo4j. Clean them with:

```bash
# Use the dedicated cleanup skill in Claude Code:
#   /headroom-clean-e2e
```

Or run the Cypher queries manually (see `openspec/changes/archive/*/` or
the `headroom-clean-e2e` skill for the full command list).

## Best Practices

- **Isolation**: Each test creates unique names via `secrets.token_hex(4)`
  suffix — no name collision between runs.
- **Speed**: Tests target `120s` timeout but typically complete in <30s.
- **Headless**: Playwright runs headless by default. Add `--headed` for
  debugging (requires `export DISPLAY` or Xvfb on a headless server).
