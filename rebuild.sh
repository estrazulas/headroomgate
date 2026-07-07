#!/usr/bin/env bash
# rebuild.sh — Compile, release, and install headroom from source
set -euo pipefail
source "$HOME/.cargo/env"

VENV_BIN="$(dirname "$0")/.venv/bin"

echo "=== Upstream check ==="
if git remote get-url upstream >/dev/null 2>&1; then
  echo "⚠️  Sanitized history — direct merge won't work."
  echo "   To sync: follow BUILD.md (reset + cherry-pick)."
  echo "   Continuing without upstream sync..."
else
  echo "   Remote 'upstream' not configured. Skipping sync."
fi

echo ""
echo "=== Quality checks ==="
echo "  ruff check..."
"$VENV_BIN/ruff" check .
echo "  ruff format..."
"$VENV_BIN/ruff" format --check .
echo "  mypy..."
"$VENV_BIN/mypy" headroom --ignore-missing-imports
echo "  OK — all quality checks passed"

VERSAO=$(grep 'version = ' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
echo ""
echo "=== Building headroom v${VERSAO} ==="
rm -rf dist/
maturin build --release --out dist/

echo "=== Building headroom-auth plugin ==="
PLUGIN_DIR="plugins/headroom-auth"
PLUGIN_VERSAO=$(grep 'version = ' "$PLUGIN_DIR/pyproject.toml" | head -1 | sed 's/.*"\(.*\)".*/\1/')
pyproject-build --outdir dist/ "$PLUGIN_DIR"

echo "=== Publishing release v${VERSAO} ==="
# Source GH_TOKEN from headroom env if available
[ -f "$HOME/.config/headroom/env" ] && export $(grep -v '^#' "$HOME/.config/headroom/env" | grep 'GH_TOKEN' | xargs) 2>/dev/null || true
GH_REPO=$(git remote get-url origin 2>/dev/null | sed 's|.*[:/]\([^/]*/[^/]*\)\.git|\1|')
gh release create "v${VERSAO}" \
  dist/headroom_ai-*.whl \
  dist/headroom_auth-*.whl \
  ${GH_REPO:+--repo "$GH_REPO"} \
  --title "v${VERSAO} — Build sanitizado" \
  --notes "Build compiled locally from commit $(git rev-parse HEAD)."

echo "=== Installing locally ==="
WHEEL=$(ls dist/headroom_ai-*.whl | head -1)
PLUGIN_WHEEL=$(ls dist/headroom_auth-*.whl | head -1)
pipx install --force "${WHEEL}[proxy,code,mcp,auth]"
pipx uninject headroom-ai headroom-auth 2>/dev/null || true
pipx inject headroom-ai "$PLUGIN_WHEEL"
systemctl --user restart headroom.service 2>/dev/null || true

echo "=== Done! headroom ${VERSAO} + headroom-auth ${PLUGIN_VERSAO} installed and release published ==="
