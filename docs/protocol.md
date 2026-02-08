# Protocol

Especifica o protocolo de comunicação entre gateway, coordinator e workers.

## Entidades

- Client
- Pool Gateway
- Pool Coordinator
- Worker

## Fluxo alto nível

1. Client envia requisição ao Gateway.
2. Gateway valida autenticação/token e encaminha ao Coordinator.
3. Coordinator agenda tarefa para um Worker elegível.
4. Worker processa e retorna resultado/telemetria.
