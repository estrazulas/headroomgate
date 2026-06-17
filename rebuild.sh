#!/usr/bin/env bash
# rebuild.sh — Compila, publica release e instala headroom do fonte
set -euo pipefail
source "$HOME/.cargo/env"

echo "=== Verificando upstream ==="
if git remote get-url upstream >/dev/null 2>&1; then
  echo "⚠️  Histórico sanitizado — merge direto não funciona."
  echo "   Para sync: siga BUILD.md (reset + cherry-pick)."
  echo "   Continuando sem sync upstream..."
else
  echo "   Remote 'upstream' não configurado. Pulando sync."
fi

VERSAO=$(grep 'version = ' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
echo "=== Compilando headroom v${VERSAO} ==="
rm -rf dist/
maturin build --release --out dist/

echo "=== Publicando release v${VERSAO} ==="
gh release create "v${VERSAO}" dist/*.whl \
  --title "v${VERSAO} — Build sanitizado" \
  --notes "Build compilado localmente a partir do commit $(git rev-parse HEAD)."

echo "=== Instalando localmente ==="
WHEEL=$(ls dist/*.whl | head -1)
pipx install --force "${WHEEL}[proxy,code,mcp,auth]"
systemctl --user restart headroom.service 2>/dev/null || true

echo "=== Pronto! headroom ${VERSAO} instalado e release publicado ==="
