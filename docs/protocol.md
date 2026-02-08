# Protocol

Especifica o protocolo de comunicação entre gateway, coordinator e workers.

## Entidades

- Client
- Pool Gateway
- Pool Coordinator
- Worker Owner (conta humana/sistema que gerencia workers)
- Worker Runtime (processo executando no host do worker)

## Fluxo alto nível

1. Client envia requisição ao Gateway.
2. Gateway valida autenticação/token e encaminha ao Coordinator.
3. Coordinator agenda tarefa para um Worker elegível.
4. Worker Runtime faz polling, processa a tarefa e envia resultado assinado.

---

## Worker Owner API

Endpoints usados para cadastro e gestão de workers por um usuário com papel `WORKER_OWNER`.

### Autenticação esperada

- `Authorization: Bearer <access_token>` (OAuth2 password flow, `tokenUrl=/auth/login`).
- Token deve mapear para usuário ativo.
- Role obrigatória: `WORKER_OWNER`.

### `POST /workers/register`

Registra um novo worker vinculado ao usuário autenticado.

**Request JSON**

- `name` (string, obrigatório, 1..120)
- `region` (string, opcional, máx. 64)
- `specs_json` (objeto JSON, opcional)
- `public_key` (string base64url Ed25519 pública, opcional na criação, recomendado)

**Response JSON (201)**

- `id` (int)
- `name` (string)
- `owner_user_id` (int)
- `status` (string; inicia como `offline`)
- `region` (string | null)
- `specs_json` (objeto | null)
- `public_key` (string | null)
- `last_seen_at` (datetime ISO-8601 | null)

**Erros e condições**

- `401 Invalid token`: token ausente/inválido, usuário inativo ou inexistente.
- `403 Insufficient role`: usuário sem role `WORKER_OWNER`.
- `409 Worker name already exists`: conflito de unicidade no nome.

**Exemplo real**

```http
POST /workers/register
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "name": "worker-owner-a",
  "region": "sa-east-1",
  "public_key": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE"
}
```

```json
{
  "id": 1,
  "name": "worker-owner-a",
  "owner_user_id": 10,
  "status": "offline",
  "region": "sa-east-1",
  "specs_json": null,
  "public_key": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE",
  "last_seen_at": null
}
```

### `GET /workers`

Lista somente workers cujo `owner_user_id` é o usuário autenticado.

**Request**

- Sem corpo.

**Response JSON (200)**

- `workers`: array de `WorkerResponse`.

**Erros e condições**

- `401 Invalid token`
- `403 Insufficient role`

**Exemplo real**

```http
GET /workers
Authorization: Bearer <token>
```

```json
{
  "workers": [
    {
      "id": 7,
      "name": "worker-owned",
      "owner_user_id": 22,
      "status": "offline",
      "region": null,
      "specs_json": null,
      "public_key": null,
      "last_seen_at": null
    }
  ]
}
```

---

## Worker Runtime API

Endpoints operacionais usados durante execução dos workers.

> Observação: atualmente estes endpoints também exigem token de `WORKER_OWNER` e validam ownership por `worker_id`. Em uma evolução futura, o runtime pode usar identidade própria, mas o contrato atual é owner-token + assinatura criptográfica no submit.

### Autenticação esperada

- `Authorization: Bearer <access_token>` com role `WORKER_OWNER`.
- `worker_id` sempre é validado contra o usuário autenticado (`owner_user_id`).
- No submit, além do token, há autenticação criptográfica via assinatura Ed25519.

### `POST /workers/heartbeat`

Marca worker como online e atualiza `last_seen_at`.

**Request JSON**

- `worker_id` (int, obrigatório)

**Response JSON (200)**

- `worker_id` (int)
- `last_seen_at` (datetime ISO-8601)

**Erros e condições**

- `401 Invalid token`
- `403 Insufficient role`
- `404 Worker not found`: worker inexistente **ou** worker não pertence ao usuário autenticado (ownership inválido)

**Exemplo real**

```http
POST /workers/heartbeat
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "worker_id": 7
}
```

```json
{
  "worker_id": 7,
  "last_seen_at": "2026-02-08T12:30:45.123456Z"
}
```

### `POST /jobs/poll`

Retorna a assignment pendente mais antiga (`ASSIGNED`) do worker.

**Request JSON**

- `worker_id` (int, obrigatório)

**Response JSON (200)**

- `assignment_id` (int)
- `job` (objeto JSON com payload do job)
- `nonce` (string anti-replay)
- `cost_hint_tokens` (int, usa prioridade do job)

**Erros e condições**

- `401 Invalid token`
- `403 Insufficient role`
- `404 Worker not found`: worker inexistente ou ownership inválido.
- `404 No assignment available`: sem assignment `ASSIGNED` disponível para o worker.

**Exemplo real**

```http
POST /jobs/poll
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "worker_id": 4
}
```

```json
{
  "assignment_id": 15,
  "job": {
    "prompt": "hello"
  },
  "nonce": "nonce-poll-1",
  "cost_hint_tokens": 99
}
```

### `POST /jobs/submit`

Submete resultado de assignment, valida assinatura do payload assinado, valida nonce e bloqueia replay.

**Request JSON**

- `worker_id` (int, obrigatório)
- `assignment_id` (int, obrigatório)
- `nonce` (string, obrigatório, 1..128)
- `signature` (string base64url Ed25519, obrigatório)
- `output` (objeto JSON | null)
- `error_message` (string | null)
- `artifact_uri` (string | null)
- `output_hash` (string | null, máx. 128)
- `metrics_json` (objeto JSON | null)

**Response JSON (200)**

- `assignment_id` (int)
- `status` (`completed` ou `failed`)
- `finished_at` (datetime ISO-8601)

**Erros e condições**

- `400 Worker public key is not configured`: worker sem chave pública para verificar assinatura.
- `400 Invalid public key encoding` / `Invalid public key length`: `public_key` persistida inválida.
- `400 Invalid signature encoding` / `Invalid signature length`: assinatura em formato inválido.
- `400 Signature verification failed`: assinatura Ed25519 válida em formato, porém não confere com o objeto assinado.
- `400 Invalid nonce`: `nonce` recebido difere da `nonce` atribuída à assignment.
- `401 Invalid token`
- `403 Insufficient role`
- `404 Worker not found`: worker inexistente ou ownership inválido.
- `404 Assignment not found`: assignment inexistente ou não pertence ao worker.
- `409 Assignment already submitted`: replay detectado (resultado já existe).
- `409 Assignment is not in a submittable state`: status da assignment não é `ASSIGNED`/`STARTED`.
- `409 Concurrent submission conflict`: conflito de concorrência na persistência.

**Exemplo real**

```http
POST /jobs/submit
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "worker_id": 4,
  "assignment_id": 15,
  "nonce": "nonce-submit-1",
  "signature": "K2xQ2i3-hwA1fjvml7I9T4fQY2uD-5E3nQfYQ9v8MEkTSZ6u7m9qfWf8N0U3G6asQ6IYl5j9v2pW4p3m6n8XDA",
  "output": {
    "ok": true
  },
  "output_hash": "hash-1"
}
```

```json
{
  "assignment_id": 15,
  "status": "completed",
  "finished_at": "2026-02-08T12:35:10.000000Z"
}
```

---

## Canonical JSON + Hash + Signature

### Algoritmo canônico

A serialização canônica usada no coordinator segue:

- JSON UTF-8
- ordem determinística de chaves (`sort_keys=true`)
- sem espaços extras (`separators=(",",":")`)
- preserva Unicode (`ensure_ascii=false`)

Em pseudocódigo:

```text
canonical_json(obj) = json.dumps(obj, sort_keys=true, separators=(",",":"), ensure_ascii=false).encode("utf-8")
sha256_hex(obj) = SHA256(canonical_json(obj)).hexdigest(lowercase)
```

### Objeto exato assinado no `POST /jobs/submit`

O runtime deve assinar **exatamente** este objeto (sem campos extras):

```json
{
  "assignment_id": 15,
  "nonce": "nonce-submit-1",
  "output_hash": "hash-1"
}
```

Regras:

1. Construir o objeto acima com os mesmos valores enviados no request.
2. Serializar com canonical JSON.
3. Assinar os bytes com chave privada Ed25519 do worker.
4. Enviar assinatura em `base64url` (padding opcional, servidor aceita sem padding).

### Relação entre `output` e `output_hash`

- O coordinator valida assinatura apenas sobre `assignment_id + nonce + output_hash`.
- O cálculo/consistência de `output_hash` com `output` deve ser garantido pelo runtime/chains externas.
- Recomendação operacional: usar `output_hash = sha256_hex(canonical_json(output))` para manter determinismo de ponta a ponta.

---

## Compatibilidade: `last_seen_at` vs `last_heartbeat_at`

Houve migração de esquema renomeando `workers.last_heartbeat_at` para `workers.last_seen_at`.

- Contrato atual de API expõe somente `last_seen_at`.
- Em migração gradual de clientes legados:
  - leitura: aceitar ambos no consumidor (`last_seen_at` preferencial; fallback para `last_heartbeat_at`);
  - escrita: enviar/esperar apenas `last_seen_at` no novo contrato;
  - observabilidade: dashboards/ETL devem mapear os dois nomes enquanto coexistirem dados legados.

Após término da migração, remover compatibilidade com `last_heartbeat_at`.
