---
mode: agent
description: Set up a local graph-rag dev environment from a fresh clone.
---
Get this repo running locally from a fresh clone.

Steps:
1. `cp .env.example .env`. Leave `NEO4J_PASSWORD=changeme-local-dev` unless the
   user asked to change it. Never commit `.env`.
2. `make install` (`uv sync --all-extras`).
3. `make fetch-model` — downloads `sentence-transformers/all-MiniLM-L6-v2` into
   `models/all-MiniLM-L6-v2/` (~87 MB). Needs network once; after that
   ingestion/tests can run with `HF_HUB_OFFLINE=1`.
4. `make up` — starts Neo4j in Docker. The stock `neo4j` image auto-installs the
   APOC + GDS plugins from `NEO4J_PLUGINS` in `docker-compose.yml`; nothing to
   do. Wait until `make status` prints `Neo4j is reachable.`
5. `make apply-schema` — constraints, full-text indexes, vector indexes.
6. Verify: `make lint`, `make test`.

Report which steps ran and their output. If `make fetch-model` can't reach
`huggingface.co`, say so — ingestion will fail without the model.
