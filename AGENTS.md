# AGENTS.md — cross-agent guide for graph-rag

The canonical guide for **any** AI coding agent (GitHub Copilot, Claude Code,
Cursor, …) working in this repository, and a useful summary for human
contributors. Tool-specific files defer to this one:

- [`.github/copilot-instructions.md`](.github/copilot-instructions.md) — the
  short, always-loaded version for GitHub Copilot.
- `CLAUDE.md` — Claude / Claude Code; adds context-compaction guidance.
- Task recipes: [`.github/prompts/`](.github/prompts) (Copilot prompt files).

Human contributors: [`CONTRIBUTING.md`](CONTRIBUTING.md) has setup + the PR
workflow. Design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Day-2 ops:
[`docs/operations.md`](docs/operations.md).

---

## What this project is

A local-first **Graph RAG knowledge base for coding agents**. It ingests the
heterogeneous material a coding agent needs — service docs (PDF), internal
Markdown, Python source, YAML policy files (Checkov) — into a single **Neo4j**
knowledge graph, and exposes it over an **MCP** server (Streamable HTTP, and
optionally stdio): hybrid vector + full-text search, table-of-contents
navigation, exact policy lookup, code-centrality ranking (GDS PageRank), graph
traversal, and the agent's own persistent working memory.

It runs entirely on the developer's machine. The default embedding model
(`sentence-transformers/all-MiniLM-L6-v2`) is local, so ingestion needs no API
key and works offline once the model is fetched.

Adding support for a new file type must be a small, isolated change — a new
parser class registered in the parser registry — never a rewrite.

---

## Names — keep them straight

| Thing | Value | Notes |
| --- | --- | --- |
| PyPI distribution + console command | **`grag-mcp`** | `graph-rag` was taken on PyPI |
| Python import package + `src/` directory | **`graph_rag`** | `from graph_rag.ingest import …` |
| GitHub repository | **`graph-rag`** | |
| MCP server identity | **`graph-rag`** | `MCPServer(name="graph-rag")`, resource URI `graph-rag://sources`, `claude mcp add graph-rag …` — **never rename** |

The CLI entry point is `graph_rag.cli:app`, run as `uv run grag-mcp <verb>` (or
`grag-mcp <verb>` when installed). `pyproject.toml` needs the explicit
`[tool.hatch.build.targets.wheel] packages = ["src/graph_rag"]` because the
distribution name no longer implies the package directory.

CLI verbs: `status`, `apply-schema`, `ingest [--watch] [--dry-run]`,
`serve-mcp [--stdio]`, `compute-centrality`, `prune-memory`, `eval-retrieval`.

---

## Working principles

### Think before coding
- State assumptions explicitly. Ask when the request is ambiguous.
- Multiple reasonable interpretations? Present them with tradeoffs — don't pick
  one silently.

### Simplicity first
- The minimum code that solves the problem. Nothing speculative.
- No abstractions for single-use code. No unrequested features.
- If 200 lines could be 50, rewrite it.

### Surgical changes
- Touch only what the task requires. Match the surrounding style.
- Don't refactor or reformat adjacent code that isn't broken.
- Remove only the dead code your own change created.

### Complete code, no false completion
- Complete, runnable code — never stubs, `TODO`s, or "omitted for brevity".
- Never claim completion without running the verification below.
- If blocked or something is unverified, say so plainly and give the exact
  command to verify.

---

## Python standards

- Python 3.12+, full type hints, Pydantic v2 for data that crosses a boundary
  (CLI ↔ pipeline ↔ MCP ↔ Neo4j).
- `ruff` for lint and formatting: `line-length = 100`, `target-version = py312`,
  rule set `E, F, I, UP, B`.
- `pathlib.Path`, not `os.path`. Specific exception types, not bare `except`.
- Dependency injection over module-level globals and singletons.
- Avoid single-letter variable names.
- Tests in `tests/`, run with `uv run pytest`.

## Code organization — one class per file

Strict "one class per file" architecture, mirroring Java package conventions
with Pythonic naming.

1. **File structure** — every primary class in its own module. Do not combine
   multiple primary classes in one file. Small helper dataclasses/enums used
   only by that class may live alongside it.
2. **Naming** — modules are `lower_snake_case`; classes are `PascalCase`; the
   filename is the class name converted to `snake_case`
   (`SentenceTransformerEmbedder` → `sentence_transformer_embedder.py`).
3. **Package facade** — every package has an `__init__.py` that imports its
   public classes from their submodules (`from .parser_registry import
   ParserRegistry`) and defines `__all__`.
4. **Import expectation** — consumers import from the package, not the
   submodule: `from graph_rag.ingest import ParserRegistry`.
5. **Internal deps** — explicit relative imports within a package
   (`from .other_file import OtherClass`) to keep the dependency graph clear and
   avoid cycles.

Apply this to all new code, refactors, and new directories.

---

## Repository layout

```
src/graph_rag/
  cli.py                     typer CLI (entry point graph_rag.cli:app → grag-mcp)
  settings.py                Pydantic-settings config (env-driven)
  ingest/                    parsers (PDF/Markdown/Python/YAML), registry, chunker
  ingestion_pipeline.py      parse → chunk → embed → write, idempotent by content hash
  graph/                     Neo4j schema, writers, centrality_analyzer (GDS PageRank)
  mcp_server/                build_server (tools + resources), retriever, models
  memory/                    AgentMemory write / recall / decay-pruning
  http_app.py                FastAPI app mounted beside MCP; POST /ingest
  eval/                      retrieval eval set + evaluator + fixture corpus
tests/                       pytest
docs/                        ARCHITECTURE.md, operations.md, ROADMAP.md
examples/checkov-policies/   the only sample data that ships
scripts/fetch_model.py       downloads the embedding model into models/
Dockerfile                   multi-stage: builder venv → distroless/cc runtime
docker-compose.yml           neo4j + mcp-server
```

---

## Environment & running

Requires [`uv`](https://docs.astral.sh/uv/) and Docker.

```bash
cp .env.example .env         # adjust NEO4J_PASSWORD if you like
make install                 # uv sync --all-extras
make fetch-model             # embedding model → models/all-MiniLM-L6-v2/ (~87 MB)
make up                      # start Neo4j (Docker); APOC + GDS auto-install
make apply-schema            # constraints + full-text + vector indexes
make ingest INGEST_PATH=examples/checkov-policies
make mcp-serve               # MCP server on http://127.0.0.1:8765/mcp
```

Or the whole stack: `docker compose up -d`. Other targets: `make down`,
`make lint`, `make format`, `make test`, `make eval`, `make logs`, `make status`.

Key env vars (see `.env.example` and `src/graph_rag/settings.py`):
`NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD`, `MCP_HOST` / `MCP_PORT` /
`MCP_AUTH_TOKEN`, and the Docker base-image overrides `NEO4J_IMAGE`,
`BUILDER_IMAGE`, `RUNTIME_IMAGE`, `UV_IMAGE`.

`HF_HUB_OFFLINE=1` makes ingestion/tests use the on-disk model only (no network).

---

## Verification — run before you hand back

```bash
make lint                       # ruff check .
uv run ruff format --check .    # formatting
make test                       # pytest
make eval                       # ONLY if you touched chunking / embedding / ranking (needs Neo4j)
```

CI (`.github/workflows/ci.yml`) on every PR: `lint` (ruff check + format check),
`test` (pytest on 3.12 and 3.13), `eval` (retrieval eval against a Neo4j service
container), `image` (build the Docker image, Trivy-scan it, fail on fixable
HIGH/CRITICAL).

---

## Planning, branches, PRs

Planning lives on **GitHub**, not in a repo file — the Project board,
milestones, and issues. Workflow for an agent:

1. Work against an existing issue, or open one (`gh issue create`).
2. For anything non-trivial, post a `[CHECKPOINT]` comment on that issue/PR
   **before** starting:
   ```
   [CHECKPOINT]
   1. Objective: <one sentence>
   2. Done & verified: <what's implemented, with the commands that proved it>
   3. Critical context: <decisions, config, module/variable names, patterns to preserve>
   4. Discarded paths: <approaches tried and rejected>
   5. Next step: <exactly what comes next>
   ```
   Convert relative dates to absolute. Keep the "why" (decisions, tradeoffs) in
   the issue/PR so it survives a context reset.
3. Branch from `main`. Never commit or push to `main` directly.
4. Open a PR whose body has `Closes #<n>`. Keep the diff scoped to the issue.
5. The **repo owner merges** PRs and deletes branches — don't self-merge.
6. Update `CHANGELOG.md` (`[Unreleased]`) for anything user-visible.

---

## Security & things not to break

- **Never commit `.env`** — it's gitignored. Only `.env.example` is tracked, and
  its placeholder password is `changeme-local-dev`.
- The MCP server binds `127.0.0.1` only. Origin / DNS-rebinding protection is
  always on (`TransportSecuritySettings` in `cli.py`). `MCP_AUTH_TOKEN`
  (optional) adds a bearer-token check. Do not weaken any of these or bind to
  `0.0.0.0` on the host side. See [`SECURITY.md`](SECURITY.md).
- Base images (`NEO4J_IMAGE`, `BUILDER_IMAGE`, `RUNTIME_IMAGE`, `UV_IMAGE`) must
  stay overridable, with the current **public** defaults. Hardened-registry
  (Docker Hardened Images, etc.) guidance is in `docs/operations.md`.
- The runtime Docker image is distroless (no shell) and runs as uid 65532 —
  keep it non-root and shell-free.
- The `[pdf]` extra pulls in PyMuPDF (AGPL). The base install must stay
  Apache-2.0-only: import `pymupdf` lazily inside the PDF parser, never at
  module top.
- The repo ships **no document corpus**. `examples/checkov-policies/` (three
  small samples) is the only tracked data.
- Don't add the embedding model back into git — it's fetched with
  `make fetch-model` and `models/` is gitignored.

---

## Response format

When reporting a change:

```
**What changed**
- <file>: <what and why>

**Verification run**
- <command> → <result>

**Remaining issues / risks**
- <list or "None">
```
