# Connecting to the Headroom Auth Proxy

This guide covers how to connect **any** Anthropic-compatible or
OpenAI-compatible client through a Headroom proxy that has the auth plugin
enabled.

You only need your **Headroom API key** (`hr_...`) — provider keys
(Anthropic, OpenAI, DeepSeek) live on the proxy server and are injected
automatically. You never see or store them.

---

## Prerequisites

- Your admin gave you an API key starting with `hr_`
- The proxy is running (your admin provides the URL)

---

## Method 1 — Claude Code (recommended)

Use the `headroom-claude` wrapper:

```bash
# One-time setup: save your key
mkdir -p ~/.config/headroom
cat > ~/.config/headroom/env <<'EOF'
HEADROOM_API_KEY=hr_your_key_here
# HEADROOM_PROXY_URL=http://proxy.empresa.com:8787
EOF
chmod 600 ~/.config/headroom/env

# Install the wrapper (optional — or run from repo)
cp scripts/headroom-claude ~/.local/bin/

# Connect
headroom-claude "Explain Python decorators"
```

**What happens:** The proxy authenticates you, injects the provider key, and
logs the request for audit. You never touch a provider key.

### Wrapper options

| Flag | Purpose |
|------|---------|
| `--proxy-url URL` | Override the proxy URL (default: `http://localhost:8787`) |
| `--help` | Show usage |
| `-- claude-args...` | Pass arguments to `claude` |

```bash
headroom-claude --proxy-url http://proxy.empresa.com:8787 "Hello"
headroom-claude -- --model claude-sonnet-4-6 --max-turns 5
```

---

## Method 2 — curl (testing and debugging)

```bash
# Load your key
source ~/.config/headroom/env

# Anthropic-compatible endpoint
curl -s -H "x-api-key: $HEADROOM_API_KEY" \
     -H "anthropic-version: 2023-06-01" \
     -H "Content-Type: application/json" \
     http://localhost:8787/v1/messages -d '{
       "model": "claude-sonnet-4-6",
       "max_tokens": 100,
       "messages": [{"role": "user", "content": "Hello"}]
     }'

# OpenAI-compatible endpoint
curl -s -H "Authorization: Bearer $HEADROOM_API_KEY" \
     -H "Content-Type: application/json" \
     http://localhost:8787/v1/chat/completions -d '{
       "model": "gpt-5",
       "max_tokens": 100,
       "messages": [{"role": "user", "content": "Hello"}]
     }'
```

---

## Method 3 — OpenAI Python SDK / any OpenAI-compatible client

Set the base URL and API key to point at the proxy:

```bash
export OPENAI_BASE_URL="http://localhost:8787/v1"
export OPENAI_API_KEY="$HEADROOM_API_KEY"
```

```python
# Now use the OpenAI SDK normally
from openai import OpenAI
client = OpenAI()  # reads OPENAI_BASE_URL and OPENAI_API_KEY
response = client.chat.completions.create(
    model="gpt-5",
    messages=[{"role": "user", "content": "Hello"}],
)
```

This works with **any** OpenAI-compatible tool (LangChain, LiteLLM, Vercel
AI SDK, etc.) — just point `OPENAI_BASE_URL` at the proxy.

---

## Method 4 — Anthropic Python SDK

```bash
export ANTHROPIC_BASE_URL="http://localhost:8787"
export ANTHROPIC_AUTH_TOKEN="$HEADROOM_API_KEY"
```

```python
from anthropic import Anthropic
client = Anthropic()  # reads ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN
message = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=100,
    messages=[{"role": "user", "content": "Hello"}],
)
```

---

## Configuration reference

| Variable | Required | Purpose |
|----------|----------|---------|
| `HEADROOM_API_KEY` | Yes | Your Headroom API key (`hr_...`) |
| `HEADROOM_PROXY_URL` | No | Proxy URL (default: `http://localhost:8787`) |
| `ANTHROPIC_BASE_URL` | Set by wrapper | Anthropic-compatible base URL |
| `ANTHROPIC_AUTH_TOKEN` | Set by wrapper | API key sent as `x-api-key` header |
| `OPENAI_BASE_URL` | For OpenAI clients | OpenAI-compatible base URL (`.../v1`) |
| `OPENAI_API_KEY` | For OpenAI clients | API key sent as `Authorization: Bearer` |

---

## Troubleshooting

### "HEADROOM_API_KEY is not set"
Your config file is missing. Run:
```bash
mkdir -p ~/.config/headroom
cp scripts/headroom-claude-env.template ~/.config/headroom/env
# Edit ~/.config/headroom/env with your key
```

### "Authorization header is required" / 401
The proxy expects your API key in the `x-api-key` header (Anthropic path)
or `Authorization: Bearer` header (OpenAI path). The wrapper sets this
automatically. With curl, ensure you pass the header explicitly.

### "Key expired" / "Key not found"
Your API key may have expired (90-day default). Ask your admin to
generate a new one: `headroom auth create-key <username>`.

### "provider_key_not_configured"
The admin hasn't registered the provider key for your role yet. The proxy
cannot forward requests upstream without a provider key.

### Connection refused
The proxy is not running or is on a different port. Verify with:
```bash
curl -s http://localhost:8787/health
```

---

## Security notes

- Your config file (`~/.config/headroom/env`) should be `chmod 600` —
  readable only by you.
- Never commit your API key to git. The `.env` file is gitignored.
- Provider keys are encrypted with Fernet in Neo4j and never leave the
  proxy server.
- If your key is compromised, the admin can revoke it:
  `headroom auth revoke-key <key_id>`.
