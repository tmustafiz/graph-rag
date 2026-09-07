# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Maven / Gradle project model. New `MavenParser` (`pom.xml`, stdlib
  `xml.etree`) and `GradleParser` (`build.gradle` / `build.gradle.kts` /
  `settings.gradle(.kts)`, tree-sitter `groovy` / `kotlin`) turn build files
  into `(:Module {group, artifact, version, path, build_tool, packages,
  source_roots})` nodes with `(:Module)-[:DEPENDS_ON {scope}]->(:Module)` and
  `-[:DEPENDS_ON_EXTERNAL {gav, scope}]->(:ExternalArtifact)` edges. Maven reads
  `<parent>` inheritance, `<properties>` `${...}` interpolation, the reactor
  `<modules>` list, `<dependencies>` GAV + `<scope>`, and
  `<build><sourceDirectory>`; Gradle does a shallow tree-sitter pass for
  `group` / `version` / `rootProject.name`, `include`, `dependencies { }`
  coordinates (configuration → `scope`), `project(':x')` deps, and `srcDirs`.
  Source-root discovery adds `src/test/java` and `target/generated-sources` /
  `build/generated` when present. On a directory ingest, build files parse
  first and a new `ProjectModelResolver` then wires
  `(:Source)-[:IN_MODULE]->(:Module)` (nearest module dir), promotes sibling
  dependencies (`project(':x')` / matching GAV → `DEPENDS_ON`), and sets
  `external` (bool) on every `(:CodeEntity)-[:IMPORTS]->(:CodeEntity)` edge —
  `false` for first-party / in-project targets, `true` for third-party. New
  `module_path` / `external_artifact_gav` constraints and a `module_fulltext`
  index. ([#70](https://github.com/tmustafiz/graph-rag/issues/70))
- Spring / Java application-config parser (`ConfigFileParser`, stdlib + PyYAML,
  no extra). Handles `application*` / `bootstrap*` (`.yml` / `.yaml` /
  `.properties`) and any `*.properties` / `*.yml` under a `resources`
  directory; registered ahead of `YamlParser`, which still gets Checkov custom
  policies (name-matched `.yml` with `metadata.id` + `definition` is handed
  back) and all other generic YAML. Each file becomes a `ConfigFile` plus a
  flattened `ConfigProperty` list — YAML nesting collapsed to dotted keys
  (list items `[i]`), `.properties` read line-wise (comment markers, `\` line
  continuations, `#---` multi-document separators), real line numbers kept.
  Spring profile resolved from an `application-<profile>` filename or a
  `spring.config.activate.on-profile` key; `${a.b:default}` placeholders become
  `(:ConfigProperty)-[:REFERENCES]->(:ConfigProperty)` edges within the file.
  A `Section` + one `Chunk` per profile makes config searchable via `search`,
  with secret-looking keys (`password` / `secret` / `token` / `credential` /
  `key`) redacted in the chunk text (real value stays on the node). New
  `config_file_path` / `config_property_id` constraints and
  `config_property_fulltext` index. Feeds `@Value` / `@ConfigurationProperties`
  resolution in the Spring bean model.
  ([#72](https://github.com/tmustafiz/graph-rag/issues/72))
- Structured Java annotation model. `JavaParser` now captures annotations on
  types, methods, constructors, fields, and parameters as `Annotation` nodes
  (`(CodeEntity)-[:ANNOTATED_WITH]->(:Annotation {fqn, name, target, attributes,
  line})`), keyed by `(owner, target, fqn, line)`. Attribute values (string /
  number / boolean / class-literal / enum-constant / array / nested annotation)
  are parsed into a map and persisted as a JSON string (`attributes` property);
  the annotation FQN is resolved against the file's imports, falling back to the
  simple name. Type-level annotations (`@RestController` on a class, …), which
  were previously dropped entirely, are now captured. Fields carrying at least
  one annotation are emitted as `field` `CodeEntity`s (`kind` `field`,
  `qualified_name` `<type>#<field>`); plain fields stay folded into the owning
  type's `embed_text` as before. New `Annotation` uniqueness constraint and
  `annotation_name_fulltext` index. Foundation for the Spring bean / MVC /
  Spring-Data models. ([#69](https://github.com/tmustafiz/graph-rag/issues/69))

## [0.5.0] - 2026-09-06

### Added
- CSS / SCSS / Less stylesheet parser (`StylesheetParser`, opt-in
  `grag-mcp[css]` extra, tree-sitter `css` / `scss` / `less` grammars).
  `.css` / `.scss` / `.sass` / `.less` ingest as `Section` + `Chunk` (no
  `CodeEntity` — CSS has no call graph), so the plain `search` tool covers
  them: one `Section` per file (plus one per top-level `@media` / `@supports`)
  and one `Chunk` per rule, with SCSS nesting flattened into full selector
  paths (`.card .title`, `.card:hover`). Custom properties (`--x`), SCSS
  `$variables`, and `@mixin`s each also get a small name-bearing chunk.
  `@import` / `@use` / `@forward` resolve against the file tree to a new
  `(Source)-[:IMPORTS]->(Source)` edge (Sass built-ins and remote URLs
  skipped). `.sass` indented syntax and grammar-version gaps (`@extend`, some
  `@include` forms) degrade to a partial result with a logged warning.
  `ParsedDocument` gains `source_imports`. Sample under `examples/stylesheets/`.
  ([#66](https://github.com/tmustafiz/graph-rag/issues/66))
- Procedural SQL parsing (`ProceduralSqlExtractor`, run by `SqlParser` on the
  same `grag-mcp[sql]` extra). Stored procedures, functions, packages, package
  bodies, and triggers become `CodeEntity` nodes (`kind` ∈ `package` |
  `package_body` | `procedure` | `function` | `trigger`; packaged routines get
  `parent_qualified_name` = the package). Best-effort `CALLS` between routines,
  plus `READS` / `WRITES` edges to `:DbTable` (from `SELECT` vs
  `INSERT`/`UPDATE`/`DELETE`/`MERGE` in the body) and `ON` (trigger → its
  table). `sqlglot` parses T-SQL procedure bodies as an AST; PL/pgSQL `$$…$$`
  bodies and all of Oracle PL/SQL (packages, triggers) fall back to a
  delimiter-scoped regex sweep — accuracy ceiling documented per dialect in
  `docs/operations.md`. A routine whose body can't be analyzed still yields its
  header entity with a logged warning. `SqlParser` now also claims `.pks` /
  `.pkb` / `.prc` / `.fnc` / `.trg` / `.plsql`; `CodeEntity` gains `reads` /
  `writes` / `trigger_table`. Sample under `examples/sql-schema/procedures/`.
  ([#65](https://github.com/tmustafiz/graph-rag/issues/65))
- SQL schema parser (`SqlParser`, opt-in `grag-mcp[sql]` extra, backed by
  `sqlglot`). `.sql` DDL becomes a database-schema graph — not `CodeEntity` —
  of `:DbTable` / `:DbColumn` (type, nullability, default, PK flag) / `:DbView`
  (incl. materialized) / `:DbIndex` (covered columns) nodes keyed by
  dialect-qualified `qualified_name`. Foreign keys (inline, table-level, and
  `ALTER TABLE … ADD CONSTRAINT`, including when the `ALTER` is in a different
  migration file) yield `REFERENCES` edges at column and table level; a view's
  `SELECT` yields `DEPENDS_ON` edges (CTE names excluded); `HAS_COLUMN` /
  `HAS_INDEX` link a table to its parts. Dialect is `settings.sql_dialect`
  (env `GRAG_SQL_DIALECT`), overridable per file with a
  `-- grag:dialect=<name>` marker; an unknown dialect or unparseable file logs
  a warning and yields an empty `Source`. Tables and views are embedded and get
  vector + full-text indexes; wiring them into `search_code` / a
  `search_schema` tool is a follow-up. Sample migrations under
  `examples/sql-schema/`.
  ([#64](https://github.com/tmustafiz/graph-rag/issues/64))
- React-aware enrichment (`ReactEnricher`, run automatically by
  `JavaScriptParser` on `.jsx` / `.tsx` and `react`-importing `.js` / `.ts`).
  A `function` / `class` `CodeEntity` that returns JSX or extends
  `React.Component` is retagged `kind="component"`; each PascalCase JSX element
  it mounts that resolves to a local definition or an import becomes a new
  `(component)-[:RENDERS]->(component)` edge (lowercase host tags and
  unresolved names skipped, like `calls`); the hook calls (`useState`,
  `useEffect`, custom `useX`) and prop names (first-argument destructuring or
  `props.` member accesses) it uses are folded into `embed_text` / `signature`
  so `search_code("component that uses useAuth")` can match. `CodeEntity` gains
  a `renders` list; `GraphWriter` writes the `RENDERS` edge. Prop types and
  lifecycle call graphs are out of scope.
  ([#63](https://github.com/tmustafiz/graph-rag/issues/63))
- JavaScript / TypeScript source parser (`JavaScriptParser`, opt-in
  `grag-mcp[js]` extra, same `tree-sitter` backend). One parser for
  `.js` / `.mjs` / `.cjs` / `.jsx` / `.ts` / `.tsx` — TS and JSX are grammar
  variants of the same parse. Each file becomes a `module` `CodeEntity`
  (`qualified_name` is the project-relative path — nearest `package.json` /
  `tsconfig.json` ancestor — dotted and extension-stripped, `index` collapsed
  to its directory) carrying the file's `imports`, plus one entity per
  top-level `function` / `class` (+ `method` / `constructor`) / exported
  arrow-`const`, and signature-only `interface` / `type` / `enum`. `IMPORTS`
  covers ESM (`import`, `export … from`, `export *`, dynamic `import()`) and
  CommonJS (`require`); relative specifiers resolve against the project tree
  (named imports as `module.symbol`), bare specifiers (`react`) stay verbatim.
  Best-effort static `CALLS` for local, imported, and `this.*` shapes — same
  no-type-inference policy as `PythonParser`. JSDoc becomes
  `docstring`/`embed_text`. Sample project under `examples/js/`.
  ([#62](https://github.com/tmustafiz/graph-rag/issues/62))
- Java source parser (`JavaParser`, opt-in `grag-mcp[java]` extra, backed by
  `tree-sitter` + `tree-sitter-language-pack`). A `.java` file becomes a
  `Source` plus one `CodeEntity` per type (`class` / `interface` / `enum` /
  `record` / `annotation`) and per `method` / `constructor`, with
  package-prefixed, overload-safe `qualified_name`s, `CONTAINS` nesting,
  Javadoc as `docstring`/`embed_text`, `IMPORTS` from all four import forms,
  and best-effort static `CALLS` for the resolvable shapes (unqualified /
  `this` / `super` / statically-imported / `Type.method` on a known type) —
  same no-type-inference policy as `PythonParser`. Fields fold into the
  owning type's `embed_text`; there is no file-level `module` entity. Feeds
  `search_code` / `get_neighbors` / `compute-centrality` with no
  retrieval-side change. Sample tree under `examples/java/`.
  ([#61](https://github.com/tmustafiz/graph-rag/issues/61))

### Changed
- Code parsing is no longer Python-framed. `CodeEntity` carries a `language`
  property, `CodeSearchResult` exposes it, and `qualified_name` is documented
  as the single cross-language unique key that each parser must namespace.
  MCP instructions, `search` / `search_code` tool descriptions, the
  `compute-centrality` hint, README, and `docs/ARCHITECTURE.md` (new "Adding
  a language" section) now say "source code" rather than "Python". Groundwork
  for the Java / JavaScript-TypeScript / SQL / PL-SQL / CSS parsers; Python
  ingestion behavior is unchanged.
  ([#60](https://github.com/tmustafiz/graph-rag/issues/60))
- `examples/agent-memory/` instructions snippets (`AGENTS.md.example`,
  `copilot/copilot-instructions.md.example`): firmer, more directive wording
  so an agent actually writes memory during a task instead of treating it as
  optional — enumerated `remember` triggers per `kind` and an explicit
  "before you end your turn" checkpoint that folds saving into task
  completion. No behavior change; prompt text only.

## [0.4.0] - 2026-09-05

### Added
- `examples/agent-memory/`: copy-paste templates for a coding agent in a
  *downstream* project to use graph-rag's `remember`/`recall`/`forget` tools
  as its own persistent working memory, for both **Claude Code** and **VS
  Code Copilot Chat** — an always-on instructions snippet (`AGENTS.md` /
  `copilot-instructions.md`), a skill / prompt file, and a `SessionStart`
  hook (`session_start_recall.py`, using the `mcp` Python client) that
  recalls relevant memories into context automatically at the start of a
  session. ([#49](https://github.com/tmustafiz/graph-rag/issues/49))
- Opt-in split deployment: `docker-compose.knowledge.yml` /
  `docker-compose.memory.yml` run the knowledge base and agent memory as fully
  independent stacks — separate Neo4j, separate MCP server, optionally
  separate hosts — instead of `docker-compose.yml`'s combined default (still
  unchanged). Both build from the same `Dockerfile`: a `knowledge` target
  (full parser stack, incl. `[pdf]`; content-identical to the default image,
  just pinned to `--role knowledge`) and a `memory` target (bare package, no
  parsers, no `pymupdf` — smaller image and CVE-scan surface, pinned to
  `--role memory`). CI builds and scans both.
  ([#45](https://github.com/tmustafiz/graph-rag/issues/45))
- `serve-mcp --role knowledge|memory|all` (default `all`, unchanged behavior).
  `knowledge` and `memory` each start a standalone MCP server with only that
  half of the tools — `search`/`search_code`/`search_policies`/`get_section`/
  `get_outline`/`list_sources`/`find_policies_for`/`get_neighbors`/
  `get_central_code_entities`/`cite`/`ingest_path` for `knowledge`;
  `remember`/`recall`/`forget` for `memory` — so the knowledge base and agent
  memory can run as independent deployments, each against its own Neo4j.
  `POST /ingest` is only mounted for `knowledge`/`all`.
  ([#44](https://github.com/tmustafiz/graph-rag/issues/44))

### Fixed
- `recall(about_qualified_name=...)` could silently return zero results in a
  database with no `CodeEntity` nodes — the link was represented only as an
  `(:AgentMemory)-[:ABOUT]->(:CodeEntity)` edge, so the filter pattern could
  never match. `about_qualified_name` is now also stored as a plain property
  on `AgentMemory` (the source of truth for `recall`'s filter); the edge is
  still merged, best-effort, when a matching `CodeEntity` exists in the same
  database. ([#43](https://github.com/tmustafiz/graph-rag/issues/43))

## [0.3.0] - 2026-09-05

### Added
- Opt-in **query rewriting** ahead of `search` / `search_code` /
  `search_policies`. `GRAG_QUERY_REWRITE=1` rewrites a query into a few variants
  (acronym expansion, multi-part splitting, paraphrase), runs hybrid search for
  each, and fuses the hit sets (best `[0, 1]` score per hit) before the
  reranker/top-k stage. Two backends: an offline `HeuristicQueryRewriter`
  (built-in acronym map + `GRAG_QUERY_REWRITE_SYNONYMS` JSON override, no
  network) by default, and an opt-in `LlmQueryRewriter` when
  `GRAG_QUERY_REWRITE_MODEL` is set — an OpenAI-compatible `POST
  /v1/chat/completions` call (`GRAG_QUERY_REWRITE_API_BASE` points it at a local
  Ollama / LM Studio / vLLM endpoint) that fails at startup without a key and
  degrades to the unrewritten query on any request error.
  `GRAG_QUERY_REWRITE_MAX_QUERIES` (default 3) caps the variant count;
  `grag-mcp eval-retrieval --rewrite` measures a pass (composable with
  `--rerank`). Off by default, no new dependencies.
  ([#40](https://github.com/tmustafiz/graph-rag/issues/40))
- Config-selected hosted embedding backends. `GRAG_EMBEDDING_PROVIDER` selects
  `openai`, `ollama`, `voyage`, `cohere`, or `gemini` (unset keeps the local
  `all-MiniLM-L6-v2` — still the default, no API key). Each backend is a plain
  `httpx` REST call; no provider SDKs are added. `GRAG_EMBEDDING_MODEL` sets the
  model id and `GRAG_EMBEDDING_API_BASE` the endpoint (OpenAI-compatible
  gateways, non-local Ollama). `build_embedder()` probes the provider once at
  startup and fails fast if the vector width doesn't match `EMBEDDING_DIMENSIONS`
  rather than corrupting the index mid-ingest.
  ([#10](https://github.com/tmustafiz/graph-rag/issues/10))
- Optional cross-encoder reranking for `search` / `search_code` /
  `search_policies`. Set `GRAG_RERANK=1` to re-score the fused hybrid-search
  shortlist with `cross-encoder/ms-marco-MiniLM-L-6-v2` (read query + document
  together) before truncating to `top_k`; the fused score breaks ties. Off by
  default. The model is not baked into the image and there is no implicit Hub
  download — `make fetch-reranker` vendors it, or set `GRAG_RERANK_MODEL` to a
  local path (or a Hub id to allow a pull); with reranking on and nothing
  resolvable the process exits at startup. Search results gain a `rerank_score`
  field (the raw cross-encoder logit, `null` when off); `score` keeps its
  `[0, 1]` fused meaning unchanged. `grag-mcp eval-retrieval --rerank` prints a
  baseline-vs-reranked comparison; a naive-vector / hybrid / hybrid+rerank table
  is in the README. ([#14](https://github.com/tmustafiz/graph-rag/issues/14))

### Changed
- `grag-mcp prune-memory` runs with no arguments — the decay score is now
  `(1 + access_count) * exp(-days_since_last_recall / 30)` (reads
  `last_accessed_at`, which nothing used before), with a default `--threshold`
  of `0.5` (a never-recalled memory decays out ~3 weeks after creation; a
  reinforced one lasts months). Adds `--dry-run` (list what would be
  soft/hard-deleted, write nothing), `--list-important` (review the
  never-decaying `importance=True` memories), a `make prune` target, and a
  scheduling recipe in `docs/operations.md`.
- `recall` ranks by semantic relevance **plus** a flat boost for
  `importance=True` memories and a recency/frequency boost (a saturating
  function of `access_count` decayed by time since last recall) — previously
  those signals only fed pruning. `recall` also takes optional `kind`,
  `about_qualified_name`, and `session_id` filters, returns `last_accessed_at`
  and `access_count` on each hit, only reinforces hits above a similarity
  floor, and no longer 500s on a query with Lucene metacharacters.

## [0.2.0] - 2026-09-03

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
- The retrieval eval (`grag-mcp eval-retrieval`) covers `search_code` and
  `search_policies`, not just prose `search`, plus negative cases and the
  `top_k` boundary — 5 cases over 2 fixtures grew to 13 over 4. An `EvalCase`
  now carries a `tool` and an `expect_match` flag; the fixture corpus gains a
  `scheduler.py` module and a `policies.yaml`. Existing eval-set rows are
  unchanged (they default to `tool: search`).
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

### Fixed
- `search` / `search_code` / `search_policies` no longer 500 when the query
  contains a Lucene metacharacter (a pasted CLI flag like `--dry-run`, a
  `resource:type` string, code, a path). The query is escaped before it reaches
  `db.index.fulltext.queryNodes`, and any residual parser error (e.g. a bare
  `AND`/`OR`) is caught so the search degrades to vector-only instead of
  failing.

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

[Unreleased]: https://github.com/tmustafiz/graph-rag/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/tmustafiz/graph-rag/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/tmustafiz/graph-rag/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/tmustafiz/graph-rag/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/tmustafiz/graph-rag/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/tmustafiz/graph-rag/releases/tag/v0.1.0
