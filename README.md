# OpenMesh-AI

Base monorepo for a **pool operator** in the OpenMesh-AI ecosystem.

## Overview

The operator coordinates workers to execute inference/distribution tasks
and exposes a gateway layer for external consumption.

Components:

-   `pool-coordinator/` --- Internal API for job orchestration, workers,
    and pool state.
-   `pool-gateway/` --- Edge API for clients, authentication, and
    routing to the coordinator.
-   `worker/` --- Rust CLI to register with the pool, receive work, and
    report results.
-   `docs/` --- Protocol, economics, and operations documentation.
-   Ubuntu installation guide: `docs/install-ubuntu.md`
-   Operational tutorial (pt-BR): `docs/tutorial-operacao-ptbr.md`
-   `scripts/` --- Development utilities.

## Usage Token

The `usage token` represents credit / consumption of compute capacity:

-   clients present a token to consume pool capacity;
-   the gateway validates and accounts for usage;
-   the coordinator applies allocation policies and limits;
-   the worker executes tasks and returns metrics for settlement.

> At this stage the token is documented conceptually in
> `docs/economics.md`.

## Quickstart

``` bash
make up
make logs
```

Health checks:

-   Coordinator: `GET http://localhost:8001/health`
-   Gateway: `GET http://localhost:8002/health`

## Development

``` bash
make fmt
make lint
make test
```

## License

Apache-2.0 (`LICENSE`).
