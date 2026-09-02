---
mode: agent
description: Add ingestion support for a new file type (a new parser class).
---
Add a parser for a new file type: ${input:fileType:e.g. reStructuredText / .rst}.

This must be a small, isolated change — a new parser class registered in the
registry. Do **not** modify the chunker, pipeline, graph writer, or existing
parsers unless the new type genuinely requires it (say why if so).

1. Read an existing parser to match the pattern — e.g.
   `src/graph_rag/ingest/parsers/markdown_parser.py` (prose) or
   `python_parser.py` (code). Note the return type (`ParsedDocument` / sections /
   code entities) and how it's registered.
2. Create `src/graph_rag/ingest/parsers/<snake_case>_parser.py` with one class,
   `<PascalCase>Parser`, filename = class name in snake_case. One class per file.
3. Register it: add it to the parser registry keyed by file extension, and
   re-export it from the package `__init__.py` (`from .x_parser import XParser`,
   add to `__all__`).
4. Heavy or optionally-licensed third-party imports go **lazily inside the parse
   method** with an actionable error if missing (see `pdf_parser.py`'s handling
   of `pymupdf`) — never at module top. If it needs a new dependency, add it as
   an optional extra in `pyproject.toml`, not a base dependency.
5. Tests in `tests/test_<snake_case>_parser.py`: a normal parse, an empty file,
   and the missing-dependency error path if step 4 applies.
6. Verify: `make lint`, `uv run ruff format --check .`, `make test`. Run
   `make eval` only if you touched chunking/embedding/ranking.
7. Update `CHANGELOG.md` (`[Unreleased]`) and the file-type list in `README.md`
   and `docs/ARCHITECTURE.md`.

Report in the What changed / Verification run / Remaining issues format.
