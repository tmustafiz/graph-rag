# Releasing graph-rag

This project ships one release per milestone. Milestone work is isolated on a
long-lived integration branch so `main` stays releasable at all times; `main`
only ever moves by a release merge or a hotfix.

## Branching model (git-flow-lite)

```
main            ──●────────────────────────────────●──────────────▶  (tags: v0.5.0 … v0.6.0)
                   \                              ↑ merge commit
release/v0.6.0      ●──●────●────●────●────●──────●   (integration; deleted after the tag)
                       \    \    \         \
feat/… branches         ●    ●    ●         ●         (squash-merged into release/v0.6.0)
```

- **`main`** — always points at the latest released tag. Protected: PR + green
  CI, no direct pushes. Never a feature-PR target.
- **`release/vX.Y.0`** — one per milestone, cut from `main` when the milestone
  starts. Exactly one active at a time. Protected the same way. This is the base
  for every feature branch in the milestone and the target for their PRs.
- **`feat/<slug>` / `fix/<slug>`** — one per issue, branched from
  `release/vX.Y.0`, PR'd back into it, **squash-merged** by the repo owner.
- **`hotfix/<slug>`** — for a fix to an already-released version; branched from
  `main`.

During the milestone:

- `pyproject.toml`'s `version` stays at the **last released** value. It is bumped
  once, in the release-prep PR (below).
- `CHANGELOG.md` entries accumulate under `[Unreleased]`, one per feature PR, as
  usual.
- CI (`.github/workflows/ci.yml`) runs on every PR into `release/**` and on every
  push to it, so cross-feature interaction bugs surface before release.

## Starting a milestone (repo owner)

1. `git switch main && git pull`
2. `git switch -c release/vX.Y.0 && git push -u origin release/vX.Y.0`
3. Add a branch-protection rule for `release/**` (or confirm the existing one
   covers it): require a PR, require the `lint` / `test` / `eval` / `image`
   status checks, block direct pushes and force-pushes.
4. Post a `[CHECKPOINT]` comment on the milestone tracking issue naming the
   branch and the intended issue order.

## During the milestone (contributors / agents)

Per issue: branch from `release/vX.Y.0`, implement, verify

```bash
make lint && uv run ruff format --check . && make test
make eval        # only if you touched chunking / embedding / ranking
```

commit, push, open a PR **with base `release/vX.Y.0`** and body `Closes #<n>`.
The repo owner squash-merges, then **closes `#<n>` manually** — GitHub only
auto-closes from the default branch, and these PRs target `release/*`. The
`Closes #<n>` line is still required: the release PR (below) collects them.

## Cutting the release (repo owner)

Preconditions: `release/vX.Y.0` green, and every milestone issue closed — done
by hand as each feature PR merges (see above), since none auto-close.

1. **Release-prep PR into `release/vX.Y.0`:**
   - Bump `version` in `pyproject.toml` to `X.Y.0`.
   - `CHANGELOG.md`: rename `[Unreleased]` → `[X.Y.0] - <YYYY-MM-DD>`, add a
     fresh empty `[Unreleased]`, update the link definitions at the bottom.
   - Verify locally:
     ```bash
     uv build && uvx twine check dist/*
     test "$(uv version --short)" = "X.Y.0"
     ```
   - Merge into `release/vX.Y.0` (squash is fine).
2. **Milestone PR `release/vX.Y.0` → `main`.** Let CI run. Merge with a **merge
   commit** — *not* squash, which would flatten the milestone into one commit and
   break the branch's ancestry with `main`.
3. **Tag on `main`:**
   ```bash
   git switch main && git pull
   git tag vX.Y.0 && git push origin vX.Y.0
   ```
   `release.yml` checks the tag matches `pyproject.toml`, builds the wheel +
   sdist, runs `twine check`, publishes to PyPI via Trusted Publishing, and
   builds + pushes the multi-arch image to GHCR.
4. Confirm the PyPI project and GitHub Release look right, then
   `git push origin --delete release/vX.Y.0` and delete the local copy.
5. Move the GitHub milestone to closed; the next milestone starts from step 1 of
   "Starting a milestone".

Dry run: Actions → Release → Run workflow → target `testpypi` (publishes the
dists to TestPyPI, builds the image without pushing).

## Hotfix to a released version

Needed when a bug in `vX.Y.0` must ship as `vX.Y.Z` while the next milestone is
in progress.

1. `git switch main && git switch -c hotfix/<slug>` (branches off the `vX.Y.0`
   tag, since `main` points there).
2. Fix + test + CHANGELOG entry. PR into `main`.
3. After merge: bump `pyproject.toml` to `X.Y.Z` (its own tiny PR or folded into
   the fix PR), then `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. Merge `main` into the active `release/*` branch so the in-progress milestone
   carries the fix.

## One-time setup (already done for `grag-mcp`)

- PyPI Trusted Publisher for project `grag-mcp`: owner `tmustafiz`, repo
  `grag-mcp`, workflow `release.yml`, environment `pypi`
  (<https://pypi.org/manage/account/publishing/>).
- GitHub Environment `pypi` (Settings → Environments); optionally restrict to tag
  pushes and add required reviewers. Repeat for `testpypi` for the dry-run path.
