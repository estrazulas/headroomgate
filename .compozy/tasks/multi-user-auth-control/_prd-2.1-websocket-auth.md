# PRD 2.1: WebSocket Auth (Codex Relay)

## Status

**Deferred** — este PRD é um placeholder. O suporte a Codex (OpenAI GPT-5.4+) ainda não está ativo no headroom. Quando for implementado, este PRD deve ser revisitado.

## Overview

O PRD 2 (Authenticated Proxy Gateway) cobre autenticação em requests HTTP REST. Conexões WebSocket (`/v1/responses` do Codex relay) têm um modelo diferente: a key do proxy só aparece no handshake inicial, e a conexão permanece aberta por minutos ou horas. Este PRD descreve o que precisa ser feito para proteger conexões WebSocket quando o Codex relay for suportado.

## Why This Is Separate

- **Escopo**: WebSocket auth exige tratamento específico que o ASGI middleware comum não cobre
- **Prioridade**: Nenhum cliente atual (Claude Code, Cursor, ChatGPT, Copilot) usa WebSocket — todos usam HTTP REST
- **Risco**: Incluir WebSocket auth no MVP do PRD 2 atrasaria a entrega sem benefício imediato

## Key Differences from HTTP Auth

| | HTTP REST (PRD 2) | WebSocket (PRD 2.1) |
|---|---|---|
| Auth check | Todo request | Só no handshake |
| Conexão | Abre e fecha | Persiste por minutos/horas |
| Revogação | Próximo request falha (TTL 10s) | Conexão já estabelecida continua ativa |
| Rate limit | Por request | ? (eventos, não requests) |
| Transporte | ASGI middleware padrão | Handshake HTTP + upgrade WebSocket |

## Open Design Questions (a decidir quando implementar)

1. **Auth no handshake**: O header `Authorization: Bearer hr_...` deve ser validado no handshake HTTP que precede o upgrade para WebSocket?
2. **Revogação mid-session**: Se uma key for revogada enquanto o WebSocket está ativo, como cortar a conexão? (Opções: mensagem de close no protocolo, timeout de sessão máximo, ignorar — sessão continua até o cliente desconectar)
3. **Rate limiting**: Como aplicar rate limits em WebSocket? Por evento? Por mensagem? Por tempo de sessão?
4. **Cache de validação**: O cache TTL de 10s do PRD 2 se aplica ao WebSocket? Ou cada handshake faz query Neo4j?
5. **Múltiplos providers**: O Codex relay suporta outros providers além da OpenAI? O mapeamento de path → provider se aplica?

## Tentative Scope (MVP)

- Validar `Authorization: Bearer hr_...` no handshake WebSocket
- Resolver user_id, role, provider keys
- Injetar provider key antes do upgrade
- Timeout máximo de sessão (ex: 30 minutos) para limitar janela de revogação
- Logging de conexão WebSocket no Neo4j (`:RequestLog` com `transport: "websocket"`)

## Non-Goals

- Rate limiting por WebSocket (complexo demais pro MVP)
- Corte de sessão ativa na revogação de key (MVP aceita que sessão continua até timeout)
- Suporte a providers além de OpenAI para WebSocket

## Dependencies

- PRD 1 (Admin CLI & User Management) — `Neo4jAuthStore`, `FernetCrypto`
- PRD 2 (Authenticated Proxy Gateway) — middleware de auth, cache, contextvars
- Codex relay no headroom (ainda não implementado)

## References

- [PRD 2: Authenticated Proxy Gateway](../_prd-2-auth-gateway.md)
- `headroom/proxy/ws_session_registry.py` — registro de sessões WebSocket existente
- [ADR-002: Auth middleware como plugin](../adrs/adr-002.md)
