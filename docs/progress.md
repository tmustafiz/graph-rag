# Project Progress Log

Source of truth for project state across sessions. A new timestamped
entry is added at each significant checkpoint (phase complete, major
decision, or breakpoint) — most recent entry first. See
[docs/IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full
phased plan this log tracks progress against.

---

## 2026-08-24 17:22 EDT

- Reverted the previous move: `.claude/IMPLEMENTATION_PLAN.md` →
  `docs/IMPLEMENTATION_PLAN.md`. User wants the plan version-controlled,
  so it stays under `docs/` (tracked) rather than `.claude/`
  (gitignored). References in `README.md` and this file updated back
  to `docs/IMPLEMENTATION_PLAN.md`.

---

## 2026-08-24 17:20 EDT

- Moved the implementation plan: `docs/IMPLEMENTATION_PLAN.md` →
  `.claude/IMPLEMENTATION_PLAN.md` (per user request). Updated the
  reference in `README.md` and the one at the top of this file.
- **Flag**: `.claude/` is listed in `.gitignore` (added in Phase 0 as
  "local tooling state"), so the plan is now untracked by git — it
  will not be committed or visible to anyone cloning the repo. This
  was true before the move too (nothing has been committed yet), but
  worth surfacing in case the plan should stay version-controlled
  going forward — say so and I'll either un-ignore this one file or
  move it back under `docs/`.

---

## 2026-08-24 16:47 EDT

[CHECKPOINT]

1. **Core Objective**: Build a Graph RAG system, backed by Neo4j, that
   ingests heterogeneous docs (PDF, Markdown, Python, YAML/Checkov
   policies) with context-aware/structure-aware chunking, and exposes
   lookup to coding agents via an MCP server (Streamable HTTP
   transport).
2. **Completed Milestones**:
   - `docs/IMPLEMENTATION_PLAN.md` written: 11 phases (0–10), with
     Mermaid architecture / phase-roadmap / graph-schema / MCP
     sequence diagrams.
   - **Phase 0 (scaffolding) — complete and verified**:
     - uv-managed package: `src/graph_rag/{ingest,graph,mcp_server}/`,
       `cli.py`, `settings.py`.
     - `pyproject.toml`: `neo4j`, `typer`, `pydantic-settings` core
       deps; `pymupdf` under a `pdf` extra staged for Phase 2;
       `ruff` + `pytest` dev deps.
     - `docker-compose.yml`: `neo4j:5.24-community` + APOC, bound to
       `127.0.0.1` only on 7474/7687, with healthcheck.
     - CLI `graph-rag` connects to Neo4j via the bolt driver —
       verified output: "Neo4j is reachable."
     - `Makefile` (up/down/install/status/lint/test), `.env.example`,
       `README.md`.
     - `ruff check` clean; smoke test (`tests/test_settings.py`)
       passing.
   - Git repo initialized at project root. No commits made yet (none
     requested).
   - `.gitignore` expanded to cover `.venv`, `.env`, Python build
     artifacts, test/lint/type caches (`.pytest_cache/`,
     `.ruff_cache/`, `.mypy_cache/`, `.coverage`, `htmlcov/`), editor
     dirs (`.vscode/`, `.idea/`), `*.log`, and `.claude/` (local
     tooling state).
3. **Critical Context** (decisions that must survive context loss):
   - **MCP transport = Streamable HTTP**, not stdio — runs as a
     long-lived `docker-compose` service (added in Phase 3), bound to
     `127.0.0.1`, with `Origin` header validation and an optional
     bearer token. Rationale: one warm process can serve multiple
     agent sessions without reloading the embedding model per spawn.
     Full detail in `IMPLEMENTATION_PLAN.md` Phase 3.
   - **Embeddings default**: local `sentence-transformers` model
     (offline-friendly, no API key required), behind a pluggable
     `Embedder` interface so it can be swapped for a hosted provider
     later.
   - **PDF source** (`training-docs/dms-ug.pdf`, AWS DMS User Guide,
     1780 pages) has an embedded TOC/outline — Phase 2's `PdfParser`
     will read PyMuPDF's outline API directly for heading-hierarchy
     chunking, falling back to font-size heuristics only for PDFs
     without an embedded outline.
   - **Typer quirk**: with only one `@app.command()` registered,
     `graph-rag` collapses to bare invocation (no `status` subcommand
     name) — resolves naturally once a second command (`ingest`,
     Phase 2) is added. `Makefile`'s `status` target and `README.md`
     were written to match today's bare-invocation reality; revisit
     once `ingest` lands.
   - First `docker compose up -d neo4j` took ~10 minutes end-to-end
     due to a slow image pull on this network (confirmed via
     `docker events` + task log, not a config/sandbox problem) — not
     a reason for concern if it recurs on a clean machine.
4. **Discarded Paths**:
   - Considered stdio for MCP transport (simpler, no port/lifecycle
     management) — rejected per explicit user preference for HTTP,
     see Critical Context above.
5. **Next Step**: Phase 1 — graph schema. Define constraints/indexes
   (including the native vector index on `Chunk.embedding`) in
   `src/graph_rag/graph/schema.py`, matching the node/relationship
   taxonomy already documented in `IMPLEMENTATION_PLAN.md` Phase 1.

---

## 2026-08-24 ~15:50–16:00 EDT — housekeeping (folded into checkpoint above)

- Found two files not created by this session and flagged them to the
  user rather than acting unilaterally: a `CLAUDE.md` describing an
  unrelated "Project Octopus" monorepo, and a nested
  `graph-rag/graph-rag/` directory containing its own empty
  git + git-lfs repo. Neither matched any command run in this
  session.
- User removed `graph-rag/graph-rag/` themselves; asked to leave
  `CLAUDE.md` as-is for now. Both resolved — no outstanding action.
