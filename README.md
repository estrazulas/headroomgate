<div align="center"><pre>
  ██╗  ██╗███████╗ █████╗ ██████╗ ██████╗  ██████╗  ██████╗ ███╗   ███╗
  ██║  ██║██╔════╝██╔══██╗██╔══██╗██╔══██╗██╔═══██╗██╔═══██╗████╗ ████║
  ███████║█████╗  ███████║██║  ██║██████╔╝██║   ██║██║   ██║██╔████╔██║
  ██╔══██║██╔══╝  ██╔══██║██║  ██║██╔══██╗██║   ██║██║   ██║██║╚██╔╝██║
  ██║  ██║███████╗██║  ██║██████╔╝██║  ██║╚██████╔╝╚██████╔╝██║ ╚═╝ ██║
  ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚═╝     ╚═╝
                  The context compression layer for AI agents
</pre></div>

<p align="center"><strong>60–95% fewer tokens · library · proxy · MCP · 6 algorithms · local-first · reversible</strong></p>

<p align="center">
  <a href="https://github.com/estrazulas/headroom_sanitizer"><img src="https://img.shields.io/badge/fork-sanitized-blue.svg" alt="Fork: sanitized"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License: Apache 2.0"></a>
  <a href="https://github.com/chopratejas/headroom"><img src="https://img.shields.io/badge/upstream-headroom-8A2BE2.svg" alt="Upstream: chopratejas/headroom"></a>
</p>

<p align="center">
  <a href="https://headroom-docs.vercel.app/docs">Docs</a> ·
  <a href="#get-started">Install</a> ·
  <a href="#agent-compatibility-matrix">Agents</a> ·
  <a href="https://discord.gg/yRmaUNpsPJ">Discord</a>
</p>

---

Headroom compresses everything your AI agent reads — tool outputs, logs, RAG chunks, files, and conversation history — before it reaches the LLM. Same answers, fraction of the tokens.

> **This is a sanitized fork** of [chopratejas/headroom](https://github.com/chopratejas/headroom). All compression features are preserved from upstream. For the original project's full documentation, benchmarks, pipeline internals, and integrations, see the [upstream repo](https://github.com/chopratejas/headroom).

---

## 🔐 What's different in this fork

This fork adds **multi-user auth and access control** on top of the compression proxy, turning Headroom into a managed LLM gateway for teams.

### PRD 1 — Admin CLI & user management

- **User registration** — `headroom auth user add` creates users with encrypted API keys (Fernet)
- **Team organization** — users belong to teams; the admin sets roles and rate limits
- **Key rotation** — `headroom auth key rotate <user>` generates a new API key, revoking the old one

### PRD 2 — Auth proxy gateway

- **Middleware plugin** — every proxy request is authenticated before reaching the LLM
- **API key validation** — reads the `Authorization: Bearer <key>` header, looks up the user in Neo4j
- **Rate limiting** — per-user and per-team token budgets enforced by a token-bucket algorithm
- **Identity propagation** — the authenticated user identity travels through `contextvars`, available to every downstream component without passing it explicitly

### PRD 3 — Audit & analytics

- **Structured logging (Neo4j)** — every request is recorded: who made it, which model, how many tokens, latency, cache hit/miss
- **Semantic search (Qdrant)** — request prompts are embedded as vectors so you can search by meaning: *"show me everything about database migrations"*
- **Async buffer** — writes are batched in memory (50 entries or 5 seconds, whichever comes first), so audit logging adds **zero latency** to the client response
- **CLI analytics** — `headroom audit summary`, `headroom audit top --by-tokens`, `headroom audit search "architecture patterns"`

---

## How it works (layman's version)

Think of Headroom as an **office building** where each LLM request is a visit:

| Component | Technology | Real-world analogy |
|-----------|-----------|-------------------|
| **Auth middleware** | Neo4j + Fernet | The **badge reader** at the turnstile — only people with a valid badge (API key) get in |
| **Rate limiter** | Token bucket | The **elevator keycard** — each team has a monthly quota; when it's spent, the elevator stops |
| **Audit store** | Neo4j | The **sign-in book** at reception — records who came in, when, which room they used, how long they stayed |
| **Semantic log** | Qdrant + embeddings | The **librarian's index cards** — you can search "who asked about Python threading?" and find matching visits even if the exact words differ |

### Request flow

```
 ┌──────────┐
 │  Client  │  "Explain Python inheritance"
 └────┬─────┘
      │  Request + Authorization: Bearer <api-key>
      ▼
 ┌─────────────────────────────────────────────────────────┐
 │                    HEADROOM PROXY                         │
 │                                                          │
 │  ┌──────────────────┐                                   │
 │  │  1. AUTH (Neo4j) │  "Whose badge is this?"           │
 │  │  API key → user, │  → "joao, team backend, active"   │
 │  │  team, role      │                                    │
 │  └────────┬─────────┘                                   │
 │           │ ✅ Authenticated                             │
 │           ▼                                             │
 │  ┌──────────────────┐                                   │
 │  │  2. COMPRESSION  │  Same pipeline as upstream        │
 │  │  + LLM CALL     │  ──► Anthropic / OpenAI            │
 │  └────────┬─────────┘  ◄── Response                     │
 │           │ Response ready                              │
 │           ▼                                             │
 │  ┌──────────────────┐                                   │
 │  │  3. BUFFER (RAM) │  "Don't write one by one —        │
 │  │  Batches 50 reqs │   collect and flush in bulk"      │
 │  │  or 5 seconds    │                                   │
 │  └────────┬─────────┘                                   │
 │           │                                             │
 │  ┌────────┴────────┐                                    │
 │  │    4. RECORD     │  (background — client already     │
 │  │                  │   got the response)               │
 │  │  ┌──────┐┌─────┐ │                                    │
 │  │  │Neo4j ││Qdrant│ │                                  │
 │  │  │      ││      │ │                                  │
 │  │  │"joao ││vector│ │                                  │
 │  │  │ used ││[0.1, │ │  ← 384 numbers representing      │
 │  │  │GPT-5 ││ 0.3, │ │    "Explain Python inheritance"  │
 │  │  │1200  ││ ...] │ │    for future similarity search  │
 │  │  │tokens││      │ │                                  │
 │  │  └──────┘└─────┘ │                                    │
 │  └──────────────────┘                                   │
 │           │                                             │
 └───────────┼─────────────────────────────────────────────┘
             ▼
    ┌────────────┐
    │  Client    │  Response delivered
    └────────────┘
```

### What each database stores

**Neo4j** answers **"who did what and when"** (a turbocharged spreadsheet):

```
(joao)──[MADE]──(RequestLog)
                   │
                   ├── when: 2026-06-17 14:32
                   ├── model: gpt-5
                   ├── tokens in: 200
                   ├── tokens out: 1000
                   ├── saved: 300 tokens (compression)
                   ├── latency: 1.2s
                   └── cache: miss

Query: "How many tokens did team backend use this week?"
Query: "Who uses Claude Opus the most?"
```

**Qdrant** answers **"what was it about?"** (Google for your request history):

```
"Explain Python inheritance"
        │
        ▼
  [0.12, 0.87, -0.34, ...]   ← 384-number fingerprint
        │
        ▼
  Stored alongside metadata
        │
        ▼
  Future search: "queries about OOP and Python"
        │
        ▼
  Finds this request even though it
  never contained the word "OOP"!

Query: "What is the data team asking about lately?"
Query: "Show me requests similar to this one that returned errors"
```

**In one sentence:** Neo4j gives you the structured audit trail; Qdrant lets you explore it by meaning.

---

## Get started

Install the latest release wheel directly from GitHub:

```bash
pipx install --force \
  "https://github.com/estrazulas/headroom_sanitizer/releases/download/v0.25.1/headroom_ai-0.25.1-cp310-abi3-manylinux_2_35_x86_64.whl[proxy,code,mcp]"
```

Available extras (same as upstream plus the new `[auth]` extra):

| Extra | Provides |
|-------|----------|
| `proxy` | FastAPI proxy server, MCP tools, ONNX compression |
| `code` | AST-based code compression (tree-sitter) |
| `mcp` | MCP server (`headroom_compress`, `headroom_retrieve`, `headroom_stats`) |
| `memory` | Local vector memory (hnswlib, sqlite-vec) |
| `auth` | **New** — user management CLI, API key crypto, Neo4j auth store |
| `all` | Everything above |

> **Note:** The `[auth]` extra requires a running Neo4j instance. Set `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` in your environment.

---

## Quick start — auth proxy

| You are a… | Run this |
|------------|----------|
| **Admin** setting up the proxy | `./scripts/headroom-setup` |
| **Developer** connecting your client | See [docs/auth.md](docs/auth.md) |
| **Developer** using Claude Code | `./scripts/headroom-connect "prompt"` |

```bash
# Admin: interactive setup (Neo4j, encryption key, users, provider keys)
./scripts/headroom-setup

# Developer: save your key and connect
cp scripts/headroom-connect-env.template ~/.config/headroom/env
# edit ~/.config/headroom/env with your hr_... key
./scripts/headroom-connect "Explain Python decorators"
```

---

## Agent compatibility matrix

| Agent       | `headroom wrap` | Notes                            |
|-------------|:---------------:|----------------------------------|
| Claude Code | ✅              | `--memory` · `--code-graph`      |
| Codex       | ✅              | shares memory with Claude        |
| Cursor      | ✅              | prints config — paste once       |
| Aider       | ✅              | starts proxy + launches          |
| OpenClaw    | ✅              | installs as ContextEngine plugin |

Any OpenAI-compatible client works via `headroom proxy`. MCP-native: `headroom mcp install`.

---

## When to use · When to skip

**Use this fork if you…**
- run an LLM proxy for a **team** and need to know who is using what
- want **API key authentication** without setting up a separate auth service
- need an **audit trail** — who asked what, when, and how much it cost
- want **semantic search** over request history ("find all conversations about Kubernetes")
- need **per-user rate limits** so one heavy user doesn't exhaust the team budget

**Skip this fork if you…**
- only use Headroom for **personal** projects — the upstream proxy is simpler
- don't want to run **Neo4j** or **Qdrant** alongside the proxy
- only use a single provider's native compaction and don't need team features
- work in a sandboxed environment where local processes can't run

---

## How to build / install

This fork lets you compile from audited source instead of running opaque PyPI binaries.

### One-command install (pre-built wheel)

```bash
pipx install --force \
  "https://github.com/estrazulas/headroom_sanitizer/releases/download/v0.25.1/headroom_ai-0.25.1-cp310-abi3-manylinux_2_35_x86_64.whl[proxy,code,mcp]"
```

### Build from source

```bash
# 1. Sync with upstream
git fetch upstream --tags
git merge upstream/main

# 2. Build wheel (requires Rust + Maturin)
source "$HOME/.cargo/env"
rm -rf dist/
maturin build --release --out dist/

# 3. Publish GitHub Release
VER=$(grep 'version = ' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
gh release create "v${VER}" dist/*.whl \
  --title "v${VER} — Build sanitizado" \
  --notes "Build from commit $(git rev-parse HEAD)."

# 4. Install locally
pipx install --force "dist/*.whl[proxy,code,mcp]"
systemctl --user restart headroom.service
```

Or use the bundled script: `./rebuild.sh`

Full build guide: [`BUILD.md`](BUILD.md)

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

This fork is based on [chopratejas/headroom](https://github.com/chopratejas/headroom). All upstream compression capabilities are preserved and unmodified.
