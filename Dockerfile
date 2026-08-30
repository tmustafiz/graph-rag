# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Builder: resolve deps and build the app venv against a self-contained
# CPython (python-build-standalone, via uv) so the runtime image needs no
# system Python at all.
# ---------------------------------------------------------------------------
FROM python:3.14-slim-trixie AS builder

# Pull the latest Debian point-release fixes into the (throwaway) build stage.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

# Pinned uv (static binary image — just /uv and /uvx).
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

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
# Runtime: distroless "cc" — glibc + libgcc + libstdc++ (torch's C++ runtime)
# + ca-certificates + tzdata. No shell, no package manager, no system Python.
# Runs as the non-root user (uid 65532).
# ---------------------------------------------------------------------------
FROM gcr.io/distroless/cc-debian13:nonroot

# The interpreter the venv's scripts and symlinks resolve to (same path as in
# the builder, so the venv stays valid).
COPY --from=builder /opt/python /opt/python
COPY --from=builder --chown=nonroot:nonroot /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}"
WORKDIR /app
EXPOSE 8765

ENTRYPOINT ["/app/.venv/bin/graph-rag"]
CMD ["serve-mcp"]
