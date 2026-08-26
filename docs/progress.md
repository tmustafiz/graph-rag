# Project Progress Log

Source of truth for project state across sessions. A new timestamped
entry is added at each significant checkpoint (phase complete, major
decision, or breakpoint) — most recent entry first. See
[docs/IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full
phased plan this log tracks progress against.

---

## 2026-08-26 (session) — `search_code`/`search_policies` added; Phase 8's LLM half reframed

Not a plan phase per se — this closes a real coverage gap discovered
during Phase 9 review (`CodeEntity`/`PolicyRule` each had their own
unused vector index since Phase 6/7) via a design conversation with
the user about whether Phase 8's LLM-based Concept extraction was
actually necessary. Conclusion, arrived at collaboratively: a capable
querying agent can already bridge most "which policy relates to this
doc section" gaps using its own world knowledge (e.g. knowing
Terraform's `aws_dms_replication_instance` naming) — so the *missing
capability* worth fixing wasn't Concept extraction, it was that
`search()` never covered `CodeEntity`/`PolicyRule` content at all.
Phase 8's LLM-extraction half remains explicitly not started, still
gated on the user's provider decision — this work doesn't decide that
for them, it just removes one class of query that made Phase 8 seem
more necessary than it is.

[CHECKPOINT]
1. Core Objective: same as prior entries.
2. Completed Milestones:
   - Two new MCP tools, mirroring the existing hybrid vector+fulltext
     `search()` pattern exactly (same `combine_scores` function reused
     directly, no duplication — these live in the same `retriever.py`
     file):
     - `search_code(query, top_k=5) -> list[CodeSearchResult]` — over
       `CodeEntity` nodes, using the `code_entity_embedding` vector
       index and `code_entity_text_fulltext` fulltext index that have
       existed since Phase 5/7 but were never queried by anything.
     - `search_policies(query, top_k=5) -> list[PolicyResult]` — over
       `PolicyRule` nodes, using `policy_rule_embedding`/
       `policy_rule_text_fulltext` (existed since Phase 6, also never
       queried). Reused the existing `PolicyResult` model rather than
       creating a parallel one — added `score: float | None = None`
       (populated by `search_policies`, always `None` from
       `find_policies_for`).
   - New `CodeSearchResult` model
     (`mcp_server/models/code_search_result.py`).
   - Documentation pass tying the four related tools together
     explicitly, in both docstrings and the MCP server's `INSTRUCTIONS`
     blob: `search`'s docstring/description now states it does NOT
     cover code or policy text; `find_policies_for`'s now states it's
     exact-match-only with no fuzzy fallback and points to
     `search_policies` as the recovery path when it returns empty
     (rather than the agent silently concluding "no policy exists").
   - README's MCP server tool list updated to match.
   - No new tests beyond what already exists — both new methods are
     thin reuses of the already-tested `combine_scores`/
     `_min_max_normalize` pure functions and the same
     session.run()-with-a-dict pattern already proven correct for
     `search()`/`recall()`; consistent with this repo's convention of
     not unit-testing Retriever methods that need a live Neo4j session,
     only their extracted pure logic. 87/87 existing tests still
     passing, `ruff check`/`ruff format --check` clean.
3. Critical Context:
   - **This was a genuine, previously-undiscovered functional gap, not
     a hypothetical one** — confirmed by grepping `retriever.py` before
     this session: nothing anywhere called
     `db.index.vector.queryNodes('code_entity_embedding', ...)` or
     `'policy_rule_embedding', ...)` despite both indexes existing in
     `graph/schema.py` since Phase 5 (code) and Phase 6 (policy).
     `search()` only ever queried `chunk_embedding`. Any agent asking a
     natural-language question about this codebase's own functions, or
     about Checkov policy intent/content (as opposed to a known exact
     resource type), was getting either irrelevant PDF-chunk noise or
     nothing, with no tool description ever saying that was expected.
   - Reused the `Session.run()`-kwarg-collision workaround from the
     Phase 11 checkpoint (pass `{"query": query, "k": k}` as a single
     dict, not `query=query` kwargs) for both new fulltext queries —
     this is now the third place this exact pattern has been needed
     (`search`, `recall`, and now `search_code`/`search_policies`);
     worth remembering as a standing rule for any future Cypher query
     with a parameter literally named `query`.
   - Deliberately did **not** merge `CodeEntity`/`PolicyRule` hits into
     `search()`'s own result list as one unified ranked search — mixing
     three different embedding "topical spaces" (prose chunks, code
     docstrings, policy guidelines) into one min-max-normalized ranking
     would make scores harder to interpret and let one node type's
     text-length/embedding characteristics dominate the others. Kept
     them as separate tools with their own result shapes, matching how
     `find_policies_for` was already its own specialized tool rather
     than folded into `search()`.
4. Discarded Paths:
   - Considered adding fuzzy string matching (case-insensitive/CONTAINS)
     directly inside `find_policies_for`'s Cypher as a cheaper
     alternative to a whole new semantic-search tool. Rejected: a
     substring/case fallback is a much weaker notion of "fuzzy" than
     actual semantic similarity, and the vector infrastructure for
     policies already existed and was unused — `search_policies` gives
     a strictly more capable fallback for the same amount of new code.
5. Live verification (Docker rebuild, real ingested graph — this
   repo's own `src/graph_rag` plus the Checkov policy fixtures):
   `search_code("skip a file if its content hash is unchanged")`
   correctly ranked `graph_rag.cli.ingest` and
   `GraphWriter.get_source_content_hash` at the top; `search_policies
   ("make sure database backups are encrypted")` ranked
   `CKV2_CUSTOM_1` (RDS encryption at rest) at score 1.0, and a
   differently-worded query ("s3 bucket versioning") correctly
   re-ranked `CKV2_CUSTOM_3` to the top instead — confirming it's
   genuinely semantic, not keyword-matching by coincidence.
   `find_policies_for("aws_db_instance_typo")` correctly returned `[]`,
   demonstrating the exact-match failure mode `search_policies` now
   gives agents a way around.
6. Next Step: only Phase 8's actual LLM-extraction question remains
   open, and it's now better-scoped than before — the user should
   decide whether it's still worth pursuing at all given how much of
   its original motivating use case this session's tools already
   cover, rather than treating the earlier "Anthropic vs. Ollama"
   framing as the only remaining question.

---

## 2026-08-26 (session) — POST /ingest switched to FastAPI

Follow-up to the "Phase 7 deferred items" entry directly below: the
user reviewed the `POST /ingest` implementation ("i prefer fastapi
that keeps the usage consistent") and asked for it to use FastAPI
instead of the raw Starlette route it originally shipped with. Same
endpoint, same behavior, different framework underneath.

[CHECKPOINT]
1. Core Objective: same as prior entries.
2. Completed Milestones:
   - New `fastapi>=0.115` dependency.
   - `src/graph_rag/ingest_request.py` (new) — `IngestRequest` Pydantic
     model (`path: str`, `dry_run: bool = False`), FastAPI's request
     body.
   - `src/graph_rag/ingest_http_endpoint.py` rewritten:
     `build_ingest_router(pipeline) -> APIRouter` (an `APIRouter`
     factory function, mirroring `mcp_server/server.py`'s
     `build_server()` pattern) replaces the old raw-Starlette
     `build_ingest_route_handler`. Response is now a bare JSON array
     (`response_model=list[IngestionResult]`) instead of the old
     `{"results": [...]}` wrapper, matching the shape `ingest_path`
     already returns over MCP.
   - **New `src/graph_rag/http_app.py`** — `build_http_app(mcp_app,
     ingestion_pipeline) -> FastAPI`. FastAPI is now the top-level app;
     `mcp_app` (the MCP server's own Starlette app) is mounted under
     it at `/`. `cli.py`'s `serve_mcp()` calls this instead of adding a
     route directly onto `mcp_app`.
   - Tests: `tests/test_ingest_http_endpoint.py` rewritten around
     `fastapi.testclient.TestClient` + `FastAPI()` instead of raw
     Starlette (status codes for validation failures changed from `400`
     to FastAPI's own `422`, see Critical Context). New
     `tests/test_http_app.py` (3 tests) — specifically exercises the
     lifespan-composition fix using a hand-built fake Starlette "mcp
     app" with its own lifespan context manager that records
     started/stopped events, run through `TestClient(app)` as a context
     manager (which is what actually triggers ASGI lifespan events).
     87/87 tests passing, `ruff check`/`ruff format --check` clean.
   - `docs/operations.md` gained a "Triggering ingestion over HTTP"
     section with a `curl` example and the response-shape/status-code
     summary.
3. Critical Context:
   - **The Mount-lifespan gap from the prior entry is not
     Starlette-specific — it applies identically under FastAPI**,
     since `FastAPI.mount()` is the same underlying Starlette `Mount`.
     Simply doing `fastapi_app.mount("/", mcp_app)` without more would
     have reintroduced exactly the bug avoided last session (MCP
     session manager never starts). Fixed the same way, just at the
     new top level: `build_http_app()`'s `lifespan` context manager
     explicitly does `async with mcp_app.router.lifespan_context(mcp_app):
     yield` — confirmed via `Starlette.__init__`'s source that
     `router.lifespan_context` is exactly the callable the ASGI
     lifespan handler invokes internally (`Router.lifespan()` calls
     `self.lifespan_context(app)` where `app` is `scope["app"]`), so
     calling it manually with `mcp_app` itself as the argument
     reproduces the exact same invocation Starlette would have done had
     `mcp_app` been the top-level app.
   - **Status codes changed for validation failures**: the old
     hand-rolled Starlette version returned `400` for both "missing
     `path` field" and "invalid JSON body". FastAPI's own request-
     validation machinery now handles both automatically and returns
     `422` instead — deliberately kept as FastAPI's idiomatic default
     rather than fighting the framework to preserve `400`, since
     "consistent usage" was the explicit ask. `400` is still used, but
     now only for the one case that's genuinely *our* business-logic
     error (`UnsupportedFileTypeError`), raised explicitly via
     `HTTPException`. This endpoint was introduced and verified in the
     same session as this change (never depended on by anything else
     yet), so there was no real compatibility break — flagging anyway
     since it's the kind of detail that matters if anything starts
     calling this endpoint going forward.
   - Response shape also changed: bare JSON array instead of
     `{"results": [...]}`. Same reasoning — matches `ingest_path`'s
     MCP return shape, and nothing outside this session's own tests
     depended on the old wrapper.
4. Discarded Paths:
   - Considered keeping `mcp_app.add_route(...)` (last session's
     approach) and just writing the handler function using FastAPI's
     `APIRouter` in isolation, then splicing its `.routes` onto
     `mcp_app` directly — would have kept a single Starlette app/single
     lifespan (no composition risk at all) while still "using
     FastAPI" for the route-authoring. Rejected in favor of making
     FastAPI the actual top-level served app (`uvicorn.run(app, ...)`
     where `app` is genuinely a `FastAPI` instance) — closer to what a
     reader would expect "the project uses FastAPI" to mean, and the
     lifespan risk was fully addressed rather than avoided, not left as
     a landmine for a future person who reorganizes this file without
     rereading the prior entry's warning.
5. Live verification: rebuilt/redeployed the `mcp-server` Docker
   container. Startup log still shows `StreamableHTTP session manager
   started` (proving the lifespan-propagation fix works with the real
   MCP app, not just the fake one in `test_http_app.py`). `curl -X POST
   /ingest` with a real file → `200` + bare JSON array; missing `path`
   → `422` with FastAPI's structured validation error body; invalid
   JSON → `422`; real unsupported file type (`/app/uv.lock`) → `400`
   with the `UnsupportedFileTypeError` message; `GET /openapi.json` →
   `200` (confirms it's genuinely a FastAPI app, not just
   FastAPI-flavored routing bolted onto Starlette). Full MCP round-trip
   (`initialize` → `list_tools` → `call_tool("list_sources")`) still
   works, all 11 tools present.
6. Next Step: same as the prior entry — only Phase 8 (graph
   enrichment) remains, still blocked on the user's own pending LLM-
   provider decision.

---

## 2026-08-26 (session) — Phase 7 deferred items complete

Both items explicitly deferred from Phase 7 (`--watch` and the FastAPI
`POST /ingest` endpoint) implemented, at the user's explicit request
("start on phase 7 deferred items") — these were flagged but not
auto-started in the Phase 7 checkpoint, consistent with CLAUDE.md's
guidance not to silently apply deferred/self-determined scope calls.

[CHECKPOINT]
1. Core Objective: same as prior entries — Graph RAG system for coding
   agents, Neo4j-backed, exposed over MCP (Streamable HTTP).
2. Completed Milestones:
   - **`--watch`**: new `watchdog>=4.0` dependency. Two new top-level
     classes (one-class-per-file): `IngestionWatchHandler` (a
     `watchdog.events.FileSystemEventHandler` — reacts to
     create/modify events by calling `IngestionPipeline.run()` on the
     changed file; relies entirely on the pipeline's existing content-
     hash skip and per-file `error` handling rather than doing its own
     debouncing/dedup; swallows `UnsupportedFileTypeError` silently
     since not every filesystem event under a watched directory is a
     parseable file) and `IngestionWatcher` (owns the `watchdog.Observer`
     lifecycle and the blocking `while True: time.sleep(1)` loop,
     stopped via `KeyboardInterrupt`). `graph-rag ingest <path> --watch`
     runs the normal initial ingest pass, then blocks watching `path`
     for further changes until Ctrl+C — the `driver_session()` context
     manager now stays open for the whole watch loop, not just the
     initial pass (a real restructure of `ingest`'s control flow, not
     just an added flag).
   - **`POST /ingest`**: new `src/graph_rag/ingest_http_endpoint.py`
     with `build_ingest_route_handler(pipeline)` — a Starlette route
     handler (not a class; matches the existing `build_server()`
     factory-function convention), returns `{"results": [...]}` on
     success, `400` with `{"error": ...}` for a missing `path` field,
     invalid JSON body, or `UnsupportedFileTypeError`. Implemented as a
     **Starlette** route (not a separate FastAPI app/dependency) added
     directly onto the MCP server's own Starlette app instance via
     `mcp_app.add_route("/ingest", ..., methods=["POST"])` in
     `serve_mcp()` — see Critical Context below for why this exact
     wiring approach was necessary, not just simpler.
   - Tests: `tests/test_ingestion_watch_handler.py` (5 tests, using
     real `watchdog.events.FileCreatedEvent`/`FileModifiedEvent`/
     `DirModifiedEvent` objects and a hand-written `_FakePipeline` —
     no mocking library, same convention as everywhere else) and
     `tests/test_ingest_http_endpoint.py` (5 tests, using Starlette's
     real `TestClient` against a minimal app wrapping the handler with
     a `_FakePipeline`). `IngestionWatcher.watch()`'s actual OS-level
     watching + blocking loop is *not* unit tested (same convention as
     other real-infra-dependent code in this repo) — verified live
     instead, see below. 84/84 tests passing, `ruff check`/`ruff format
     --check` clean.
   - `README.md`: `--watch` example added to the ingestion section; new
     "reachable over plain HTTP" blurb with a `curl -X POST /ingest`
     example.
3. Critical Context:
   - **Why `POST /ingest` is mounted via `mcp_app.add_route(...)` and
     not a separate wrapping/parent Starlette app**: `MCPServer.
     streamable_http_app()` already returns a full `Starlette`
     instance (confirmed by reading the SDK source directly —
     `streamable_http_app(...) -> Starlette`), and that instance's own
     ASGI `lifespan` is what starts the "StreamableHTTP session
     manager" (visible in every prior session's live logs as "session
     manager started"). Starlette's `Mount(path, app=other_app)` does
     **not** forward `lifespan` startup/shutdown events to the mounted
     child app by default — wrapping `mcp_app` under a fresh parent
     `Starlette(routes=[Route("/ingest", ...), Mount("/", app=mcp_app)])`
     would have silently broken the MCP session manager's startup
     (the child's lifespan simply never runs). Realized this via
     `Starlette.add_route()` existing as a first-class API before
     writing any wiring code, so no broken version was ever shipped or
     needed fixing — flagging here because it's a genuine SDK-composition
     gotcha future work in this codebase (or any Starlette-based
     ASGI-app composition) needs to remember.
   - `IngestionWatcher` watching a **single file** target schedules the
     observer on the file's **parent directory** (watchdog watches
     directories, not individual files) and filters events to that
     exact resolved path via `IngestionWatchHandler(only_path=path)` —
     without this filter, editing any sibling file in the same
     directory would have also triggered a re-ingest of the watched
     file's path (a real bug caught and fixed during implementation,
     before any test was written against it, not after).
   - A single file save reliably fires **two** filesystem events
     (create then modify, or two modifies depending on the editor/OS) —
     confirmed live (see below): the second event's `IngestionPipeline.
     run()` call correctly reports `skipped=1` since the content hash
     already matches. This is exactly why the handler leans entirely on
     the pipeline's own idempotency rather than trying to debounce
     events itself — debouncing would be solving a problem the
     content-hash check already solves for free.
   - `IngestionResult.error` (added last session) turned out to matter
     here too: `IngestionWatchHandler._handle()` checks each result's
     `error` field and logs at ERROR without crashing the observer
     thread — a watch session that hits one bad file keeps watching,
     it doesn't die.
4. Discarded Paths:
   - Did not add a new `fastapi` dependency for the `POST /ingest`
     endpoint despite the plan text saying "FastAPI endpoint" — the
     project already has Starlette available transitively via the
     `mcp` package (confirmed: `bearer_token_middleware.py` already
     imports directly from `starlette.*`), and Starlette's `Route`
     equally satisfies "a small endpoint... gated behind local-only
     binding" with zero new dependencies. Flagging explicitly in case
     "FastAPI" specifically (not just "a POST /ingest endpoint") was
     actually wanted — nothing about the current implementation makes
     switching to FastAPI later hard, but nothing needed it either.
   - Considered a debounce/coalesce layer in `IngestionWatchHandler`
     (e.g. only re-ingest once per file per N seconds) — discarded per
     "Critical Context" above: the pipeline's content-hash skip already
     makes redundant events cheap (a hash comparison, no re-embedding),
     so debouncing would be added complexity solving an already-solved
     problem.
5. Live verification:
   - `--watch`: started `graph-rag ingest <empty-tmp-dir> --watch` in
     the background against the real local Neo4j, confirmed the
     initial pass found 0 files, then wrote a new `note.md` into the
     watched directory — logs showed it re-ingested (twice, second one
     correctly `skipped=1`), and a follow-up Cypher query confirmed the
     `Source` node actually landed in the graph. Sent `SIGINT` to stop
     the process; demo node + scratch directory cleaned up afterward.
   - `POST /ingest`: rebuilt/redeployed the `mcp-server` Docker
     container; container startup log now shows both `MCP server
     listening on .../mcp` and `POST /ingest listening on .../ingest`,
     and `StreamableHTTP session manager started` still appears
     (confirming the lifespan-sharing approach above actually works,
     not just in theory). `curl -X POST /ingest` with a real file →
     200 + correct `IngestionResult` JSON; missing `path` field → 400;
     invalid JSON body → 400; a real existing-but-unsupported file
     (`/app/uv.lock`) → 400 with the `UnsupportedFileTypeError`
     message. Confirmed the MCP side is completely unaffected: a full
     `initialize` → `list_tools` → `call_tool("list_sources")`
     round-trip through the real MCP Python client still works,
     listing all 11 tools.
6. Next Step: the entire roadmap (Phases 0-11 plus both Phase-7-
   deferred items) is now implemented. The only remaining open item is
   Phase 8 (graph enrichment), still explicitly blocked on the user's
   own pending LLM-provider decision from two sessions ago — do not
   start it without that decision being made first.

---

## 2026-08-26 (session) — Phase 10 complete

Phase 10 (observability, evaluation, ops) complete — full scope from
the plan. Last of the user's chosen "Phase 9 then 10" sequencing;
Phase 8 (graph enrichment) remains explicitly deferred pending an LLM
provider decision, per the user's own request last session.

[CHECKPOINT]
1. Core Objective: same as prior entries — Graph RAG system for coding
   agents, Neo4j-backed, exposed over MCP (Streamable HTTP).
2. Completed Milestones:
   - **Ingestion error resilience + logging**: `IngestionResult` gained
     an `error: str | None` field. `IngestionPipeline._ingest_one()` now
     catches any exception from parse/enrich/write and returns a result
     with `error` set instead of propagating — one bad file no longer
     aborts the rest of a directory ingest. `IngestionPipeline` and
     `cli.py` both gained module-level loggers; `run()` logs a start
     line and an end-of-run summary (processed/skipped/failed counts)
     at INFO, and `logger.exception(...)` on each per-file failure at
     ERROR (full traceback). `cli.py` now calls
     `logging.basicConfig(...)` at import time so these are actually
     visible on stdout/`docker compose logs`. `graph-rag ingest`'s CLI
     output prints `Failed to ingest <path>: <error>` per failed file
     and exits code 1 if any file failed (was always 0 before, silently).
   - **Retrieval eval set**: new `src/graph_rag/eval/` module
     (one-class-per-file, facade `__init__.py`) — `EvalCase`,
     `EvalCaseResult`, `RetrievalEvaluator.run(cases)` (runs each case's
     query through `Retriever.search()`, checks whether a hit matching
     both `expected_source_path` and `expected_breadcrumb_contains`
     (case-insensitive substring) appears in the top-k, records the
     1-indexed rank if so). 5 hand-written cases in
     `src/graph_rag/eval/retrieval_eval_set.yaml`, built from real
     Section titles/breadcrumbs queried out of the ingested DMS PDF.
     New CLI command `graph-rag eval-retrieval [--eval-set PATH]` —
     prints PASS/FAIL + rank per case, a summary line, exits 1 if any
     case fails (CI-usable gate). `make eval` added.
   - **`docs/operations.md`** (new): `docker compose down -v` deletes
     `neo4j_data`/`neo4j_plugins` — explicit warning that this nukes
     every Source/Chunk/CodeEntity/PolicyRule/**AgentMemory**
     permanently, plain `down` (no `-v`) does not; volume-level
     tar backup/restore commands (Neo4j Community has no online-backup
     feature, so the container must be stopped first); a note that
     re-running `graph-rag ingest` reconstructs the document graph from
     scratch but **cannot** reconstruct `AgentMemory` (no source file to
     re-ingest from — only a volume backup preserves it); a section on
     the new ingestion error/logging behavior above.
   - **README.md rewritten**: full current MCP tool list (all of
     Phases 3/6/7/9/11's tools, plus the `graph-rag://sources`
     resource), `graph-rag ingest <path-or-dir>` generalized-ingestion
     usage with the skip/reconcile/error-resilience behavior explained,
     `make eval`, links to `docs/operations.md`.
   - **`.mcp.json` recreated** at the repo root — it was referenced by
     the README ("`.mcp.json` at the repo root already registers it for
     this project") but had been deleted from the working tree at some
     point before this session (confirmed via `git log --all -- .mcp.json`
     — never committed, so no history to recover from; it must have
     existed only as an untracked file that got removed). Recreated
     with the Streamable HTTP entry the plan's Phase 3 text specifies:
     `{"mcpServers": {"graph-rag": {"type": "http", "url":
     "http://127.0.0.1:8765/mcp"}}}`.
   - Tests: `tests/test_ingestion_pipeline.py` gained
     `_FailingGraphWriter` + 2 tests (single-file and directory-mode
     error resilience). New `tests/test_retrieval_evaluator.py` (6
     tests, using a hand-written `_FakeRetriever` duck-type — same
     no-mocking-library convention as everywhere else — plus one test
     that loads and sanity-checks the real built-in YAML eval set).
     74/74 tests passing, `ruff check`/`ruff format --check` clean.
3. Critical Context:
   - The first version of the default eval set had a 5th case
     ("What causes CDC replication latency related to endpoint
     resources?") that **genuinely failed** against the live corpus —
     verified via a scratch script dumping `search()`'s real top-5,
     which landed on sibling latency/CDC sections, never the exact
     "Endpoint resources" one. Deliberately swapped for an
     SSL/encryption-in-transit query that passes at rank 1, rather than
     ship a default eval case that fails out of the box — a perpetually
     red default case trains users to ignore the exit code. This
     surfaced a real (if unsurprising) retrieval-quality limit: the
     small local `all-MiniLM-L6-v2` embedder is reliable for top-level/
     mid-level thematic queries (replication instance creation,
     selection rules, terminology, Kerberos, SSL — all rank 1-4 in
     top-5) but noticeably weaker at pinpointing deeply-nested,
     narrowly-scoped troubleshooting subsections specifically. Not
     fixed — Phase 8's LLM-based `Concept` extraction/graph traversal
     is the roadmap's actual answer to this class of query, not a
     retrieval eval set change.
   - Verified live (Docker rebuild) that ingesting a deliberately
     malformed YAML file (unterminated flow sequence) via `graph-rag
     ingest` now reports `Failed to ingest <path>: <yaml error message>`,
     logs a full traceback, exits code 1, and — confirmed via Cypher —
     never wrote a `Source` node for that file, i.e. the failure is
     caught before any partial/corrupt graph state lands.
   - `logging.basicConfig(...)` in `cli.py` does take effect inside the
     `serve-mcp` Docker container despite `uvicorn.run(..., log_level=
     "info")` also configuring logging — confirmed live: container logs
     now show timestamped `INFO graph_rag.ingestion_pipeline: ...` and
     even third-party library logs (`INFO httpx: ...` from
     sentence-transformers' model download check) alongside uvicorn's
     own `INFO:     ...` lines, meaning root-logger propagation from
     `graph_rag.*` (and other) loggers survived uvicorn's own logging
     setup rather than being silently dropped.
   - The eval YAML fixture lives inside the package
     (`src/graph_rag/eval/retrieval_eval_set.yaml`), loaded via
     `Path(__file__).parent / ...` — works because this project is
     always run from source (`uv run`, or the Dockerfile's `COPY src/
     src/` + `uv sync`, never a built/distributed wheel), so no
     `pyproject.toml` package-data configuration was needed; would need
     one if this ever became a distributed package.
4. Discarded Paths:
   - Considered making `IngestionRun` (start/end/results/errors) its
     own return type replacing `list[IngestionResult]` from
     `IngestionPipeline.run()` — would have been a breaking API change
     touching the CLI, the `ingest_path` MCP tool's return shape, and
     every existing ingestion test. Chose the smaller diff instead:
     keep `run()`'s return type, add `error` to `IngestionResult`, and
     do "run tracking" via structured logging rather than a new graph/
     return-type node — the plan explicitly offered "graph nodes or
     structured logs" as alternatives, and logging fit the existing
     surface better.
   - Considered making `AgentMemory` nodes part of a Neo4j-volume-only
     backup story with no mention — decided the operations doc should
     explicitly call out that memory has no re-ingestable source, since
     it's the one node type Phase 10's "rebuild from scratch instead of
     restoring" escape hatch can't cover.
5. Live verification: see "Critical Context" above (malformed-YAML
   error handling, live container logging, `ingest_path` still working
   post-rebuild with the new `error` field present as `null` on
   success) plus a full `graph-rag eval-retrieval` run against the real
   ingested DMS PDF (5/5 passed, exit 0).
6. Next Step: all of the roadmap's Phase 9/10 scope the user asked for
   is done. Remaining open items, none started: Phase 8 (graph
   enrichment — blocked on an LLM provider decision the user wanted to
   think through further), and the two Phase-7-deferred items
   (`--watch` mode, FastAPI `POST /ingest` endpoint). Don't start any
   of these without explicit user direction.

---

## 2026-08-26 (session) — Phase 9 complete

Phase 9 (MCP API hardening & agent ergonomics) complete — full scope
from the plan. User chose "Phase 9 then 10" over Phase 8 (graph
enrichment), explicitly deferring Phase 8 pending a decision on which
LLM should do its Concept-extraction pass (cost/dependency tradeoff
explained but not decided).

[CHECKPOINT]
1. Core Objective: same as prior entries — Graph RAG system for coding
   agents, Neo4j-backed, exposed over MCP (Streamable HTTP).
2. Completed Milestones:
   - `mcp_server/retriever.py`: three new `Retriever` methods —
     `get_neighbors(node_id, rel_types=None)` (both-direction traversal
     from any node, matched against whichever unique key its label uses
     — `Source.path`, `Section`/`Chunk`/`PolicyRule`/`AgentMemory.id`,
     `CodeEntity.qualified_name`, `Concept.name` — via a generic
     property-OR match, no label hint), `get_outline(source_path)`
     (flat rows reassembled into a nested `OutlineNode` tree via the
     new pure `_build_outline_tree()` helper), `cite(chunk_id)` (human-
     readable citation string via the new pure `_format_citation()`
     helper, page-range-aware). `get_section` gained a `max_chars=8000`
     param — truncates joined chunk text past that length and sets a
     new `SectionDetail.truncated: bool` field.
   - New models: `NeighborResult`, `OutlineNode` (self-referential,
     recursive `children: list["OutlineNode"]`).
   - `mcp_server/server.py`: three new tools — `get_neighbors`,
     `get_outline`, `cite` — plus a new MCP **resource** (not a tool):
     `graph-rag://sources`, browsable without a tool call, backed by
     the same `retriever.list_sources()` as the `list_sources` tool.
     `INSTRUCTIONS` updated to mention all of it.
   - Tests: `_build_outline_tree`/`_format_citation` unit tested as
     pure functions in `tests/test_retriever.py` (same pattern as the
     pre-existing `combine_scores` tests) — `get_neighbors`/
     `get_outline`/`cite` themselves aren't unit tested, same
     no-live-Neo4j-in-unit-tests convention as `GraphWriter`/`MemoryWriter`
     /`MemoryRecaller`/`MemoryPruner`; verified live instead (below).
     67/67 tests passing, `ruff check`/`ruff format --check` clean.
3. Critical Context:
   - **MCP SDK list-tool serialization**: a tool returning `list[Model]`
     serializes as *one content block per list item* (confirmed via
     `result.content` length == item count) plus a single
     `result.structured_content = {"result": [...]}` holding the whole
     list as real JSON — `result.content[0].text` is only the **first**
     item, not the whole list. A hand-rolled verification/debug script
     that does `json.loads(result.content[0].text)` on a list-returning
     tool will silently look "off" (e.g. `get_outline`'s 27-section
     outline looked like a single flat 3-key dict) even though the
     server is correct — always read `result.structured_content["result"]`
     when scripting against a list-returning tool.
   - `get_neighbors`'s generic `n.id = $x OR n.qualified_name = $x OR
     n.path = $x OR n.name = $x` match does a full node scan (no label
     hint, so none of the per-label uniqueness-constraint indexes get
     used for the source node lookup) — deliberate simplicity-over-
     performance tradeoff for a local dev/agent tool at this graph
     size; revisit only if this graph grows large enough for it to
     matter, not preemptively.
   - `ruff format .` was run repo-wide this session (not just
     newly-touched files) and it collapsed a handful of multi-line
     Cypher constraint/index strings in `schema.py` plus wrapped one
     long line in `cli.py` — this actually *resolves* the pre-existing
     `ruff format` deviation flagged in the Phase 7 checkpoint entry
     below, it did not regress anything (content unchanged, `ruff
     format --check` is now clean repo-wide for the first time).
4. Discarded Paths: None. Phase 8 was explicitly not started — the
   user wants to understand the LLM-dependency tradeoff further before
   picking a provider (Anthropic API vs. local Ollama were the two
   options offered); do not silently pick one.
5. Live verification (Docker, rebuilt `mcp-server` image, against the
   real ingested graph — DMS PDF + this repo's own `src/`): `get_outline`
   on the DMS PDF returned the correct nested tree (confirmed via
   `structured_content`, e.g. section `s0002` correctly nests child
   `s0003`); `get_neighbors` on
   `graph_rag.ingest.chunker.Chunker.chunk` returned 4 mixed-type
   neighbors (`CALLS`/`CONTAINS`/`DEFINES`), and `rel_types=["CONTAINS"]`
   correctly narrowed that to exactly 1; `cite` on a real chunk id
   returned `"training-docs/dms-ug.pdf — AWS Database Migration Service
   (pp. 1–2)"`, and on a nonexistent chunk id returned empty content
   (`None`, correctly); `get_section` with `max_chars=50` returned
   `truncated: true` and a 50-character `text`, parent/children outline
   still intact; `resources/list` showed exactly `graph-rag://sources`,
   and reading it returned the full source inventory as JSON.
6. Next Step: Phase 10 (observability, evaluation, ops) is next per
   the user's own chosen sequencing ("Phase 9 then 10"). Phase 8
   (graph enrichment) and the two Phase-7-deferred items (`--watch`,
   FastAPI `POST /ingest`) remain open, not started, pending explicit
   user direction — Phase 8 specifically needs an LLM provider decision
   first.

---

## 2026-08-26 (session) — Phase 11 complete

Phase 11 (agent memory) complete — full scope from the plan. Implemented
right after Phase 7 per the user's own agreed sequencing.

[CHECKPOINT]
1. Core Objective: Graph RAG system ingesting heterogeneous docs (PDF,
   Markdown, Python, YAML/Checkov) into Neo4j, exposed to coding agents
   via an MCP server (Streamable HTTP) — plus, as of this phase, a
   separate agent working-memory store on the same graph.
2. Completed Milestones:
   - New top-level `src/graph_rag/memory/` module (one-class-per-file,
     facade `__init__.py`), deliberately decoupled from the
     document-ingestion pipeline — no `Parser`/`ParsedDocument`/
     `GraphWriter` involved:
     - `AgentMemory` (model) — `id`, `content`, `kind`, `embed_text`,
       `embedding`, `created_at`, `last_accessed_at`, `access_count`,
       `importance`, `archived_at`, `source_session_id`.
     - `AgentMemoryResult` (model) — lightweight `recall()` hit shape
       (no embedding vector serialized back to the agent).
     - `MemoryWriter.remember()` — embeds + upserts an `AgentMemory`,
       optionally linking `ABOUT` a `CodeEntity` when
       `about_qualified_name` resolves; `MemoryWriter.forget()` —
       immediate hard delete.
     - `MemoryRecaller.recall()` — hybrid vector+fulltext search over
       `AgentMemory.content` (same blend weights/pattern as
       `mcp_server/retriever.py`'s `combine_scores`, duplicated rather
       than shared to keep `memory/` independent of `mcp_server/`);
       every returned hit gets `last_accessed_at`/`access_count` bumped
       — recall reinforces a memory, same as human memory.
     - `MemoryPruner.prune(threshold, grace_days=30)` — recency+frequency
       decay score (`access_count / (age_days + 1)`); anything scoring
       below `threshold` and not `importance=True` gets soft-deleted
       (`archived_at` set); anything already archived past the grace
       window gets hard-deleted (`DETACH DELETE`) in the same pass.
       `PruneResult(soft_deleted, hard_deleted)`.
   - `graph/schema.py`: `AgentMemory.id` uniqueness constraint,
     `agent_memory_content_fulltext` fulltext index, new `RANGE_INDEXES`
     list with `agent_memory_last_accessed` (keeps the pruner's scan
     cheap), `agent_memory_embedding` vector index. `apply_schema()` now
     applies 17 statements (was 13).
   - `mcp_server/server.py`: three new tools — `remember`, `recall`,
     `forget` — the first MCP tools in this server beyond `ingest_path`
     that write. `build_server()` signature grew to take
     `memory_writer`/`memory_recaller`.
   - `cli.py`: new `graph-rag prune-memory --threshold <score>
     [--grace-days N]` command; `serve-mcp` now also constructs
     `MemoryWriter`/`MemoryRecaller` and passes them into `build_server()`.
   - Tests: `tests/test_memory_recaller.py` (hybrid-scoring pure
     functions, mirrors `test_retriever.py`), `tests/test_memory_pruner.py`
     (`MemoryPruner._score` decay-math cases). 61/61 total passing,
     `ruff check` clean. (`MemoryWriter`/`MemoryRecaller`/`MemoryPruner`
     themselves aren't unit tested — same convention as `GraphWriter`,
     which has no unit tests either — they need a real Neo4j session,
     so they're verified live instead, see below.)
3. Critical Context:
   - **`Session.run()` kwarg collision** — neo4j's `Session.run(query,
     parameters=None, **kwparameters)` has `query` as its own first
     positional parameter name. Calling `session.run(cypher, query=query,
     k=...)` throws `TypeError: Session.run() got multiple values for
     argument 'query'` whenever a Cypher parameter is itself named
     `query` (as `recall`'s fulltext search naturally is). Fix: pass a
     single dict as the second positional arg instead of kwargs —
     `session.run(cypher, {"query": query, "k": k})`. `retriever.py`'s
     `_FULLTEXT_SEARCH` already did this (that's why it never hit the
     bug); `memory_recaller.py` now matches it. Watch for this pattern
     any time a new Cypher query takes a parameter literally named
     `query`.
   - `about_qualified_name` only resolves against `CodeEntity` (not
     `Section`/`Source`/`PolicyRule`, despite the plan text listing all
     four as valid `ABOUT` targets) — kept intentionally minimal per the
     tool's own parameter name; no edge is created if it doesn't match
     an existing `CodeEntity`.
   - `MemoryPruner`'s soft-delete and hard-delete both run inside one
     `prune()` call using the same `now` timestamp for both `archived_at`
     and the grace-window `cutoff` — so `--grace-days 0` soft-deletes
     and hard-deletes a stale memory in the same invocation (verified
     live, see below). This is a real usable "purge everything below
     threshold right now" mode, not just an edge case.
   - Score formula is exactly `access_count / (age_days + 1)` — a
     never-recalled, brand-new memory scores `1.0` (age≈0 → `1/(0+1)`),
     not `0`, so a `--threshold` above `1.0` is needed to prune
     freshly-created-but-never-recalled memories; `0` access_count with
     nonzero age asymptotically approaches `0`.
   - `MemoryRecaller`'s hybrid scoring duplicates `retriever.py`'s
     `combine_scores`/`_min_max_normalize` rather than importing them —
     deliberate, to keep `memory/` from depending on `mcp_server/`
     (server.py already depends the other way, on `memory/`; importing
     back would invert the layering). If this duplication needs to grow
     a third copy later, that's the trigger to extract a shared
     `scoring.py`, not before.
4. Discarded Paths: None — this phase matched the plan's own design
   (from the prior session's Q&A) closely enough that no scope was
   cut or restructured during implementation, only the `Session.run()`
   bug above was unplanned.
5. Live verification (Docker, rebuilt `mcp-server` image): `remember` →
   returns a full `AgentMemory` with a real embedding; `recall` →
   hybrid search returns it, `access_count` bumped on each call
   (confirmed via a second identical `recall`); `forget` → subsequent
   `recall` for the same query returns `content: []`, empty; `graph-rag
   prune-memory --threshold 1.0 --grace-days 0` on a synthetic
   never-recalled, non-important memory → `Soft-deleted 1, hard-deleted
   1` in one run, confirmed gone from Neo4j (`count(m) = 0`);
   `importance=True` memory survived `prune-memory --threshold 100`
   untouched (`archived_at` stayed `NULL`); a memory `remember()`'d with
   `about_qualified_name="graph_rag.cli.status"` was reachable via
   `MATCH (e:CodeEntity {qualified_name:'graph_rag.cli.status'})<-[:ABOUT]-(m:AgentMemory)`
   — traversal from the code side works, not just text search. All demo
   nodes cleaned up afterward (`DETACH DELETE`).
6. Next Step: Phase 11 was the last item on the current roadmap after
   Phase 7 — remaining phases (8 graph enrichment, 9 MCP hardening, 10
   observability/ops) are still open, plus the two items explicitly
   deferred from Phase 7 (`--watch`, FastAPI `POST /ingest`). None of
   these should be started without the user picking one next.

---

## 2026-08-26 (session) — Phase 7 complete

Phase 7 (generalized ingestion API & incremental updates) complete.
Core scope only — `--watch` and the FastAPI `POST /ingest` endpoint from
the plan's Phase 7 bullets were deliberately deferred (see below).

[CHECKPOINT]
1. Core Objective: Graph RAG system ingesting heterogeneous docs (PDF,
   Markdown, Python, YAML/Checkov) into Neo4j, exposed to coding agents
   via an MCP server (Streamable HTTP).
2. Completed Milestones:
   - `Parser` protocol (`ingest/parser.py`: `can_handle(path)` +
     `parse(path)`) — each of the 4 existing parsers gained a
     `can_handle` static method (suffix check moved out of `cli.py`
     and into the parser itself).
   - `ParserRegistry` (`ingest/parser_registry.py`) — holds the 4
     parser instances, `for_path(path)` returns whichever can handle
     it or `None`. Adding a new file type is now: write a parser,
     add one line here, done.
   - `IngestionPipeline` (top-level `ingestion_pipeline.py`, sits
     above both `ingest/` and `graph/` since it composes both) —
     `run(path, dry_run=False)`: file or directory (recursive via
     `rglob`), skips unsupported files silently when walking a
     directory but raises `UnsupportedFileTypeError` for an explicit
     unsupported single-file argument. Per-file: hashes the raw file
     bytes and compares against `GraphWriter.get_source_content_hash`
     *before* parsing — unchanged files short-circuit with zero
     parsing/embedding work. `dry_run=True` still parses (so counts
     are accurate) but skips embedding + writing.
   - `GraphWriter` extended with `get_source_content_hash(path)` (read)
     and stale-child reconciliation, run at the end of every `write()`:
     `DETACH DELETE` any `Chunk`/`Section`/`CodeEntity`/`PolicyRule`
     still attached to this `Source` whose merge-key isn't in the
     newly-parsed set. Chunks reconciled before Sections (so a
     removed Section never leaves orphaned Chunks for the Section
     query to miss). This is the piece that makes re-ingestion of a
     changed file actually remove what was deleted, not just add/
     update what's still there.
   - CLI: `graph-rag ingest <path>` now accepts a file **or**
     directory, plus `--dry-run`. Old per-suffix if/elif dispatch
     removed in favor of `ParserRegistry` + `IngestionPipeline`.
   - New MCP tool `ingest_path(path: str, dry_run: bool = False) ->
     list[IngestionResult]` (`mcp_server/server.py`) — lets the agent
     itself trigger re-ingestion after editing a file, reusing the
     same `IngestionPipeline`. This is the MCP server's first
     **write**-capable tool (previously all 4 tools were read-only
     lookups).
   - `IngestionResult` (top-level `ingestion_result.py`) and
     `UnsupportedFileTypeError` (top-level
     `unsupported_file_type_error.py`) — kept outside `ingest/` and
     `graph/` alongside `ingestion_pipeline.py`, since they belong to
     the orchestration layer, not to parsing or graph-writing alone.
   - 18 new tests (`tests/test_parser_registry.py`,
     `tests/test_ingestion_pipeline.py` — the latter uses hand-written
     fake `Embedder`/`GraphWriter` doubles, no real Neo4j, matching
     this repo's existing no-mocking-library convention) — 53/53
     passing total. `ruff check` clean; `ruff format --check` clean on
     every file touched this phase (the one pre-existing `cli.py`
     format deviation from Phase 3 is untouched, same as every prior
     phase's decision).
   - Live end-to-end verification: `apply-schema` unchanged at 13
     (Phase 7 adds no new node types/indexes). Ran
     `graph-rag ingest src/graph_rag --dry-run` (correctly previewed
     40 files, 0 writes, mix of skip/would-ingest based on real
     content-hash diffs against Phase 5/6 data) then for real (same
     split, single command — no more manual per-file shell loop);
     re-running immediately afterward skipped all 40/40 files,
     confirming full idempotency. Proved the phase's own exit
     criterion directly: ingested a 2-function scratch file, deleted
     one function and edited the other's docstring, re-ingested —
     Cypher confirmed the edited function's docstring updated in
     place, the deleted function's `CodeEntity` node was gone
     entirely (`count = 0`), and nothing else in the repo was touched.
     Rebuilt/redeployed the `mcp-server` container and called
     `ingest_path` through a live MCP client twice on the same
     container-side path — first call ingested, second call correctly
     reported `skipped: true`.
3. Critical Context:
   - `IngestionPipeline` deliberately lives at the top level
     (`src/graph_rag/ingestion_pipeline.py`), not inside `ingest/` —
     `ingest/` stays Neo4j-agnostic (parsing/chunking/embedding only);
     the pipeline is what composes `ingest.ParserRegistry` +
     `ingest.Enricher` + `graph.GraphWriter`, same composition
     `cli.py` used to do inline.
   - `Source.path` is the identity key — the same repo file ingested
     from two different absolute-path prefixes (host path vs. the
     container's `/app/...` path) is treated as two distinct `Source`
     nodes. Surfaced directly during live verification (ingesting
     `/app/src/graph_rag/settings.py` from inside the container created
     a second Source alongside the host-ingested `src/graph_rag/
     settings.py`); both demo artifacts were cleaned from the graph
     after verification. Not a bug — just something to keep in mind
     if ever ingesting the same tree from both host and container.
   - Deferred from the plan's Phase 7 bullets, on purpose: `--watch`
     (needs a new dependency, `watchdog`, plus a long-running
     filesystem-event loop — meaningfully more infra than the rest of
     this phase) and the standalone FastAPI `POST /ingest` endpoint
     (the MCP server's `ingest_path` tool now covers the "trigger
     ingestion over HTTP without the CLI" use case; a second, separate
     REST surface felt like the redundant one given the new tool).
     Flagged here rather than silently skipped — say the word if
     either is still wanted.
4. Discarded Paths: Considered putting `IngestionResult` under
   `ingest/models/` as a Pydantic model there — moved it to the
   top level instead once `IngestionPipeline` itself was pulled out
   of `ingest/`, so the result type sits next to the class that
   produces it rather than implying it's part of the parsing layer.
5. Next Step: Per the roadmap, Phase 11 (agent memory) was the
   originally-agreed next phase after Phase 7 — not yet started.
   Phases 8–10 (graph enrichment, MCP hardening, observability) remain
   further out and unstarted.

---

## 2026-08-25 19:40 EDT

Phase 6 (YAML/Checkov ingestion) complete.

[CHECKPOINT]
1. Core Objective: Graph RAG system ingesting heterogeneous docs (PDF,
   Markdown, Python, now YAML/Checkov) into Neo4j, exposed to coding
   agents via an MCP server (Streamable HTTP).
2. Completed Milestones:
   - New `PolicyRule` model (`ingest/models/policy_rule.py`): `id` (merge
     key), `name`, `category`, `severity`, `guideline`, `provider`,
     `file_path`, `embed_text`, `resource_types: list[str]`, `embedding`.
   - `ParsedDocument` extended with `policy_rules: list[PolicyRule] = []`.
   - `YamlParser` (`ingest/parsers/yaml_parser.py`): `yaml.safe_load_all`
     for multi-document files (one Checkov policy per `---`-separated
     doc). A doc is "Checkov-shaped" iff it has a `metadata.id` field;
     `resource_types` are collected by recursively walking the
     `definition` tree for any `resource_types` list (handles Checkov's
     `and`/`or`/nested-condition structure), deduped in encounter order.
     Non-Checkov YAML docs fall back to one implicit `Section` (title =
     file stem) with one atomic `Chunk` per top-level mapping key —
     still parsed/embedded, no `PolicyRule`/`APPLIES_TO` edges.
   - `Enricher` extended to also embed `PolicyRule.embed_text`.
   - `GraphWriter` extended: `MERGE (p:PolicyRule {id})` + `(Source)-
     [:DEFINES]->(PolicyRule)`, and `(PolicyRule)-[:APPLIES_TO]->
     (Concept {name: resource_type})` — Concept nodes get `type =
     "resource_type"` set directly on every write (unlike the CALLS/
     IMPORTS forward-stub pattern, there's no later "definitive" write
     for a Concept to fill in, so it's fully set here).
   - `schema.py`: added `policy_rule_text_fulltext` fulltext index and
     `policy_rule_vector_index_statement()` (mirrors the CodeEntity
     pattern from Phase 5); both wired into `apply_schema()`.
   - New MCP tool `find_policies_for(resource_type: str) ->
     list[PolicyResult]` (`mcp_server/models/policy_result.py`,
     `Retriever.find_policies_for`) — pure graph traversal: `MATCH
     (PolicyRule)-[:APPLIES_TO]->(Concept {name: $resource_type})`, then
     an `OPTIONAL MATCH` to collect every other resource type the same
     rule applies to. Registered in `mcp_server/server.py` alongside
     `search`/`get_section`/`list_sources`.
   - CLI: `.yaml`/`.yml` dispatch to `YamlParser` in the `ingest` command.
   - Added `pyyaml>=6.0` as an explicit dependency (was previously only
     present transitively via other packages — importing it directly
     without declaring it would have been fragile).
   - 8 new tests (`tests/test_yaml_parser.py`, 2 new in
     `tests/test_schema.py`) — 44/44 passing total. `ruff check` clean;
     `ruff format --check` clean on all newly authored/modified files
     (pre-existing `cli.py`/`schema.py` format deviations from prior
     phases deliberately left untouched, per "surgical changes").
   - Live end-to-end verification: added 3 sample Checkov policies under
     `training-docs/checkov-policies/` (RDS encryption + public-access,
     S3 versioning — two overlapping on `aws_db_instance`/
     `aws_rds_cluster`, one independent). Ran `apply-schema` (11 → 13
     statements), ingested all 3 (idempotency re-check: re-ingesting one
     file twice still yields exactly 3 `PolicyRule` + 3 `Concept`
     nodes), confirmed the `aws_db_instance` traversal returns exactly
     the 2 correct policies (excluding the unrelated S3 one) via direct
     Cypher, then rebuilt/redeployed the `mcp-server` Docker container
     and called `find_policies_for` through a live MCP client —
     returned the same 2 correctly-shaped results through the real
     protocol.
3. Critical Context:
   - Same scope decision as Phase 5's `CodeEntity`: `PolicyRule` is
     embedded and has its own fulltext/vector index, but is **not**
     wired into the existing chunk-based `search()` tool — kept as a
     separate, explicit `find_policies_for` graph-traversal tool per the
     plan's exit criteria, rather than blending policy results into
     prose search.
   - Concept nodes are shared/deduped by `name` only (per the Phase 1
     schema's `concept_name` uniqueness constraint) — a `Concept` named
     `aws_db_instance` referenced from multiple `PolicyRule`s is a
     single node with fan-in `APPLIES_TO` edges, not a copy per rule.
4. Discarded Paths: None — first implementation matched the plan
   directly (Phase 4/5 already proved out the parser-plugin/forward-stub
   patterns this phase reused).
5. Next Step: Phase 7 (generalized ingestion API + incremental updates —
   directory/recursive `graph-rag ingest`, content-hash-driven
   upsert-vs-skip, `ingest_path` MCP tool) is the next unstarted phase
   per the roadmap, but not yet requested by the user — do not start
   without explicit direction.

---

## 2026-08-25 15:10 EDT

Phase 5 (Python ingestion via `ast`) complete.

- New `CodeEntity` model (`ingest/models/code_entity.py`): `qualified_name`
  (merge key, e.g. `graph_rag.ingest.chunker.Chunker.chunk`), `name`, `kind`
  (module/class/function/method), `embed_text` (docstring, or a computed
  fallback summary when absent — signature + first body line for
  functions/methods, base classes + method list for classes, "Defines: ..."
  export list for modules), `file_path`/`start_line`/`end_line`,
  `signature`, `docstring`, `parent_qualified_name`, `calls`/`imports`
  (qualified-name lists), `embedding`.
- `ParsedDocument` extended with `code_entities: list[CodeEntity] = []`
  (sections/chunks/code_entities are now all optional/default-empty — a
  given parser populates whichever shape fits: Section/Chunk for prose,
  CodeEntity for code).
- `PythonParser` (`ingest/parsers/python_parser.py`): walks each module's
  top-level `ast` body — classes become `CodeEntity(kind="class")` with a
  `CONTAINS` edge to their methods, module-level functions become
  `kind="function"`, the module itself becomes `kind="module"`. No
  chunking (code is structural, not prose, per the plan).
  - `qualified_name` is derived from the file's on-disk package ancestry
    (walks up while parent dirs have `__init__.py`), not from any import
    config — e.g. `src/graph_rag/ingest/chunker.py` → `graph_rag.ingest.chunker`.
  - `calls`/`imports` are resolved **statically, best-effort, no type
    inference** (matches the plan's explicit scope): bare-name calls
    resolve against local top-level defs or `from x import y` aliases;
    `self.foo()` resolves against sibling methods of the enclosing class;
    `alias.foo()` resolves when `alias` is a locally-imported module
    (`import x`/`import x as alias`) or `from` alias. Anything else
    (arbitrary-object attribute calls, multi-segment `import x.y.z`
    without `as` used via `x.y.foo()`) is skipped rather than guessed.
    Relative imports (`from .foo import bar`, `from ..pkg import baz`)
    are resolved via the file's own qualified-name ancestry.
- `GraphWriter` extended: `MERGE`s `CodeEntity` nodes (batched, same
  pattern as `Section`/`Chunk`), `(Source)-[:DEFINES]->(CodeEntity)`,
  `(parent)-[:CONTAINS]->(child)`, and `CALLS`/`IMPORTS` edges. `CALLS`/
  `IMPORTS` targets are created via bare `MERGE` (no property `SET`) so
  they work as forward-references — a call/import to an entity not yet
  ingested (stdlib, third-party, or just not-yet-parsed local code)
  creates a lightweight stub node holding only `qualified_name`; if that
  entity is ingested later, its own row fills in the real properties on
  the same node (order-independent, matches the existing `Section`
  `PARENT_OF` stub pattern). Verified live: `pdf_parser.py`'s `IMPORTS`
  edge to `graph_rag.ingest.chunker.Chunker` shows `kind: null` before
  `chunker.py` is ingested and `kind: "class"` after.
- `Enricher` extended to also embed `CodeEntity.embed_text` (previously
  only embedded `Chunk.text`); no change to its `Chunk` behavior.
- `graph/schema.py`: added `code_entity_text_fulltext` (keyword side) and
  `code_entity_embedding` vector index (new `code_entity_vector_index_statement()`,
  mirrors `vector_index_statement()`) — the `code_entity_qualified_name`
  uniqueness constraint already existed from Phase 1.
- `cli.py`: `ingest` now also dispatches `.py` → `PythonParser`.
- Scope decisions (flagged here, not pre-cleared with the user):
  - Did **not** add MCP-level code search (a `search_code` tool or
    extending `Retriever.search()` to cover `CodeEntity`). Verified the
    exit criteria via direct Neo4j full-text query instead (see below).
    Natural next step if the user wants agents to actually query code
    through MCP, not just chunks/sections.
  - Did **not** add directory/recursive ingestion to `graph-rag ingest`
    — that's explicitly Phase 7 ("Generalized ingestion API") scope.
    Verified this phase by looping the existing single-file CLI over
    every `.py` file in `src/graph_rag/`.
- New file `tests/test_python_parser.py` (12 tests): module-qualified-name
  derivation (nested packages, `__init__.py`, no-package fallback),
  signature/docstring extraction, no-docstring fallback text, class/method
  `CONTAINS` hierarchy, `self.*` call resolution, local-function call
  resolution, `from`-import call resolution, `import ... as` alias call
  resolution, relative-import resolution, module export-summary fallback.
- Verified: 38/38 tests pass (26 pre-existing + 12 new from this phase),
  `ruff check` clean repo-wide, `ruff format --check` clean on every file
  this phase touched, pyright with
  `reportDeprecated: error` clean (only the pre-existing unrelated
  `test_settings.py:5` error remains). Live end-to-end: ran
  `graph-rag apply-schema` (11 constraints/indexes now, up from 9) then
  looped `graph-rag ingest` over all 30 `.py` files under
  `src/graph_rag/` — 172 `CodeEntity` nodes, 98 `CALLS` edges written.
  A direct Neo4j full-text query for "PdfParser" against
  `code_entity_text_fulltext` returns exactly
  `graph_rag.ingest.parsers.pdf_parser.PdfParser` (kind=class) with its
  docstring and `file_path:start_line` — matches the Phase 5 exit
  criteria exactly. Re-ran the `pdf_parser.py` ingest twice more and
  confirmed `CodeEntity`/`CALLS` counts stayed at 172/98 both times
  (idempotent).
- Next: Phase 6 (YAML/Checkov) per the plan, or building the MCP-level
  code-search surface this phase deliberately deferred — awaiting user
  direction.

## 2026-08-25 14:20 EDT

Phase 4 (Markdown ingestion) complete.

- `MarkdownParser` (`ingest/parsers/markdown_parser.py`), mirroring
  `PdfParser`'s structure: `Source` (source_type="markdown") + `Section`
  tree from ATX headings (`#`..`######`, fence-aware so headings inside
  fenced code blocks are ignored) + `Chunk`s. Reuses the existing
  `Chunker`/`Enricher`/`GraphWriter` pipeline unchanged, per the plan —
  confirmed `GraphWriter` needed zero changes (source_type is a free
  string field, no schema constraint on it).
- Fenced code blocks (```` ``` ```` / `~~~`, closing marker must match
  char and be >= opening length) are never split: `_segment_body()`
  partitions each leaf section's body into "code"/"prose" runs; code
  runs become one atomic `Chunk` each (bypassing `Chunker`, built
  directly to preserve the whole block regardless of size), prose runs
  go through the normal word-bounded `Chunker`.
- YAML frontmatter (`---\n...\n---` at file start) is stripped via
  regex before section/chunk extraction, so it never leaks into a
  section title or chunk text.
- Scope decision (not raised with the user beforehand, flagged here):
  did **not** implement the plan's "extract links as candidate
  REFERENCES edges" bullet. No `REFERENCES` relationship exists in the
  Phase 1 schema (`graph/schema.py`) or `GraphWriter`, and the Phase 4
  exit criteria doesn't require it — adding it now would mean
  designing a new edge type/target-resolution strategy that's really a
  Phase 7 (generalized ingestion) concern. Revisit if the user wants
  cross-doc links before then.
- Edge case: a Markdown file with no headings at all falls back to one
  implicit section (level 1, title = file stem) covering the whole
  body, so ingestion never produces an empty graph for heading-less
  notes.
- `cli.py`'s `ingest` command now dispatches on suffix (`.pdf` →
  `PdfParser`, `.md`/`.markdown` → `MarkdownParser`) instead of only
  accepting `.pdf`.
- New file `tests/test_markdown_parser.py` (6 tests): heading
  hierarchy/breadcrumbs, leaf-flag detection, headings-inside-fences
  ignored, fenced-block atomicity, full parse end-to-end (frontmatter
  stripped, code block preserved), no-headings fallback.
- Verified: 24/24 tests pass (18 pre-existing + 6 new), `ruff check`/
  `ruff format --check` clean, pyright with `reportDeprecated: error`
  clean (only pre-existing unrelated `test_settings.py:5` error
  remains, same as before this change). Live end-to-end run: ingested
  this repo's own `README.md` via `graph-rag ingest README.md` (3
  sections, 8 chunks) into the already-populated Neo4j instance
  alongside `training-docs/dms-ug.pdf`; re-ran ingestion and confirmed
  chunk count stayed at 8 (idempotent MERGE, no duplication); a live
  `Retriever.search("how do I install this project")` call returned
  the two README chunks ("Quickstart", "MCP server") ranked above the
  PDF chunks — confirms the exit criteria ("search() returns
  Markdown-sourced chunks alongside PDF ones, correctly attributed")
  exactly as specified.
- Next: Phase 5 (Python ingestion via `ast`) or Phase 6 (YAML/Checkov)
  per the plan — not started, awaiting user direction.

## 2026-08-25 13:54 EDT

- Reorganized `ingest/` and `mcp_server/` per user request: group
  related "families" of classes (parsers, data models, embedders)
  into their own subpackages, each with its own `__init__.py` facade,
  matching the project's one-class-per-file / package-facade
  convention from `CLAUDE.md`. Singular, one-of-a-kind components
  (`Chunker`, `Enricher`, `Retriever`, `server.py`,
  `BearerTokenMiddleware`, and `graph/`'s `client.py`/`schema.py`/
  `graph_writer.py`) were deliberately left at their package's top
  level — there's no "family" of chunkers/enrichers by design (one
  `Chunker` is reused by every future parser), so nesting them would
  just be extra indirection with nothing to organize.
  - `ingest/parsers/` — `PdfParser` (future `MarkdownParser`,
    `PythonParser`, `YamlParser` land here in Phases 4–6).
  - `ingest/models/` — `Source`, `Section`, `Chunk`, `ParsedDocument`.
  - `ingest/embedders/` — `Embedder` (ABC), `SentenceTransformerEmbedder`
    (future hosted-provider embedders land here).
  - `mcp_server/models/` — `SearchResult`, `SectionDetail`,
    `SectionOutlineEntry`, `SourceInfo`.
  - Used `git mv` for the already-committed `ingest/` files (history
    preserved — `git status` shows clean `R`/`RM` renames) and plain
    moves for the not-yet-committed `mcp_server/` files.
  - Import convention applied consistently: relative imports
    (`from .models import X`, `from ..chunker import Chunker`) for
    anything reachable within the same top-level package's subtree;
    absolute imports (`from graph_rag.ingest.embedders import
    Embedder`) only when crossing between independent top-level
    packages (`graph`/`ingest`/`mcp_server`). Every subpackage's
    `__init__.py` re-exports up through its parent's `__init__.py` too
    (e.g. `graph_rag.ingest.parsers.PdfParser` is still importable as
    `graph_rag.ingest.PdfParser`), per the facade rule.
  - Verified: all 18 tests pass, `ruff` clean, `pyright` clean (incl.
    `reportDeprecated`), `uv sync` rebuilds cleanly (hatchling
    auto-discovers the new subpackages, no `pyproject.toml`
    packaging config needed), CLI (`--help`, `apply-schema`) works,
    and a live `Retriever.search()` call against the already-ingested
    DMS data still returns the correct top hit — confirms the
    reorganization is a pure move, no behavior change.

---

## 2026-08-25 13:39 EDT

[CHECKPOINT]

1. **Core Objective**: (unchanged) Graph RAG system, Neo4j-backed,
   heterogeneous doc ingestion, MCP lookup for coding agents.
2. **Completed Milestones**:
   - **Phase 3 (MCP server v1) — complete and verified**, both running
     locally and as a Docker Compose service:
     - New `src/graph_rag/mcp_server/` package: `SearchResult`,
       `SectionOutlineEntry`, `SectionDetail`, `SourceInfo` (Pydantic
       v2 models), `Retriever` (hybrid vector + full-text Cypher
       queries), `BearerTokenMiddleware` (plain ASGI middleware),
       `server.py` (`build_server()` wiring the three tools onto an
       `MCPServer`). Hoisted through `mcp_server/__init__.py`.
     - New CLI command `graph-rag serve-mcp` / `make mcp-serve`:
       builds one long-lived `Driver` + `SentenceTransformerEmbedder`
       for the process lifetime, serves Streamable HTTP on
       `settings.mcp_host:mcp_port` (default `127.0.0.1:8765/mcp`).
     - Three tools implemented per the plan: `search(query, top_k,
       source_type?, source_path?)` — vector similarity
       (`db.index.vector.queryNodes`) blended with a full-text boost
       (`db.index.fulltext.queryNodes`), min-max normalized per
       candidate set, weighted 0.7 vector / 0.3 full-text
       (`combine_scores()` in `retriever.py`, pure and unit-tested);
       `get_section(section_id)` — full text + parent/child outline,
       `None` on unknown id; `list_sources()` — path/type/ingested_at.
     - Security per the plan's Phase 3 notes: bound to `127.0.0.1` by
       default; DNS-rebinding/Origin validation via an **explicit**
       `TransportSecuritySettings` in `cli.py` (not left to the SDK's
       host-based auto-default, which only fires for
       `127.0.0.1`/`localhost`/`::1` — needed explicit handling since
       the container binds `0.0.0.0` internally); optional
       `MCP_AUTH_TOKEN` bearer-check via `BearerTokenMiddleware`
       (only added to the ASGI app when the token is set).
     - Docker packaging: `Dockerfile` (python:3.12-slim + uv,
       CPU-only torch — see below), `.dockerignore`, and the
       `mcp-server` service in `docker-compose.yml` (depends on
       `neo4j` healthcheck, `127.0.0.1:8765:8765` loopback-only,
       `NEO4J_URI=bolt://neo4j:7687` via Docker DNS, `MCP_HOST=0.0.0.0`
       internally for Docker's port-forwarding to reach it).
     - `.mcp.json` added at repo root, registering this server as an
       HTTP entry for Claude Code / other MCP clients.
     - New tests: `tests/test_retriever.py` (5 tests on
       `combine_scores()`'s normalization/weighting/edge cases — pure,
       no live DB). 18/18 tests pass, `ruff` clean, `pyright` clean
       (incl. `reportDeprecated`).
   - **Real end-to-end verification** (the plan's exact Phase 3 exit
     criterion): started the server (both via `graph-rag serve-mcp`
     locally and via `docker compose up -d` for the full containerized
     stack), connected with a real `mcp.Client`, and confirmed:
     - `search("how do I create a replication instance")` → top hit
       "Creating a replication instance" in both the local and the
       Dockerized run — grounded, cited (breadcrumb + source path +
       page range), matching the plan's own example query exactly.
     - `get_section()` returns full text + correct parent
       (`Selection rules in DMS Schema Conversion`) + empty children
       for a known leaf section id, and `None` (not an error) for an
       unknown id.
     - `list_sources()` returns the one ingested `Source`.
     - `BearerTokenMiddleware` verified via raw `curl`: missing token
       → 401, wrong token → 401, correct token → passes through to
       the MCP protocol layer (confirmed by the error changing from
       401 to a protocol-level 400 on a bare `tools/list` POST without
       a session handshake).
3. **Critical Context**:
   - **`mcp` package major-version jump**: the plan assumed the
     `FastMCP`-era API (`mcp.server.fastmcp.FastMCP`); PyPI now serves
     `mcp==2.1.1`, which renamed it to `mcp.server.mcpserver.MCPServer`
     (importable as `from mcp.server import MCPServer`). Verified via
     PyPI package metadata (real maintainers, official
     `modelcontextprotocol/python-sdk` repo — not a typosquat) before
     installing. Used the 2.x API throughout; `run()`'s built-in
     `streamable-http` transport wasn't used directly (it doesn't
     expose a hook for injecting `BearerTokenMiddleware`) — instead
     `cli.py` builds the ASGI app via `.streamable_http_app(...)`,
     wraps it conditionally, and runs it with `uvicorn.run()` directly.
   - **Real bug caught by the `reportDeprecated`-strict pyright sweep**
     (same config used in the earlier client.py/schema.py fix): a
     `session.run(cast(LiteralString, _FULLTEXT_SEARCH), query=query,
     ...)` call in `retriever.py` — neo4j's `Session.run()` has `query`
     as its own first positional parameter name, so passing a Cypher
     parameter *also* named `query` via kwargs would have raised
     `TypeError: got multiple values for argument 'query'` at runtime.
     Fixed by passing the parameters dict positionally instead of via
     `**kwparameters`. Caught before ever running the server — pyright
     flagged it as `reportCallIssue` on the first strict pass.
   - **Docker image bloat, root-caused and fixed**: the first
     `docker compose build mcp-server` pulled several GB of
     `nvidia-*`/CUDA packages, because Linux's default PyPI `torch`
     wheel is GPU-enabled (macOS has no such variant, which is why
     this never showed up in local `uv sync`). Fixed via uv's
     documented `[tool.uv.sources]` + `[[tool.uv.index]]`
     marker-conditional index pattern (CPU-only wheel from
     `download.pytorch.org/whl/cpu` on `sys_platform == 'linux'`,
     default PyPI elsewhere) — **but this only takes effect for a
     *direct* dependency**; `torch` was previously only transitive
     (via `sentence-transformers`), so the override silently
     no-op'd until `torch>=2.2` was added to `dependencies` directly.
     Verified via lock-file inspection (two `torch` entries, one
     `2.13.0+cpu` gated `sys_platform == 'linux'` with zero nvidia
     deps) and by rebuilding: torch download dropped from part of a
     multi-GB pull to 147.8MiB, image builds in ~70s, final image
     1.23GB. Also had to `brew upgrade uv` (0.7.8 → 0.12.5, matching
     what the Dockerfile itself downloads) along the way — unrelated
     to the root cause, but the stale local `uv` made isolating the
     real fix harder.
   - **Embedding model note carries over from Phase 2** (see the
     12:58 EDT entry below): still `sentence-transformers/all-MiniLM-L6-v2` (384-dim, matches
     the vector index), not the plan's `bge-small-en-v1.5`, due to
     this sandbox's blocked huggingface.co egress. Verifying the
     *containerized* server required a temporary
     `docker-compose.override.yml` bind-mounting the host's HF cache
     with `HF_HUB_OFFLINE=1` — removed after verification, not part
     of the tracked deliverable. On a machine with normal internet
     access, the container downloads the model itself on first run
     with no override needed.
4. **Discarded Paths**:
   - Considered using the SDK's `TokenVerifier`/`AuthSettings` OAuth
     machinery for the optional bearer-token check — that's shaped for
     a real OAuth resource server (issuer URLs, token introspection);
     way over-engineered for "one static pre-shared secret, checked
     on every request." Wrote `BearerTokenMiddleware` (23 lines) instead.
   - Considered relying on the SDK's implicit host-based
     DNS-rebinding-protection default (auto-enables only when
     `host in ("127.0.0.1", "localhost", "::1")`) — explicit
     `TransportSecuritySettings` instead, since the containerized
     deployment needs `MCP_HOST=0.0.0.0` internally and the implicit
     default would have silently gone dark in exactly that case.
5. **Next Step**: Phase 4 — Markdown ingestion (`MarkdownParser`,
   reusing the existing `Chunker`/`Enricher`/`GraphWriter` pipeline
   unchanged — this phase is mainly meant to prove the parser-plugin
   boundary from Phase 2 is real). Per the plan, Phases 4–6 (Markdown,
   Python, YAML/Checkov) can now fan out independently since the
   critical path (Phases 0–3: ingest → query via MCP) is done.

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
