# Operations

Guia operacional inicial.

## Rotinas

- subir stack local com `make up`
- acompanhar logs agregados com `make logs`
- abrir shell do Postgres com `make dbshell`
- resetar ambiente local (containers + volumes) com `make reset`
- derrubar stack com `make down`

## Healthchecks e Métricas

- `GET /health` no gateway (`:8002`) e coordinator (`:8001`)
- `GET /metrics` (formato Prometheus) quando `ENABLE_PROMETHEUS_METRICS=true`
  - gateway: `http://localhost:8002/metrics`
  - coordinator: `http://localhost:8001/metrics`

## Tracing e correlação (request_id)

- O gateway recebe/gera `X-Request-ID` por request e propaga para o coordinator via header e payload interno de criação de job.
- O coordinator mantém o `request_id` no payload do job e devolve ao worker no `poll`.
- O worker registra span `worker_job` com `request_id` e inclui o campo em `metrics_json` no resultado.

## Dashboards simples (exemplo)

### 1) Tráfego e latência por endpoint

Use as métricas:
- `http_requests_total{path,method}`
- `http_request_duration_seconds_sum{path,method}`

Sugestões de painéis:
- **RPS por endpoint**: `rate(http_requests_total[1m])`
- **Latência média por endpoint**: `rate(http_request_duration_seconds_sum[5m]) / rate(http_requests_total[5m])`

### 2) Correlação operacional por request_id

No agregador de logs (ex.: Loki/ELK), filtre por `request_id` para seguir o fluxo:
1. gateway request start/end
2. chamadas internas no coordinator
3. execução no worker (`worker_job`)

### 3) Erros e timeouts

- acompanhar logs `coordinator_create`, `coordinator_poll` e cancelamentos por timeout no gateway.
- alertar se houver aumento de `HTTP 503` (timeout de verificação) e `HTTP 429` (rate-limit).
