---
mode: agent
description: Prepare a grag-mcp milestone release (version bump, changelog, release branch → main).
---
Prepare the ${input:version:e.g. 0.6.0} release of `grag-mcp`.

Publishing is automated: pushing a `vX.Y.Z` tag triggers
`.github/workflows/release.yml`, which builds and publishes to PyPI via Trusted
Publishing (no stored token). Your job is to prepare the branches, commit, and
tag. Full checklist: `docs/RELEASING.md`.

This project uses a git-flow-lite model: milestone work lives on a long-lived
`release/v${input:version}` integration branch cut from `main`; `main` only moves
by a release merge or a hotfix. Assume `release/v${input:version}` already exists
and every milestone issue is closed and green.

1. **Release-prep PR into `release/v${input:version}`:**
   - Bump `version` in `pyproject.toml` to `${input:version}`.
   - `CHANGELOG.md`: turn `[Unreleased]` into
     `[${input:version}] - <today's date, YYYY-MM-DD>`, add a fresh empty
     `[Unreleased]`, update the link definitions at the bottom.
   - Sanity-check the build:
     ```bash
     uv build
     uvx twine check dist/*
     test "$(uv version --short)" = "${input:version}"
     ```
   - Open the PR against `release/v${input:version}` (base branch, **not**
     `main`), `Closes #<n>` for the tracking issue. The repo owner merges it
     (squash is fine here).

2. **Milestone PR `release/v${input:version}` → `main`:** open it, let CI run.
   The repo owner merges it with a **merge commit** (not squash — that would
   flatten the whole milestone into one commit). Do not merge it yourself.

3. Do **not** push the tag — the repo owner does that after the merge:
   ```
   git tag v${input:version} && git push origin v${input:version}
   ```
   The workflow checks the tag matches `pyproject.toml`, builds the wheel + sdist,
   runs `twine check`, publishes to PyPI, and pushes the multi-arch image.

4. After the tag build is green, `release/v${input:version}` is deleted; the next
   milestone cuts a fresh branch from `main`.

5. Note in the PR that the PyPI Trusted Publisher for project `grag-mcp` and the
   `pypi` GitHub Environment must already exist (one-time setup, owner's task).
   To rehearse against TestPyPI first: Actions → Release → Run workflow → target
   `testpypi`.

Do not rename the distribution, the import package, or the MCP server identity —
see `AGENTS.md` → "Names".
