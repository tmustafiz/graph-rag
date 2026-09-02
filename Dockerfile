# syntax=docker/dockerfile:1

# Base images are overridable so the image can be built against whatever
# hardened registry a restricted environment mandates (Docker Hardened Images,
# Chainguard, an internal mirror, ...). Defaults are what CI builds and scans.
#   BUILDER_IMAGE  needs a shell + glibc — uv installs a glibc standalone CPython.
#                  e.g. dhi.io/python:3-dev
#   RUNTIME_IMAGE  needs glibc + libgcc + libstdc++ + libssl/libffi/libz +
#                  ca-certificates, and a non-root user; shell-less is ideal.
#                  e.g. dhi.io/python:3 (its own Python is unused — the app runs
#                  on the standalone CPython copied from the builder).
# See docs/operations.md "Restricted / hardened-registry environments".
ARG BUILDER_IMAGE=python:3.14-slim-trixie
ARG RUNTIME_IMAGE=gcr.io/distroless/cc-debian13:nonroot
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.5

# Pinned uv as its own stage so the binary source is overridable (UV_IMAGE) —
# e.g. a local scratch image built from the uv release tarball if ghcr.io is
# unreachable.
FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------------------
# Builder: resolve deps and build the app venv against a self-contained
# CPython (python-build-standalone, via uv) so the runtime image needs no
# system Python at all.
# ---------------------------------------------------------------------------
FROM ${BUILDER_IMAGE} AS builder

# Pull the latest point-release fixes into the (throwaway) build stage. Skipped
# automatically on a base with no apt (e.g. an already-patched hardened image).
RUN if command -v apt-get >/dev/null 2>&1; then \
        apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*; \
    fi

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# Install a standalone CPython, then drop its bundled pip / ensurepip — the
# runtime never installs packages, and pip's _vendor tree is the only thing
# dragging known-vulnerable msgpack / setuptools copies into the image.
RUN uv python install 3.13 \
 && rm -rf /opt/python/*/lib/python3.13/site-packages/pip \
           /opt/python/*/lib/python3.13/site-packages/pip-*.dist-info \
           /opt/python/*/lib/python3.13/ensurepip \
           /opt/python/*/lib/python3.13/test \
           /opt/python/*/lib/python3.13/idlelib

# Dependency layer (changes rarely) — resolved from the lockfile, project itself
# not installed yet so this stays cached across source edits.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --extra pdf --no-dev --frozen --no-install-project --no-editable

# Project layer — build a wheel from src/ and install it into the venv
# (--no-editable, so the runtime image never needs the source tree).
COPY src/ src/
COPY README.md LICENSE NOTICE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --extra pdf --no-dev --frozen --no-editable

# ---------------------------------------------------------------------------
# Runtime: needs glibc + libgcc + libstdc++ (torch's C++ runtime) + libssl /
# libffi / libz (the standalone CPython's stdlib) + ca-certificates, a
# non-root user, and ideally no shell or package manager. distroless "cc"
# (the default) and dhi.io/python:3 both fit — both run as uid 65532.
# ---------------------------------------------------------------------------
FROM ${RUNTIME_IMAGE}

# The interpreter the venv's scripts and symlinks resolve to (same path as in
# the builder, so the venv stays valid).
COPY --from=builder /opt/python /opt/python
# Numeric uid/gid (not the "nonroot" name) so the chown resolves on any base.
COPY --from=builder --chown=65532:65532 /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}"
WORKDIR /app
EXPOSE 8765
USER 65532

ENTRYPOINT ["/app/.venv/bin/grag-mcp"]
CMD ["serve-mcp"]
