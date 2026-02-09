# Tutorial operacional (Web + API) — OpenMesh Pool

Este guia mostra **como operar seu ambiente em produção** usando os serviços que você já subiu:

- Coordinator: `http://212.56.35.111:8001`
- Gateway: `http://212.56.35.111:8002`

---

## 1) O que cada serviço faz

## Coordinator (`:8001`)
Painel de controle técnico do pool:
- autenticação e usuários (`/auth/*`);
- registro e gestão de workers (`/workers*`);
- operação administrativa (`/admin/*`);
- saldo e extrato (`/me/*`);
- ciclo interno de jobs e verificação.

## Gateway (`:8002`)
Entrada pública para clientes:
- recebe chamadas de inferência (`/v1/embed`, `/v1/rank`);
- valida API key;
- aplica rate limit;
- encaminha job para o coordinator e aguarda verificação.

---

## 2) Gestão via Web (Swagger UI)

Como as APIs são FastAPI, você já tem gestão web nativa via Swagger:

- Coordinator docs: `http://212.56.35.111:8001/docs`
- Gateway docs: `http://212.56.35.111:8002/docs`

Também existe o schema OpenAPI (para Postman/Insomnia):
- `http://212.56.35.111:8001/openapi.json`
- `http://212.56.35.111:8002/openapi.json`

> **Fluxo na UI**: abrir endpoint → `Try it out` → preencher JSON → `Execute`.

---

## 3) Primeiro acesso (bootstrapping)

## 3.1 Criar usuário CLIENTE
No Coordinator (`/docs`) execute `POST /auth/register`:

```json
{
  "email": "cliente@seu-dominio.com",
  "password": "Troque-por-uma-senha-forte-123",
  "role": "client"
}
```

## 3.2 Criar usuário OPERADOR (dono de worker)
`POST /auth/register`:

```json
{
  "email": "operador@seu-dominio.com",
  "password": "Outra-senha-forte-123",
  "role": "worker_owner"
}
```

## 3.3 Login
`POST /auth/login` para cada usuário.
Resposta traz `access_token` e `refresh_token`.

Na Swagger do Coordinator, clique em **Authorize** e use:

```text
Bearer <access_token>
```

---

## 4) Criar API key de cliente (para usar no Gateway)

Com token do usuário `client`, use `POST /auth/api-keys`:

```json
{
  "name": "producao-app-1"
}
```

Guarde o campo `key` retornado. Ele será enviado no header:

```text
X-API-Key: <api_key>
```

---

## 5) Cadastrar e operar workers

Com token do `worker_owner`:

## 5.1 Registrar worker
`POST /workers/register`

Exemplo:

```json
{
  "name": "worker-sp-01",
  "region": "sa-east",
  "public_key": "<chave_publica_ed25519_base64url>",
  "specs_json": {
    "reputation": 0.9,
    "estimated_latency_ms": 120
  }
}
```

## 5.2 Listar workers
`GET /workers`

## 5.3 Heartbeat (manter online)
`POST /workers/heartbeat`

```json
{
  "worker_id": 1
}
```

Sem heartbeat recorrente, worker tende a ficar sem atividade real no agendamento.

---

## 6) Operação administrativa do pool (web)

Com usuário `worker_owner` autenticado no Coordinator:

- `GET /admin/workers` → visão de capacidade e jobs ativos.
- `GET /admin/jobs` → fila e status de jobs.
- `POST /admin/jobs/enqueue-demo` → carga de teste.
- `GET /admin/leaderboard` → ranking de workers.
- `GET /admin/finance/summary` → resumo financeiro do pool.
- `GET /admin/emission/status` e `POST /admin/emission/run-now` → emissão.

Isso já funciona como **console web operacional** via Swagger.

---

## 7) Consumo do Gateway (produção)

Use a API key criada no coordinator.

## 7.1 Embed

```bash
curl -X POST 'http://212.56.35.111:8002/v1/embed' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: SUA_API_KEY' \
  -d '{"text":"OpenMesh é uma rede distribuída."}'
```

## 7.2 Rank

```bash
curl -X POST 'http://212.56.35.111:8002/v1/rank' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: SUA_API_KEY' \
  -d '{
    "query":"infra distribuída",
    "texts":["OpenMesh", "banco relacional", "fila assíncrona"]
  }'
```

---

## 8) Observabilidade e operação contínua

Checklist diário:

1. Health:
   - `GET /health` em `:8001` e `:8002`.
2. Métricas:
   - `GET /metrics` (se habilitado por env).
3. Capacidade:
   - `GET /admin/workers` e `GET /admin/jobs`.
4. Finanças:
   - `GET /admin/finance/summary`.
5. Auditoria de usuário:
   - `GET /me`, `GET /me/balance`, `GET /me/ledger`.

---

## 9) Segurança mínima recomendada (produção)

- Colocar reverse proxy (Nginx/Traefik) com HTTPS (Let's Encrypt).
- Restringir acesso ao Coordinator (ideal: apenas VPN/IP allowlist).
- Rotacionar `COORDINATOR_INTERNAL_TOKEN` e API keys periodicamente.
- Definir CORS apenas para domínios confiáveis no Gateway.
- Ativar logs estruturados e centralizar em stack observável.

---

## 10) Troubleshooting rápido

## `401 Invalid API key` no Gateway
- API key não cadastrada/configurada corretamente.
- Verifique header `X-API-Key`.

## `429 Rate limit exceeded`
- Cliente/IP excedeu limite.
- Ajuste `RATE_LIMIT_PER_MINUTE_API_KEY` e `RATE_LIMIT_PER_MINUTE_IP`.

## `503 Verification timeout`
- Gateway não recebeu job `verified` a tempo.
- Verifique workers online, fila e latência; ajuste `POLL_TIMEOUT_SECONDS`.

## Coordinator saudável, mas sem jobs finalizados
- Worker não está enviando heartbeat.
- Worker sem chave pública válida para assinatura.
- Falha de submit/assinatura em `/jobs/submit`.

---

## 11) Próximo passo para gestão realmente amigável

Hoje a gestão web é via Swagger (funcional e completa para operação técnica).
Para operação não técnica, crie um painel (React/Next.js) consumindo:

- Coordinator para admin/finance/workers/jobs;
- Gateway para tráfego de clientes.

Comece por telas: **Login**, **Workers**, **Jobs**, **Finance**, **Health/Metrics**.
