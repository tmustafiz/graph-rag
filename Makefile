.PHONY: up down logs status install lint test

up:
	docker compose up -d neo4j

down:
	docker compose down

logs:
	docker compose logs -f neo4j

install:
	uv sync --all-extras

status:
	uv run graph-rag status

apply-schema:
	uv run graph-rag apply-schema

lint:
	uv run ruff check .

test:
	uv run pytest
