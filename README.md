# OpenMesh-AI

Monorepo base para um **pool operator** do ecossistema OpenMesh-AI.

## Visão geral

O operador coordena workers para executar tarefas de inferência/distribuição e expõe uma camada de gateway para consumo externo.

Componentes:

- `pool-coordinator/` — API interna para coordenação de jobs, workers e estado do pool.
- `pool-gateway/` — API de borda para clientes, autenticação e roteamento para o coordinator.
- `worker/` — CLI em Rust para registrar-se no pool, receber trabalho e reportar resultados.
- `docs/` — documentação de protocolo, economia e operações.
- `scripts/` — utilitários de desenvolvimento.

## Token de uso (usage token)

O `usage token` representa crédito/consumo de capacidade computacional:

- clientes apresentam token para consumir capacidade do pool;
- gateway valida e contabiliza consumo;
- coordinator aplica políticas de alocação e limites;
- worker executa tarefas e retorna métricas para liquidação.

> Nesta fase o token está documentado conceitualmente em `docs/economics.md`.

## Quickstart

```bash
make up
make logs
```

Healthchecks:

- Coordinator: `GET http://localhost:8001/health`
- Gateway: `GET http://localhost:8002/health`

## Desenvolvimento

```bash
make fmt
make lint
make test
```

## Licença

Apache-2.0 (`LICENSE`).
