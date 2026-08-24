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
	# `graph-rag status` becomes the real subcommand form once a second
	# command (e.g. `ingest`, Phase 2) exists; Typer collapses a single
	# command to bare invocation until then.
	uv run graph-rag

lint:
	uv run ruff check .

test:
	uv run pytest
