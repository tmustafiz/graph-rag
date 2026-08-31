.PHONY: up down logs status install lint format test ingest mcp-serve eval fetch-model

up:
	docker compose up -d neo4j

fetch-model:
	uv run python scripts/fetch_model.py

down:
	docker compose down

logs:
	docker compose logs -f neo4j

install:
	uv sync --all-extras

status:
	uv run grag-mcp status

apply-schema:
	uv run grag-mcp apply-schema

# Bring your own documents: make ingest INGEST_PATH=/path/to/your/docs
ingest:
	@test -n "$(INGEST_PATH)" || { \
		echo "Set INGEST_PATH to the file or directory to ingest, e.g.:"; \
		echo "  make ingest INGEST_PATH=~/my-docs"; \
		echo "  make ingest INGEST_PATH=examples/checkov-policies"; \
		exit 2; }
	uv run grag-mcp ingest "$(INGEST_PATH)"

mcp-serve:
	uv run grag-mcp serve-mcp

eval:
	uv run grag-mcp eval-retrieval

lint:
	uv run ruff check .

format:
	uv run ruff format .

test:
	uv run pytest
