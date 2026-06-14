#!/usr/bin/env bash
# rebuild.sh — Compila, publica release e instala headroom do fonte
set -euo pipefail
source "$HOME/.cargo/env"

echo "=== Sincronizando upstream ==="
git fetch upstream --tags
git merge upstream/main || { echo "Resolva os conflitos e rode novamente"; exit 1; }

VERSAO=$(grep 'version = ' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
echo "=== Compilando headroom v${VERSAO} ==="
rm -rf dist/
maturin build --release --out dist/

echo "=== Publicando release v${VERSAO} ==="
gh release create "v${VERSAO}" dist/*.whl \
  --title "v${VERSAO} — Build sanitizado" \
  --notes "Build compilado localmente a partir do commit $(git rev-parse HEAD)."

echo "=== Instalando localmente ==="
pipx install --force "dist/*.whl[proxy,code,mcp]"
systemctl --user restart headroom.service 2>/dev/null || true

echo "=== Pronto! headroom ${VERSAO} instalado e release publicado ==="
