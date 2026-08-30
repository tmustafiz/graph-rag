# Contributing to graph-rag

Thanks for taking the time to contribute. This project is Apache-2.0 licensed;
by submitting a contribution you agree it is licensed under the same terms.

## Ways to help

- **Report bugs** and **request features** via the issue templates.
- **Improve docs** — the README, `docs/`, and docstrings.
- **Add a parser** for a new file type (self-contained plugin — see below).
- **Wire up an embedder** backend (OpenAI, Voyage, Cohere, Ollama, …) behind
  the existing `Embedder` interface.
- **Pick up a `good first issue`** or comment on an open one to claim it.

Please open an issue to discuss anything non-trivial before sending a large PR.

## Development setup

Requires Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and Docker (for Neo4j).

```bash
git clone https://github.com/tmustafiz/graph-rag.git
cd graph-rag
cp .env.example .env
make install        # uv sync --all-extras
make up             # start Neo4j
make apply-schema
make ingest         # load the sample corpus
```

## Checks that must pass

CI runs these on every PR; run them locally first:

```bash
make lint                       # ruff check
uv run ruff format --check .    # formatting
make test                       # pytest (88+ tests)
```

If you touched chunking, embedding, or ranking, also run the retrieval
regression eval (needs `make ingest` first):

```bash
make eval
```

## Code conventions

This repo follows a strict **one-class-per-file** layout, mirroring Java package
conventions with Pythonic naming:

- **One primary class per module.** Do not combine multiple primary classes in
  one file. Small helper dataclasses/enums used only by that class may live
  alongside it.
- **Naming.** Modules are `lower_snake_case`; classes are `PascalCase`; the
  filename is the class name converted to `snake_case`
  (`DataProcessor` → `data_processor.py`).
- **Package facade.** Every package has an `__init__.py` that imports its public
  classes from their submodules (`from .data_processor import DataProcessor`)
  and defines `__all__`, so callers write
  `from graph_rag.ingest import ParserRegistry`, never the submodule path.
- **Internal imports** are explicit relative imports within a package
  (`from .other_file import OtherClass`).

General style:

- Python 3.12+, full type hints, Pydantic v2 for data that crosses a boundary.
- `pathlib.Path` (not `os.path`), specific exception types (not bare `except`),
  dependency injection over module-level globals.
- Avoid single-letter variable names.
- `ruff` for lint and formatting (`line-length = 100`).
- Keep changes surgical — match surrounding style, don't refactor untouched code.
- Complete, runnable code — no stubs, `TODO`s, or "omitted for brevity". If
  something is blocked or unverified, say so and give the command to verify.

Adding a parser: implement the `Parser` protocol in
`src/graph_rag/ingest/parsers/`, register it in `parser_registry.py`, and add a
`tests/test_<name>_parser.py`. No other file should need to change.

## Commit / PR

- Branch off `main`; keep PRs focused.
- Reference the issue it closes (`Closes #123`).
- Update `CHANGELOG.md` under `[Unreleased]` and add/adjust tests.
- The PR template checklist should be green before requesting review.

## Progress log

`docs/progress.md` is the running project state across sessions. When you
complete something substantial or hit a natural breakpoint, append a
timestamped `[CHECKPOINT]` entry (most-recent-first) noting what's done and
verified, decisions worth preserving, and the next step.

## Reporting security issues

Do **not** open a public issue for security problems — see `SECURITY.md`.
