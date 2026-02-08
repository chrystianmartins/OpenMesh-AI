.PHONY: up down logs dbshell reset fmt lint test migrate seed

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f pool-gateway pool-coordinator worker postgres redis

dbshell:
	docker compose exec postgres psql -U openmesh -d openmesh

reset:
	docker compose down -v --remove-orphans
	docker compose up -d --build

fmt:
	cd pool-coordinator && python -m ruff format .
	cd pool-gateway && python -m ruff format .
	cd worker && cargo fmt

lint:
	cd pool-coordinator && python -m ruff check . && python -m mypy app
	cd pool-gateway && python -m ruff check . && python -m mypy app
	cd worker && cargo clippy -- -D warnings

test:
	cd pool-coordinator && python -m pytest
	cd pool-gateway && python -m pytest
	cd worker && cargo test

migrate:
	@echo "No migrations yet (placeholder for Alembic/sqlx)."

seed:
	@echo "No seed data yet (placeholder)."
