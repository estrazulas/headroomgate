# HeadroomGate — Context Compression Gateway

Reverse proxy that compresses LLM context (60-95% token savings). Pipeline: Python `headroom/` (proxy, transforms, handlers, providers, dashboard, evals) + Rust `crates/` (smart crusher, live zone, diff compressor) + TypeScript SDK.

## Documentation lookups

Always use Context7 MCP (`resolve-library-id` → `query-docs`) when working with any library, framework, SDK, or API — even well-known ones (FastAPI, Jinja2, Starlette, HTMX, Alpine.js, Tailwind CSS, Neo4j driver, Qdrant, etc.). Prefer this over training-data knowledge and over web search. Use even when you think you know the answer — APIs change.

## Language policy

All documentation, comments in new code, commit messages, and AI-generated output must be in **English**. This includes specs, proposals, design docs, and inline explanations.

## Admin UI patterns

For admin interface forms (`headroom/admin/templates/`), use the existing `combobox` macro from `_components.html` (Alpine.js autocomplete) or a simple `<select>` dropdown when selecting from a bounded set of options. Avoid free-text input for fields like role, provider, or team selection. For short static lists (e.g., 3-5 providers), use `<select>`. For dynamic lists fetched from an API, use `{{ combobox(endpoint=url, value_key='name') }}`.

## Source of truth

- `headroom/` — main codebase (proxy server, Anthropic/OpenAI/Gemini handlers, content router, code compressor, memory, cache, dashboard, install, CLI)
- `crates/` — Rust core (smart crusher, diffs, live zone edges)
- `docs/`, `wiki/` — documentation
- `tests/` — test suite
- `sdk/typescript/` — client SDK

## Quality pipeline — run after code changes

After any source code change, verify:

```bash
# Quality (lint + format + type check)
ruff check .
ruff format --check .
mypy headroom --ignore-missing-imports

# Tests
uv run python -m pytest tests/ -x --timeout=60
```

**UI changes** (dashboard or admin templates): also run the Playwright E2E
tests before committing. See [`e2e-ui-playwright-instructions.md`](e2e-ui-playwright-instructions.md)
for setup and execution details.

The `rebuild.sh` script bundles these quality checks before building and also runs `ruff check`, `ruff format --check`, and `mypy`.

**After rebuild**, update the `deepclaude_with_headroom` repo to reflect any install/tag changes:
```bash
# After rebuild.sh completes, sync the deploy repo
cd ~/git/deepclaude_with_headroom
# Update version tag and install instructions in README.md if the
# headroom version or install steps changed.
```

## Running locally

```bash
# Run the proxy (development)
uv run headroom proxy

# Full rebuild + release (quality checks → maturin build → pipx install)
./rebuild.sh
```

**Troubleshooting proxy startup issues** — invoke `/headroom-doctor` (`~/.claude/skills/headroom-doctor/SKILL.md`). It diagnoses systemd service, Docker containers (Neo4j/Qdrant), ports, env vars, logs, and health endpoints.

**Note:** `headroom-auth` is a separate plugin (`plugins/headroom-auth/`) installed via `pipx inject`. It may not be importable in a plain `uv` venv — tests that depend on it use `pytest.importorskip`.

**For CLI usage** (auth, user management, API keys, install after rebuild), see `README.md` — it covers `headroom auth`, `headroom usage`, `headroom user`, `headroom install`, and the full command reference.

## Configuration

When the proxy isn't configured yet or env vars are missing, here's where to look:

**Env file and auth bootstrap** are documented in `~/git/deepclaude_with_headroom/install.sh` — it generates `~/.config/headroom/env`, runs `headroom auth init-db`, and creates the admin user + API key.

**Docker containers** live in `~/git/deepclaude_with_headroom/docker-compose.yml` (Neo4j + Qdrant). If they're down, the proxy starts but auth and semantic search fail.
Repo: `git@github.com:estrazulas/deepclaude_with_headroom.git` — contains the service install scripts, systemd unit, and docker-compose setup used to deploy the proxy.

For full troubleshooting (crashes, connection refused, missing containers), invoke `/headroom-doctor`.

## Local intelligence tools (check that graphs exist before using)

### graphify (conceptual map — "what is this about?")
- **Output**: `graphify-out/` (graph.json, GRAPH_REPORT.md, graph.html)
- **Update**: `/graphify <path> --update` (incremental, only new/changed files)
- **Use when**: questions about architecture, design, "how does X work?", "why was Y built this way?", concept relationships, architectural surprises
- **Query**: `graphify query "<question>"` — answers from the existing graph without rebuild

### codebase-memory (structural map — "who calls whom?")
- **Output**: `.codebase-memory/` (SQLite, tree-sitter indexed, zero LLM)
- **Update**: `codebase-memory-mcp cli --json index_repository '{"repo_path": "/home/estrazulas/git/headroomgate"}'`
- **Use when**: questions about call chains, dependencies, "who calls X?", "what does Y import?", "what's the impact of changing Z?", symbol path tracing
- **MCP tools**: `search_graph`, `trace_path`, `query_graph` (Cypher), `get_architecture`, `get_code_snippet`, `detect_changes`

## Lessons learned

Anti-patterns and pitfalls from past implementations. Read before starting similar work:

- [`lessons_learned/backend-coding.md`](lessons_learned/backend-coding.md) — Backend / coding
- [`lessons_learned/e2e-testing.md`](lessons_learned/e2e-testing.md) — E2E testing
- [`lessons_learned/frontend-templates.md`](lessons_learned/frontend-templates.md) — Frontend / templates

When archiving a change (after `/opsx:archive`), move the final artifacts to the `docs_sdd` repo:
```bash
git clone git@github.com:estrazulas/docs_sdd.git /tmp/docs_sdd
cp -r openspec/changes/<name> /tmp/docs_sdd/headroomgate/openspec/changes/
cd /tmp/docs_sdd && git add headroomgate/openspec/changes/<name> && git commit -m "..." && git push
```
During active development, specs stay in `openspec/changes/<name>/` locally. Only the final, archived version goes to `https://github.com/estrazulas/docs_sdd`.

### Quick decision rule
- "How does compression work?" → **graphify** (conceptual)
- "Who calls `ContentRouter.transform()`?" → **codebase-memory** (structural)
- "What's the proxy architecture?" → **graphify** (overview, communities)
- "Which handlers touch the cache?" → **codebase-memory** (dependencies)
- Both available? Start with whichever fits the question best. If the first doesn't give the full answer, use the other.
