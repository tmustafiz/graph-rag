FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --extra pdf --no-dev --frozen --no-install-project

COPY src/ src/
COPY README.md ./
RUN uv sync --extra pdf --no-dev --frozen

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8765

CMD ["graph-rag", "serve-mcp"]
