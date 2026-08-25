# Project Progress Log

Source of truth for project state across sessions. A new timestamped
entry is added at each significant checkpoint (phase complete, major
decision, or breakpoint) — most recent entry first. See
[docs/IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full
phased plan this log tracks progress against.

---

## 2026-08-25 12:58 EDT

[CHECKPOINT]

1. **Core Objective**: (unchanged) Graph RAG system, Neo4j-backed,
   heterogeneous doc ingestion, MCP lookup for coding agents.
2. **Completed Milestones**:
   - **Phase 2 (PDF ingestion) — complete and verified** against the
     real `training-docs/dms-ug.pdf` (1780 pages):
     - New `src/graph_rag/ingest/` modules, one class per file per
       project convention: `Source`/`Section`/`Chunk`/`ParsedDocument`
       (Pydantic v2 models), `PdfParser`, `Chunker`, `Embedder` (ABC)
       + `SentenceTransformerEmbedder`, `Enricher`. Hoisted through
       `ingest/__init__.py`'s `__all__` facade.
     - New `src/graph_rag/graph/graph_writer.py`: `GraphWriter` —
       idempotent Cypher upsert (`MERGE` throughout, batched
       `UNWIND` in batches of 500) for `Source`, `Section` (+
       `HAS_SECTION`/`PARENT_OF`), `Chunk` (+ `HAS_CHUNK`), and a
       full-document `NEXT` reading-order chain across chunks.
       Hoisted through `graph/__init__.py`.
     - `PdfParser` walks PyMuPDF's `doc.get_toc()` outline to build
       the `Section` hierarchy (breadcrumb + parent/child), extracts
       leaf-section body text by page range, and delegates to
       `Chunker` for ~400-word chunks (word count as a token-count
       approximation, no tokenizer dependency) with 15% overlap,
       never crossing a heading boundary.
     - New CLI command `graph-rag ingest <path>` (`.pdf`-only for
       now; validates extension, clear error otherwise) — parses,
       embeds, and writes in one pass. New `make ingest` target.
     - New tests: `tests/test_chunker.py` (5 tests — chunk sizing,
       overlap, empty input, order offset, content-hash determinism)
       and `tests/test_pdf_parser.py` (4 tests — hierarchy/breadcrumb
       construction, page-range computation, leaf detection, stable
       IDs), all pure/no live DB. 13/13 tests pass, `ruff` clean,
       `pyright` clean (incl. `reportDeprecated`).
   - **Real end-to-end run verified**: `graph-rag ingest
     training-docs/dms-ug.pdf` → 1500 sections, 1582 chunks written.
     Confirmed all three Phase 2 exit criteria directly:
     - Full guide ingested (1 `Source`, 1500 `Section`, 1582
       `Chunk` nodes; 1500 `HAS_SECTION`, 1473 `PARENT_OF`, 1582
       `HAS_CHUNK`, 1581 `NEXT` edges).
     - Walked `Source → Section → Chunk` and back up the breadcrumb
       for the plan's own example: `.../Selection rules in DMS
       Schema Conversion/Selection rules format` (page 176–177).
     - Vector-similarity query for "how do I create a replication
       instance" (the plan's Phase 3 example query) returned
       "Creating a replication instance" as the top hit, score 0.80.
     - Re-ran ingest a second time on the unchanged PDF: identical
       node/edge counts (no duplicates) — confirms the `MERGE`-based
       upsert is genuinely idempotent.
3. **Critical Context**:
   - **Embedding model changed from the plan's default**: this
     sandbox has no network egress to huggingface.co, so
     `BAAI/bge-small-en-v1.5` (the plan's stated default) can't be
     downloaded. Switched `SentenceTransformerEmbedder`'s default to
     `sentence-transformers/all-MiniLM-L6-v2`, which was already
     cached locally (`~/.cache/huggingface`) — also 384-dim, so no
     change needed to the Phase 1 vector index config
     (`settings.embedding_dimensions`/`embedding_similarity_function`
     already matched). `settings.py`'s comment updated accordingly.
     If ingesting on a machine with normal internet access, either
     model works; `Embedder`/`SentenceTransformerEmbedder(model_name=...)`
     is pluggable, so swapping back is a one-line change plus
     re-ingest (embeddings aren't portable across models).
   - Ingest was run with `HF_HUB_OFFLINE=1` to skip a slow/blocked
     network round-trip on model load — not required once the model
     is cached, but harmless to keep using locally.
   - `Chunk.id`/`Section.id` are deterministic
     (`{source_path}::s{index}` / `{section_id}::c{order}`), not
     content hashes — stable across re-ingestion of the same PDF
     structure, which is what makes the `MERGE`-based upsert
     idempotent. `content_hash` (sha256) is stored separately on both
     `Source` and `Chunk` for future change-detection (Phase 7).
   - `PdfParser`/`Chunker` are separate, composable classes (not
     merged) specifically so `Chunker` is reusable as-is by the
     Markdown/Python/YAML parsers in Phases 4–6, per the plan.
   - `GraphWriter` batches every `UNWIND` write at 500 rows — untested
     at much larger scale than this PDF, but cheap insurance against
     one oversized transaction on bigger future sources.
4. **Discarded Paths**:
   - Considered making `PdfParser` call `Chunker` implicitly via a
     combined return type — kept them fully decoupled instead
     (`Chunker.chunk(text, section_id, start_order, ...)` takes plain
     text) so Phase 4+ parsers can reuse `Chunker` without any
     PDF-specific coupling.
   - Considered adding `tiktoken` for exact token counts — skipped;
     word-count approximation is sufficient for chunk-boundary sizing
     and avoids an extra dependency for a non-critical metric.
5. **Next Step**: Phase 3 — MCP server v1 (Streamable HTTP,
   read-only `search`/`get_section`/`list_sources` tools) per
   `docs/IMPLEMENTATION_PLAN.md`. The DMS guide is now fully queryable
   in the graph, so this phase is what actually exposes it to a
   coding agent.

---

## 2026-08-25 11:47 EDT

- Fixed two IDE-reported (Pylance/`reportDeprecated` + `reportArgumentType`)
  issues the user flagged in `graph/client.py` and `graph/schema.py`.
  Root-caused via `uvx pyright --project <cfg with reportDeprecated:error>`
  pointed at `.venv` (plain `ruff check --select ALL` and default-mode
  `pyright` both missed these — pyright only surfaces `reportDeprecated`
  when explicitly enabled, which Pylance does by default in the IDE but
  the CLI does not).
  - `client.py`: `@contextmanager`-decorated `driver_session()` was
    annotated `-> Iterator[Driver]` — genuinely deprecated typing
    pattern; PEP-recommended form is `-> Generator[Driver]`. Fixed
    (`collections.abc.Generator` import, single type-arg form now
    valid per pyright's bundled typeshed).
  - `schema.py`: `apply_schema()`'s `session.run(statement)` failed
    `reportArgumentType` — neo4j's `Session.run()` wants
    `LiteralString | Query`, but `statement` was plain `str` once
    collected into `list[str]`. These strings are fixed,
    internally-authored DDL (never user input), so fixed with an
    explicit `typing.cast(LiteralString, statement)` at the call site
    rather than loosening the driver's type contract.
  - Swept the rest of `src/`/`tests/` with the same `reportDeprecated`
    config — no other instances found.
  - Verified: pyright (0 errors incl. `reportDeprecated`), `ruff check`
    clean, all 4 tests pass, and `graph-rag status` /
    `graph-rag apply-schema` still work against the live container.
  - Noted but **not** fixed (out of scope, flagged to user): a
    pre-existing `reportCallIssue` in `tests/test_settings.py:5` —
    `Settings(_env_file=None)` works at runtime via pydantic-settings'
    `**kwargs` but isn't visible to the type checker's stub.

---

## 2026-08-25 08:22 EDT

- Switched the Neo4j image per user request:
  `neo4j:5.24-community` → `neo4j:2026.07.1` (calendar-versioned
  release; unsuffixed tag is still Community edition — confirmed via
  `CALL dbms.components()` → `edition: 'community'`).
- `docker volume rm` on the old data/plugins volumes was blocked by
  the auto-mode permission classifier (destructive-action guard).
  Rather than working around it, did the non-destructive thing: kept
  the existing `neo4j_data` volume and started the new image directly
  against it (an in-place store upgrade), since the volume held only
  the empty schema from Phase 1 (0 nodes, verified before touching
  anything).
- Verified clean: container healthy within ~20s, no upgrade
  errors/warnings in logs (only benign default X-Forward-header and
  Java vector-incubator notices), `graph-rag status` connects,
  `graph-rag apply-schema` re-runs as a no-op, and all 6 constraints
  + the `chunk_embedding` vector index survived the switch intact.
- `docker-compose.yml` updated to `image: neo4j:2026.07.1`; no other
  files needed changes (nothing else hardcodes the version).

---

## 2026-08-24 17:26 EDT

[CHECKPOINT]

1. **Core Objective**: (unchanged) Graph RAG system, Neo4j-backed,
   heterogeneous doc ingestion, MCP lookup for coding agents.
2. **Completed Milestones**:
   - **Phase 1 (graph schema) — complete and verified**:
     - `src/graph_rag/graph/schema.py`: uniqueness constraints for all
       6 node types (`Source.path`, `Section.id`, `Chunk.id`,
       `CodeEntity.qualified_name`, `PolicyRule.id`, `Concept.name`),
       full-text indexes on `Chunk.text` and `Section.title`, and a
       native `VECTOR` index on `Chunk.embedding` (384 dims, cosine —
       matches the `bge-small-en-v1.5` default from Phase 0).
     - New CLI command `graph-rag apply-schema` (idempotent — reruns
       cleanly, verified twice against the live container).
     - New `Makefile` target `apply-schema`.
     - Applied against the live `graph-rag-neo4j` container and
       verified via `SHOW CONSTRAINTS` / `SHOW INDEXES`: 6 constraints,
       1 `VECTOR` index, 2 `FULLTEXT` indexes, plus the RANGE indexes
       Neo4j auto-creates to back each uniqueness constraint.
     - Added `tests/test_schema.py` (pure statement-generation checks,
       no live DB required); `ruff` clean, all 4 tests passing.
   - Side effect: `graph-rag` now has 2 commands (`status`,
     `apply-schema`), so Typer stopped collapsing to bare invocation —
     `graph-rag status` now works by name as originally intended.
     `Makefile`'s `status` target and `README.md` reverted to the
     `graph-rag status` form (the bare-invocation workaround noted in
     the 16:47 entry is no longer needed).
3. **Critical Context**:
   - `settings.embedding_dimensions` (384) / `embedding_similarity_function`
     (`cosine`) now drive the vector index definition — change these
     together with whatever embedding model Phase 2's `Enricher` ends
     up using, or the index dimensionality will mismatch the vectors
     written at ingest time.
   - Constraint/index names are stable, human-readable identifiers
     (e.g. `chunk_embedding`, `source_path`) — ingestion code and any
     future migration should refer to graph structure by label/property,
     not by re-deriving these names.
4. **Discarded Paths**: none this phase.
5. **Next Step**: Phase 2 — PDF ingestion pipeline for
   `training-docs/dms-ug.pdf`, using PyMuPDF's embedded outline/TOC to
   build the `Source` → `Section` (hierarchical) → `Chunk` graph, plus
   the `Enricher` (embedding generation) and idempotent upsert writer.

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
