# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `LICENSE` (Apache-2.0) and `NOTICE`; `license`, `keywords`, `classifiers`,
  and `[project.urls]` in `pyproject.toml`.
- `CONTRIBUTING.md` (with the code-convention rules), `CODE_OF_CONDUCT.md`,
  `SECURITY.md`.
- GitHub Actions CI (`ruff check`, `ruff format --check`, `pytest`),
  issue/PR templates, and Dependabot config.
- `py.typed` marker so downstream type checkers see the package's hints.
- `scripts/fetch_model.py` and `make fetch-model` for the local embedding model.

### Changed
- README restructured for first-time visitors (positioning, client setup
  snippets, tools table, architecture diagram).
- The embedding model is no longer vendored in git — fetch it with
  `make fetch-model` (falls back to a first-use Hub download otherwise).
- The repo ships no document corpus. `make ingest` now requires
  `INGEST_PATH` (`make ingest INGEST_PATH=…`); bring your own files.
- `graph-rag eval-retrieval` / `make eval` is self-contained: it ingests a
  small fixture corpus (`src/graph_rag/eval/corpus/`) before running, so it no
  longer depends on a specific document being ingested first. Added a CI job
  that runs it against a Neo4j service container.

### Removed
- Agent-instruction files (`CLAUDE.md`, `AGENTS.md`) are no longer tracked here;
  they live in a separate repository.
- `training-docs/` is no longer tracked. The three sample Checkov policies moved
  to `examples/checkov-policies/`; the bundled AWS PDFs are gone (also purged
  from git history).

## [0.1.0] - 2026-08-26

Initial implementation: phased Graph RAG pipeline (PDF / Markdown / Python /
YAML ingestion into Neo4j), hybrid vector + full-text retrieval, GDS PageRank
over the code graph, agent working-memory with decay pruning, and an MCP
server (Streamable HTTP) exposing lookup + memory tools. See
`docs/IMPLEMENTATION_PLAN.md` for the full phase history.

[Unreleased]: https://github.com/tmustafiz/graph-rag/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tmustafiz/graph-rag/releases/tag/v0.1.0
