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

### Working with an AI coding agent

[`AGENTS.md`](AGENTS.md) is the cross-agent guide (conventions, layout,
verification, PR workflow). GitHub Copilot picks up
[`.github/copilot-instructions.md`](.github/copilot-instructions.md)
automatically, `.github/prompts/` has task recipes (setup, run, deploy, add a
parser, cut a release), and `.github/workflows/copilot-setup-steps.yml`
pre-provisions the Copilot coding agent's environment.

## Development setup

Requires Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and Docker (for Neo4j).

```bash
git clone https://github.com/tmustafiz/graph-rag.git
cd graph-rag
cp .env.example .env
make install                                       # uv sync --all-extras
make fetch-model                                   # local embedding model (~87 MB)
make up                                            # start Neo4j
make apply-schema
make ingest INGEST_PATH=examples/checkov-policies  # or point at your own docs
```

The repo ships no document corpus — `make ingest` requires `INGEST_PATH`. Point
it at your own files, or at `examples/` to try the tooling.

## Checks that must pass

CI runs these on every PR; run them locally first:

```bash
make lint                       # ruff check
uv run ruff format --check .    # formatting
make test                       # pytest (88+ tests)
```

If you touched chunking, embedding, or ranking, also run the retrieval
regression eval (self-contained — it ingests its own fixture corpus):

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

- **Branch off the active milestone's integration branch** (`release/vX.Y.0`),
  not `main`, and target your PR at that same branch. Feature work for an
  in-progress milestone never lands on `main` directly — see
  [Branching model](#branching-model) below. Keep PRs focused.
- Reference the issue it closes (`Closes #123`).
- Update `CHANGELOG.md` under `[Unreleased]` and add/adjust tests.
- The PR template checklist should be green before requesting review.

## Branching model

This project uses a git-flow-lite model so an in-progress milestone can stabilise
without destabilising `main`:

- `main` only ever moves by a release merge or a hotfix; it always points at the
  latest released tag.
- Each milestone has **one long-lived integration branch**, `release/vX.Y.0`,
  cut from `main`. It is the base for every feature branch in that milestone, and
  the target for their (squash-merged) PRs.
- `pyproject.toml`'s version is bumped only in the release-prep PR near the end
  of the milestone; until then it reads the last released version.
- When the milestone is done: release-prep PR into `release/vX.Y.0`, then a
  **merge-commit** PR from `release/vX.Y.0` into `main`, then the `vX.Y.0` tag on
  the merge commit. Full checklist in [`docs/RELEASING.md`](docs/RELEASING.md).

`main` and `release/**` are protected: PR + green CI required, no direct pushes.

## Planning

Planning lives on GitHub, not in the repo:

- [Roadmap board](https://github.com/users/tmustafiz/projects/6) and
  [milestones](https://github.com/tmustafiz/graph-rag/milestones) for what's
  planned and when.
- [Issues](https://github.com/tmustafiz/graph-rag/issues) for individual work
  items — use the `area:` labels.
- [Discussions](https://github.com/tmustafiz/graph-rag/discussions) for open
  questions and proposals.

Capture design decisions and context in the issue and the PR that implements it,
so the "why" is discoverable from history. See also
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Releasing

Publishing is automated by `.github/workflows/release.yml` using PyPI
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC — no API
token is stored anywhere).

One-time setup (maintainer, on PyPI):

1. Create the `grag-mcp` project's trusted publisher at
   <https://pypi.org/manage/account/publishing/>: owner `tmustafiz`, repo
   `grag-mcp`, workflow `release.yml`, environment `pypi`.
2. In the GitHub repo, add an Environment named `pypi` (Settings → Environments).
   Optionally restrict it to tag pushes and add required reviewers.
3. Optional dry-run path: repeat for `test.pypi.org` with environment `testpypi`.

Cutting a release (see [`docs/RELEASING.md`](docs/RELEASING.md) for the full
checklist):

1. On the milestone's `release/vX.Y.0` branch, open a **release-prep PR**: bump
   `version` in `pyproject.toml`, move the `CHANGELOG.md` `[Unreleased]` items
   under a new `[x.y.z]` heading, add a fresh empty `[Unreleased]`, update the
   link definitions. Merge it into `release/vX.Y.0`.
2. Open a PR from `release/vX.Y.0` into `main` and merge it with a **merge
   commit** (not squash — that would flatten the whole milestone).
3. Tag the merge commit on `main` and push:
   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```
   The workflow checks the tag matches `pyproject.toml`, builds the
   wheel + sdist, runs `twine check`, and publishes to PyPI.
4. Delete `release/vX.Y.0` once the tag build is green.
5. To rehearse against TestPyPI first, run the workflow manually
   (Actions → Release → Run workflow → target `testpypi`).

## Reporting security issues

Do **not** open a public issue for security problems — see `SECURITY.md`.
