.PHONY: up down logs status install lint test ingest mcp-serve eval

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

ingest:
	uv run graph-rag ingest training-docs/dms-ug.pdf

mcp-serve:
	uv run graph-rag serve-mcp

eval:
	uv run graph-rag eval-retrieval

lint:
	uv run ruff check .

test:
	uv run pytest
