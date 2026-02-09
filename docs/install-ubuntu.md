# Tutorial de instalação (Ubuntu)

Este guia cobre a instalação e execução do **OpenMesh-AI** em Ubuntu 22.04+ usando Docker.

## 1) Pré-requisitos

Instale os pacotes base:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git make
```

## 2) Instalar Docker Engine + Docker Compose

```bash
# chave GPG
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# repositório
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# instalação
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Valide a instalação:

```bash
docker --version
docker compose version
```

## 3) Permissão para usar Docker sem sudo (opcional)

```bash
sudo usermod -aG docker $USER
newgrp docker
```

> Se preferir, abra uma nova sessão de terminal após o comando `usermod`.

## 4) Clonar o repositório

```bash
git clone https://github.com/<seu-org-ou-fork>/OpenMesh-AI.git
cd OpenMesh-AI
```

## 5) Subir os serviços

```bash
make up
```

Esse comando sobe:

- `postgres` (porta `5432`)
- `redis` (porta `6379`)
- `pool-coordinator` (porta `8001`)
- `pool-gateway` (porta `8002`)

## 6) Verificar saúde dos serviços

```bash
curl -fsS http://localhost:8001/health
curl -fsS http://localhost:8002/health
```

Acompanhar logs em tempo real:

```bash
make logs
```

## 7) Comandos úteis

```bash
make down    # parar stack
make reset   # recriar stack e volumes
make dbshell # abrir psql no postgres
```

## 8) Desenvolvimento local (opcional)

Para executar formatação, lint e testes, você precisará também de Python 3.11+ e Rust:

```bash
make fmt
make lint
make test
```

## Troubleshooting rápido

- **Porta ocupada**: ajuste mapeamentos no `docker-compose.yml`.
- **Permissão no Docker**: confirme se seu usuário está no grupo `docker` (`groups $USER`).
- **Falha de healthcheck**: verifique logs com `make logs` e aguarde inicialização do Postgres/Redis.
