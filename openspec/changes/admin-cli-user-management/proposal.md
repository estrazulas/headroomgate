## Why

O headroom proxy hoje não tem conceito de usuário — qualquer pessoa com uma API key de provider pode usar o proxy, sem identificação e sem controle de acesso. Para um time usar o proxy de forma segura, o admin precisa cadastrar desenvolvedores, emitir credenciais, armazenar chaves de provider criptografadas no proxy, e poder revogar acesso imediatamente. Este change cria o módulo de administração (CLI `headroom auth`) e a camada de persistência em Neo4j que suporta os PRDs 2 (auth middleware) e 3 (auditoria).

## What Changes

- **Novo pacote `headroom/auth/`** com modelos de dados (User, Role, Team, ApiKey) e `Neo4jAuthStore` para CRUD via Cypher
- **Novo módulo `headroom/auth/crypto.py`** com criptografia Fernet para provider keys (encrypt/decrypt com `HEADROOM_ENCRYPTION_KEY`)
- **Schema Neo4j**: constraints de unicidade + labels `:User`, `:Role`, `:Team`, `:ApiKey`
- **Novo grupo CLI `headroom auth`** com 15 subcomandos Click: `init-db`, `create-user`, `list-users`, `revoke-user`, `create-team`, `list-teams`, `create-key`, `list-keys`, `revoke-key`, `set-provider-key`, `list-provider-keys`, `create-role`, `list-roles`, `whoami`, `generate-key`
- **4 roles base**: admin, team_lead, developer, viewer — criadas pelo `init-db`
- **Times** obrigatórios para usuários — team lead gerencia apenas seu time
- **API keys expiram em 90 dias** (padrão, configurável via `--ttl-days`)
- **Provider keys** armazenadas criptografadas no nó `Role`, descriptografadas apenas em memória

## Capabilities

### New Capabilities

- `auth-store`: Neo4j schema (constraints, índices, labels `:User`, `:Role`, `:Team`, `:ApiKey`) e camada de acesso a dados (`Neo4jAuthStore`) com operações CRUD para usuários, roles, times e API keys. Reusa o driver Neo4j existente do `DirectMem0Adapter`.
- `auth-crypto`: Criptografia simétrica (Fernet) para provider keys armazenadas no nó `Role`. Expõe `encrypt()`/`decrypt()` via `HEADROOM_ENCRYPTION_KEY`. Provider keys nunca trafegam ou são armazenadas em texto plano.
- `admin-cli`: Grupo `headroom auth` com 15 subcomandos Click para gerenciamento de usuários, roles, times, API keys de proxy e provider keys. Acesso por role: admin gerencia tudo, team_lead gerencia seu time, developer só vê seus dados.

### Modified Capabilities

<!-- Nenhuma — este change adiciona capacidades novas sem alterar specs existentes -->

## Impact

- **Novo código**: `headroom/auth/__init__.py`, `headroom/auth/models.py`, `headroom/auth/store.py`, `headroom/auth/crypto.py`, `headroom/cli/auth.py`
- **Modificado**: `headroom/cli/main.py` (registrar grupo `auth`)
- **Dependências novas**: `cryptography` (Fernet) — já está no pyproject.toml?
- **Neo4j**: Novos labels e constraints — sem alteração nos labels existentes (`:__Entity__`)
- **Não-regressão**: Comandos CLI são independentes do proxy; podem ser executados com proxy parado
