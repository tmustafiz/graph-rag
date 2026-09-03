# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- A multi-arch (`linux/amd64` + `linux/arm64`) runtime image published to
  `ghcr.io/tmustafiz/graph-rag` on every `vX.Y.Z` tag (new `image` job in
  `release.yml`). Tags: `X.Y.Z`, `X.Y`, `sha-…`, and `latest` for a
  non-prerelease release.
- Tracked agent configuration: `AGENTS.md` (cross-agent guide),
  `.github/copilot-instructions.md` (auto-loaded by GitHub Copilot),
  `.github/prompts/*.prompt.md` (setup / run / deploy / add-a-parser /
  cut-a-release recipes), and `.github/workflows/copilot-setup-steps.yml`
  (pre-provisions the Copilot coding agent's environment). `CLAUDE.md` and the
  editor rule-files stay in a separate repo.
- Published to PyPI as **`grag-mcp`** — `uvx grag-mcp` / `uv tool install grag-mcp` /
  `pipx install grag-mcp`, no clone needed. `.github/workflows/release.yml`
  builds and publishes via Trusted Publishing on a `vX.Y.Z` tag push.
  (The importable package stays `graph_rag`; the CLI command is `grag-mcp`.)
- CI job that builds the Docker image and scans it with Trivy, failing on
  fixable HIGH/CRITICAL CVEs. Also runs weekly so newly-disclosed CVEs against
  an unchanged image are caught.
- `grag-mcp serve-mcp --stdio` — serve the MCP server over stdio for clients
  that launch it as a subprocess (Claude Desktop, etc.). HTTP stays the default.
- `docs/ARCHITECTURE.md` (present-tense design + component map) and
  `docs/ROADMAP.md` (pointer to the GitHub project board / milestones).
- `.github/release.yml` so GitHub release notes are auto-categorized by label.
- `LICENSE` (Apache-2.0) and `NOTICE`; `license`, `keywords`, `classifiers`,
  and `[project.urls]` in `pyproject.toml`.
- `CONTRIBUTING.md` (with the code-convention rules), `CODE_OF_CONDUCT.md`,
  `SECURITY.md`.
- GitHub Actions CI (`ruff check`, `ruff format --check`, `pytest`),
  issue/PR templates, and Dependabot config.
- `py.typed` marker so downstream type checkers see the package's hints.
- `scripts/fetch_model.py` and `make fetch-model` for the local embedding model.

### Changed
- The Docker image bakes the embedding model in at `/opt/models/all-MiniLM-L6-v2`
  (the builder stage runs `scripts/fetch_model.py`), so `docker compose up` needs
  no `huggingface.co` access for embeddings. `SentenceTransformerEmbedder` now
  resolves the model via `GRAG_EMBEDDING_MODEL` (a directory or a Hub repo id) →
  the baked-in image copy → `models/` in a checkout → the Hub id, replacing a
  `Path(__file__).parents[4]` lookup that silently missed in the installed wheel
  layout and always fell through to the Hub.
- The PDF parser cuts section bodies at the `(page, y)` coordinates of the
  outline destinations instead of at page boundaries. Previously, when several
  headings shared a page, each leaf section re-extracted and re-embedded the
  whole page — on the sample FSx guide that was 46% of chunks byte-identical to
  another. It also drops recurring running headers/footers, NFKC-normalizes text
  (so `ﬁle` → `file`), keeps a parent heading's preamble instead of discarding
  it, and no longer produces an empty result for a PDF that has no outline.
- The YAML parser no longer fails a whole file when a Checkov policy has a
  non-scalar (list/dict) value where a string is expected — `name`, `category`,
  `severity`, `guideline`, and `provider` degrade to absent, and a policy whose
  `metadata.id` isn't a scalar falls back to generic chunking. `_is_checkov_policy`
  now also requires a `definition`, so unrelated YAML with a stray `metadata.id`
  isn't misrouted.
- All `docker compose` base images are overridable via `.env`
  (`NEO4J_IMAGE`, `BUILDER_IMAGE`, `RUNTIME_IMAGE`, `UV_IMAGE`) so
  restricted environments can build against an approved hardened registry
  (e.g. Docker Hardened Images) without editing tracked files. Defaults
  are unchanged. See docs/operations.md.
- The Neo4j service now runs unchanged on `dhi.io/neo4j:2026` (Docker
  Hardened Image): the healthcheck uses `cypher-shell` instead of `wget`,
  `NEO4J_PLUGINS` is overridable (set it empty for images with no
  `wget`/`awk`), and the plugins volume mounts at Neo4j's default plugin
  dir so preloaded APOC/GDS jars load without an entrypoint-written
  `server.directories.plugins`.
- The app image builds and runs on Docker Hardened Images end to end
  (`BUILDER_IMAGE=dhi.io/python:3-dev`, `RUNTIME_IMAGE=dhi.io/python:3`).
  The `Dockerfile` now chowns and `USER`s by numeric uid 65532 instead of
  the `nonroot` name so the runtime base is interchangeable; torch runs
  on `dhi.io/python:3` despite it having no system `libgomp` (the wheel
  bundles OpenMP).
- README restructured for first-time visitors (positioning, client setup
  snippets, tools table, architecture diagram).
- The embedding model is no longer vendored in git — fetch it with
  `make fetch-model` (falls back to a first-use Hub download otherwise).
- The repo ships no document corpus. `make ingest` now requires
  `INGEST_PATH` (`make ingest INGEST_PATH=…`); bring your own files.
- `grag-mcp eval-retrieval` / `make eval` is self-contained: it ingests a
  small fixture corpus (`src/graph_rag/eval/corpus/`) before running, so it no
  longer depends on a specific document being ingested first. Added a CI job
  that runs it against a Neo4j service container.
- The `Dockerfile` is now a multi-stage build: the app venv is built against a
  standalone CPython 3.13 and copied into `gcr.io/distroless/cc-debian13:nonroot`
  — no shell, no package manager, non-root by default. Base-OS High/Critical
  CVEs go from 2C/5H to 0; the runtime image scans clean at High/Critical.

### Removed
- `docs/IMPLEMENTATION_PLAN.md` and `docs/progress.md` — planning, roadmap, and
  release notes now live in GitHub Issues, Milestones, the project board, and
  Releases. Architecture that outlived the plan moved to `docs/ARCHITECTURE.md`.
- Agent-instruction files (`CLAUDE.md`, `AGENTS.md`) are no longer tracked here;
  they live in a separate repository.
- `training-docs/` is no longer tracked. The three sample Checkov policies moved
  to `examples/checkov-policies/`; the bundled AWS PDFs are gone (also purged
  from git history).

## [0.1.0] - 2026-08-26

Initial implementation: Graph RAG pipeline (PDF / Markdown / Python / YAML
ingestion into Neo4j), hybrid vector + full-text retrieval, GDS PageRank over
the code graph, agent working-memory with decay pruning, and an MCP server
(Streamable HTTP) exposing lookup + memory tools. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how it fits together.

[Unreleased]: https://github.com/tmustafiz/graph-rag/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tmustafiz/graph-rag/releases/tag/v0.1.0
