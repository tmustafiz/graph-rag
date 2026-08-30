# Security Policy

## Supported versions

This project is pre-1.0. Security fixes are applied to `main` and released in
the next tagged version. Older tags are not patched.

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately via GitHub's
[private vulnerability reporting](https://github.com/tmustafiz/graph-rag/security/advisories/new)
(Security tab → "Report a vulnerability"), or email
**tanvir.mustafiz@gmail.com** with:

- a description of the issue and its impact,
- steps to reproduce or a proof of concept,
- affected version / commit.

You can expect an acknowledgement within 5 business days and a status update
within 10 business days. Coordinated disclosure is appreciated; we will credit
reporters in the release notes unless you ask otherwise.

## Deployment security model

graph-rag is **local-first** and its defaults assume a single-user, trusted
host:

- The MCP server and the `POST /ingest` endpoint bind to `127.0.0.1` by
  default. `docker-compose.yml` publishes them on the loopback interface only.
- Origin / DNS-rebinding protection is enforced unconditionally (see
  `TransportSecuritySettings` in `src/graph_rag/cli.py`), even when
  `MCP_HOST=0.0.0.0` inside a container.
- `MCP_AUTH_TOKEN` adds an optional bearer-token check as defense in depth.
- Neo4j credentials come from the environment (`.env`, never committed).

If you expose the server beyond localhost you are responsible for putting it
behind authentication and TLS. Ingested content and agent memory are stored
unencrypted in the Neo4j volume — treat that volume as sensitive.

## Scope

In scope: authentication/authorization bypass, path traversal in ingestion,
SSRF via ingestion inputs, injection into Cypher queries, secret leakage,
dependency vulnerabilities with a practical exploit path here.

Out of scope: issues requiring an already-compromised host, denial of service
from deliberately huge local inputs, and findings against the bundled Neo4j
image itself (report those upstream).
