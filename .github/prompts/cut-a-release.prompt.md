---
mode: agent
description: Prepare a grag-mcp release (version bump, changelog, tag).
---
Prepare the ${input:version:e.g. 0.2.0} release of `grag-mcp`.

Publishing is automated: pushing a `vX.Y.Z` tag triggers
`.github/workflows/release.yml`, which builds and publishes to PyPI via Trusted
Publishing (no stored token). Your job is to prepare the commit and tag.

1. Bump `version` in `pyproject.toml` to `${input:version}`.
2. `CHANGELOG.md`: turn the `[Unreleased]` section into
   `[${input:version}] - <today's date, YYYY-MM-DD>`, add a fresh empty
   `[Unreleased]`, and update the link definitions at the bottom.
3. Sanity-check the build:
   ```bash
   uv build
   uvx twine check dist/*
   test "$(uv version --short)" = "${input:version}"
   ```
4. Commit on a branch (`release/v${input:version}`), open a PR that says
   `Closes #<n>` if there's a release issue. Do **not** merge or push the tag —
   the repo owner does that after merge:
   ```
   git tag v${input:version} && git push origin v${input:version}
   ```
5. Note in the PR that the PyPI Trusted Publisher for project `grag-mcp` and the
   `pypi` GitHub Environment must already exist (one-time setup, owner's task).

Do not rename the distribution, the import package, or the MCP server identity —
see `AGENTS.md` → "Names".
