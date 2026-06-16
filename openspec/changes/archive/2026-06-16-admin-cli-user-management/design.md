## Context

O headroom proxy já usa Neo4j para memória semântica (`DirectMem0Adapter` com `GraphDatabase.driver`, Cypher via `MERGE`, APOC para vetores). O `docker-compose.yml` já provisiona Neo4j 5.26 com plugin APOC. A CLI do headroom usa Click (ex: `headroom proxy`, `headroom wrap`).

Este design estende o Neo4j existente com novos labels (`:User`, `:Role`, `:Team`, `:ApiKey`) para controle de acesso, e adiciona um grupo de comandos Click (`headroom auth`) que fala direto com o Neo4j — sem dependência do proxy estar rodando.

Constraints de segurança: provider keys nunca em texto plano no banco (Fernet), API keys do proxy exibidas só uma vez na criação (hash SHA-256 no banco), segredos nunca em argumentos posicionais (stdin/prompt interativo).

## Goals / Non-Goals

**Goals:**
- Camada de persistência (`Neo4jAuthStore`) reusando o driver Neo4j existente
- Criptografia Fernet para provider keys com DEK via `HEADROOM_ENCRYPTION_KEY`
- CLI `headroom auth` com 15 subcomandos para CRUD de usuários, roles, times, API keys e provider keys
- Schema Neo4j com constraints de unicidade (user_id, username, role name, key_hash)
- 4 roles base (admin, team_lead, developer, viewer) criadas pelo `init-db`
- Soft-delete para usuários e API keys (campo `is_active`)
- API keys com expiração padrão de 90 dias

**Non-Goals:**
- Sem API REST ou Web UI (ADR-001)
- Sem SSO/OIDC/LDAP
- Sem permissões granulares por recurso (só controle por role)
- Sem rate limits configuráveis por role (entra no PRD 2)
- Sem auditoria de ações admin (entra no PRD 3)

## Decisions

### D1: Driver Neo4j direto na CLI (sem proxy intermediário)

**Decisão**: A CLI `headroom auth` conecta direto no Neo4j via `GraphDatabase.driver`, sem passar pelo proxy.

**Alternativa rejeitada**: CLI → API REST no proxy → Neo4j. Rejeitada porque exigiria criar API REST de admin (fora do escopo MVP, ADR-001) e o proxy precisaria estar rodando para tarefas de administração.

**Rationale**: A CLI de admin é uma ferramenta de operação, não de runtime. Deve funcionar mesmo com proxy parado. O driver Neo4j já é usado pelo `DirectMem0Adapter` — mesmo padrão, mesma conexão.

### D2: Fernet (symmetric) para provider keys

**Decisão**: Criptografia simétrica com `cryptography.fernet` — uma única chave (`HEADROOM_ENCRYPTION_KEY`) para encrypt/decrypt.

**Alternativa considerada**: AES-GCM direto. Rejeitado porque Fernet já empacota AES-128-CBC + HMAC-SHA256 + timestamp de expiração, é à prova de erros comuns (nonce reuse), e é a recomendação padrão do Python cryptography library para "encrypt anything" use case.

**Alternativa considerada**: KMS externo (AWS KMS, HashiCorp Vault). Rejeitado para MVP — overengineering para time pequeno. Pode ser adicionado como opção na Phase 2.

### D3: SHA-256 para hash de API keys

**Decisão**: API keys do proxy (`hr_...`) são hasheadas com SHA-256 antes de armazenar no Neo4j. A key bruta é exibida uma única vez na criação.

**Alternativa considerada**: bcrypt/argon2. Rejeitado porque API keys são tokens aleatórios de 256 bits (não senhas humanas) — SHA-256 é suficiente e mais rápido para o hot path de validação (PRD 2). Não há risco de rainbow table porque os tokens têm entropia de 256 bits.

### D4: Soft-delete para usuários e keys

**Decisão**: `revoke-user` e `revoke-key` setam `is_active = false`. Nada é deletado fisicamente.

**Rationale**: Auditoria (PRD 3) precisa do histórico. Se um usuário for deletado, os `(:RequestLog)` órfãos perdem a referência. Soft-delete preserva relacionamentos.

## Risks / Trade-offs

- **HEADROOM_ENCRYPTION_KEY perdida** → Provider keys irrecuperáveis. Mitigação: `generate-key` exibe instrução de backup; documentação enfatiza que a chave deve ser armazenada em cofre (1Password, Vault).
- **Senha no histórico do shell** → `set-provider-key` usa prompt interativo (`getpass`), nunca argumento posicional. Documentação avisa sobre histórico.
- **Conexão Neo4j não configurada** → CLI falha com erro claro se `NEO4J_AUTH` ou URI não estiverem definidos. Mitigação: error message inclui exemplo de configuração.
- **Concorrência CLI vs middleware** → `revoke-key` precisa invalidar cache do middleware (PRD 2). Mitigação: signal file ou endpoint interno — decisão delegada ao PRD 2. Por enquanto, TTL de 60s do cache limita a janela.

## Package Map — Core vs Plugin

This change (PRD 1) creates the **core auth package** (`headroom/auth/`) that lives inside the main `headroom-ai` package. The runtime auth middleware (PRD 2) will be a **separate plugin** (`plugins/headroom-auth/`) following the `headroom-oauth2` pattern.

### Core — `headroom/auth/` (shipped with `headroom-ai`)

| Module | Responsibility |
|--------|---------------|
| `headroom/auth/__init__.py` | Package init with lazy imports for store and crypto |
| `headroom/auth/models.py` | Dataclasses: `User`, `Role`, `Team`, `ApiKey` |
| `headroom/auth/store.py` | `Neo4jAuthStore` — Cypher CRUD via `GraphDatabase.driver` (same pattern as `DirectMem0Adapter`) |
| `headroom/auth/crypto.py` | `FernetCrypto` — encrypt/decrypt provider keys via `HEADROOM_ENCRYPTION_KEY` |
| `headroom/cli/auth.py` | Click group `headroom auth` with 15 subcommands |

### Plugin — `plugins/headroom-auth/` (separate package, PRD 2)

| Module | Responsibility |
|--------|---------------|
| `headroom_auth/__init__.py` | Entry point `install(app, config)` for `headroom.proxy_extension` |
| `headroom_auth/middleware.py` | `AuthMiddleware` — ASGI per-request auth |
| `headroom_auth/cache.py` | In-memory validation cache (TTL 60s) |
| `headroom_auth/provider_injector.py` | Provider key injection by request path |
| `headroom_auth/rate_limiter.py` | Per-user rate limiter (extends existing token bucket) |

**Dependency direction**: Plugin → Core. The plugin imports `headroom.auth.store` (Neo4j queries) and `headroom.auth.crypto` (decrypt provider keys). Core has no dependency on the plugin.

**Activation boundary**: When `HEADROOM_AUTH_ENABLED=false` or `--proxy-extension headroom-auth` is not specified, the plugin is a no-op — the proxy is identical to the original. The CLI commands (`headroom auth`) work regardless of whether the proxy is running.

## Migration Plan

1. **Instalação**: `pip install headroom-ai[auth]` (dependências: `cryptography`, `neo4j` já existente)
2. **Setup inicial**: Admin executa `headroom auth init-db` (cria constraints + 4 roles base)
3. **Rollback**: `init-db` é idempotente — se falhar, corrigir conexão Neo4j e reexecutar. Remover labels novos não afeta o `:__Entity__` da memória existente.
4. **Coexistência**: Novos labels (`:User`, `:Role`, `:Team`, `:ApiKey`) não conflitam com labels existentes (`:__Entity__`)

## Open Questions

- ~~`init-db` deve pedir confirmação antes de dropar/reinicializar schema existente?~~ **Resolvido**: Sim. `init-db` é idempotente, mas pede confirmação se detecta schema existente.
- ~~Deve existir `headroom auth backup` para exportar dados sem as provider keys criptografadas?~~ **Deferido**: Phase 2.
- ~~Chaves de provider devem ser validadas no momento do `set-provider-key` (request de teste ao provider)?~~ **Resolvido**: Sim. `set-provider-key` faz um request de teste ao provider antes de armazenar. Key inválida é rejeitada imediatamente.
