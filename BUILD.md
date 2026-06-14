# 🔨 Build & Release Guide — Headroom Sanitizer

Este repositório é um fork seguro do [headroom](https://github.com/chopratejas/headroom) para uso interno.  
Aqui você **compila do código-fonte** e publica um release próprio, eliminando a dependência do binário opaco do PyPI.

---

## Pré-requisitos (instalar uma vez)

```bash
# Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"

# Maturin (build de packages Python + Rust)
pipx install 'maturin>=1.5,<2.0'

# GitHub CLI (para criar releases)
sudo apt install gh -y
gh auth login
```

---

## Fluxo completo: nova versão

### 1. Sincronizar com upstream

```bash
cd headroom_sanitizer
git fetch upstream --tags
git checkout main
git merge upstream/main
# Resolver conflitos se houver
git push origin main
```

### 2. Verificar a versão nova

```bash
grep 'version = ' pyproject.toml | head -1
# Exemplo: version = "0.26.0"
VERSAO=$(grep 'version = ' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
echo "Construindo versão: $VERSAO"
```

### 3. Compilar

```bash
source "$HOME/.cargo/env"
rm -rf dist/
maturin build --release --out dist/
ls -lh dist/
```

### 4. Publicar release no GitHub

```bash
VERSAO=$(grep 'version = ' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
gh release create "v${VERSAO}" dist/*.whl \
  --title "v${VERSAO} — Build sanitizado" \
  --notes "Build compilado localmente a partir do commit $(git rev-parse HEAD)."
```

### 5. Instalar (em qualquer máquina)

```bash
VERSAO="0.25.0"  # ajuste para a versão publicada
pipx install --force \
  "https://github.com/estrazulas/headroom_sanitizer/releases/download/v${VERSAO}/headroom_ai-${VERSAO}-cp310-abi3-manylinux_2_35_x86_64.whl[proxy,code,mcp]"
```

---

## Script completo (atalho)

Salve como `rebuild.sh` na raiz do repo:

```bash
#!/usr/bin/env bash
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
```

Uso:
```bash
chmod +x rebuild.sh
./rebuild.sh
```

---

## Verificação de segurança (auditoria)

Antes de cada build, revise as diferenças entre seu fork e o upstream:

```bash
git fetch upstream --tags
git log upstream/main ^origin/main --oneline  # commits no upstream que você não tem
git diff upstream/main --stat                  # estatística das mudanças
```

Se houver alterações suspeitas nos binários Rust (`crates/headroom-core/`, `Cargo.toml`), **não compile** até revisar.

---

## Referências

- Upstream: https://github.com/chopratejas/headroom
- PyPI oficial: https://pypi.org/project/headroom-ai/
- Maturin: https://www.maturin.rs/
