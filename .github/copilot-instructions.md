# GitHub Copilot instructions — graph-rag

These rules are prepended to every Copilot request in this repo. The full
reference is [`AGENTS.md`](../AGENTS.md); this file is the short version.

## What this project is

A local-first **Graph RAG knowledge base for coding agents**. It ingests
PDF / Markdown / Python / YAML(Checkov) into a **Neo4j** knowledge graph and
serves hybrid retrieval + the agent's own working memory over an **MCP** server
(Streamable HTTP, default `http://127.0.0.1:8765/mcp`). Runs entirely locally;
the embedding model is local.

## Names — do not mix these up

| Thing | Value |
| --- | --- |
| PyPI distribution + CLI command | `grag-mcp` |
| Python import package + `src/` dir | `graph_rag` |
| GitHub repo | `graph-rag` |
| MCP server identity (`MCPServer(name=…)`, `graph-rag://sources`) | `graph-rag` — never rename |

CLI is invoked as `uv run grag-mcp <verb>` (or `grag-mcp <verb>` once installed).
Verbs: `status`, `apply-schema`, `ingest`, `serve-mcp` (`--stdio` for stdio
transport, `--role knowledge|memory|all` — default `all` — for a split
deployment), `compute-centrality`, `prune-memory`, `eval-retrieval`.

## How to work

- **Think first.** State assumptions. If the request has multiple reasonable
  readings, present them — don't silently pick one.
- **Simplest thing that works.** No speculative abstractions, no unrequested
  features. If 200 lines could be 50, write 50.
- **Surgical diffs.** Touch only what the task needs. Don't reformat or refactor
  adjacent code. Remove only dead code your change created.
- **No false completion.** Complete, runnable code — never stubs or `TODO`.
  Never say "done" without running the verification below. If blocked, say so
  and give the exact command to check.

## Python standards

- Python 3.12+, full type hints, Pydantic v2 for data crossing a boundary.
- `ruff` for lint + format (`line-length = 100`, rules `E,F,I,UP,B`).
- `pathlib.Path`, not `os.path`. Specific exception types, not bare `except`.
- Dependency injection over module-level globals/singletons.
- Avoid single-letter names.

## One class per file (strict)

- Every primary class in its own `lower_snake_case.py`; filename is the class
  name in snake_case (`ParserRegistry` → `parser_registry.py`). Small helper
  dataclasses/enums used only by that class may sit alongside it.
- Every package has an `__init__.py` that re-exports its public classes
  (`from .parser_registry import ParserRegistry`) and defines `__all__`.
- Consumers import from the package (`from graph_rag.ingest import ParserRegistry`),
  never the submodule. Within a package use relative imports (`from .x import X`).
- A new file type = a new self-contained parser class registered in the registry.
  Never a rewrite of the pipeline.

## Verification — run before handing back

```bash
make lint                    # uv run ruff check .
uv run ruff format --check .
make test                    # uv run pytest
make eval                    # ONLY if you touched chunking / embedding / ranking (needs Neo4j)
```

CI (`.github/workflows/ci.yml`) runs the first three on every PR, plus the
retrieval eval and a Trivy scan of the Docker image.

## Planning & PRs

Planning lives on **GitHub**, not in the repo — Project board, milestones,
issues. Branch from `main`, open a PR that says `Closes #<n>`, and let the repo
owner merge and delete the branch. For a non-trivial task, post a `[CHECKPOINT]`
comment on the issue/PR before starting (objective / done & verified / critical
context / discarded paths / next step).

## Don't break these

- **Never commit `.env`** (gitignored). Only `.env.example` is tracked; its
  placeholder password is `changeme-local-dev`.
- The MCP server binds `127.0.0.1` only; origin / DNS-rebinding checks are
  always on; `MCP_AUTH_TOKEN` (optional) adds a bearer check. Don't loosen these.
- `NEO4J_IMAGE`, `BUILDER_IMAGE`, `RUNTIME_IMAGE`, `UV_IMAGE` are overridable for
  hardened-registry environments — keep the public defaults, keep them
  overridable. See [`docs/operations.md`](../docs/operations.md).
- Neo4j needs the **APOC + GDS** plugins. The stock `neo4j` image auto-installs
  them from `NEO4J_PLUGINS` in `docker-compose.yml`; hardened images need them
  preloaded (see operations.md).
- The repo ships **no document corpus**. `examples/` holds a tiny Checkov sample
  set — that's it.

## Report back in this format

```
**What changed**
- <file>: <what and why>

**Verification run**
- <command> → <result>

**Remaining issues / risks**
- <list or "None">
```
