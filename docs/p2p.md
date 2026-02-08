# P2P Federation (MVP)

## Objetivo
Implementar **pool-to-pool federation** para permitir que um coordinator encaminhe jobs para outro pool quando estiver sem capacidade local.

## Escopo do MVP
- Descoberta por **allowlist** (sem DHT).
- Autenticação por **shared_secret** por peer.
- Registro de peers em tabela local (`peers`).
- Endpoints:
  - `POST /p2p/peers/register`
  - `POST /p2p/jobs/forward`
  - `POST /p2p/results/relay`
- Registro financeiro placeholder em ledger: `entry_type = "interpool_fee"`.

## Modelo de dados
Tabela `peers`:
- `peer_id` (único)
- `url`
- `shared_secret`
- `last_seen`

## Fluxo
1. Peer remoto chama `POST /p2p/peers/register` com `peer_id + shared_secret + url`.
2. Coordinator valida allowlist + secret e atualiza `last_seen`.
3. Quando um pool precisa terceirizar trabalho, chama `POST /p2p/jobs/forward` no peer destino.
4. Pool destino aceita apenas se tiver capacidade local disponível.
5. Após execução, resultado pode voltar com `POST /p2p/results/relay`.

## Segurança
- `peer_id` precisa estar previamente allowlisted na tabela `peers`.
- `shared_secret` é validado com comparação constante (`compare_digest`).
- Sem DHT e sem auto-discovery nesse estágio.

## Ledger (placeholder)
Cada forwarding/relay grava no ledger uma linha com:
- `entry_type: interpool_fee`
- `amount: 0`
- metadados de direção (`inbound_forward`, `result_relay`) e peer.

> Valor financeiro real será definido em versão futura.
