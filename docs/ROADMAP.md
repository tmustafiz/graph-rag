# Roadmap

Planning for graph-rag happens on GitHub, not in this repo.

- **Board:** <https://github.com/users/tmustafiz/projects/6> — every tracked item,
  grouped by `Status` and `Area`.
- **Milestones:** <https://github.com/tmustafiz/graph-rag/milestones> — what's
  targeted for each release.
- **Issues:** <https://github.com/tmustafiz/graph-rag/issues> — file a bug or
  request a feature; use the `area:` labels.
- **Discussions:** <https://github.com/tmustafiz/graph-rag/discussions> — open
  questions and ideas before they become issues.
- **Releases:** <https://github.com/tmustafiz/graph-rag/releases> — release notes
  (also mirrored in [CHANGELOG.md](../CHANGELOG.md)).

## Themes

Roughly what the near-term milestones are organized around:

- **Packaging & distribution** — PyPI / `uvx` and CVE-scanned images shipped;
  next is a multi-arch (`arm64` + `amd64`) image published on release.
- **Client reach** — stdio transport shipped; next is more MCP-registry listings.
- **Lower the trial barrier** — optional embedded graph backend so Neo4j/Docker
  isn't mandatory; simpler container model provisioning.
- **Retrieval quality** — reranking, query rewriting, a bigger eval set with
  published numbers.
- **More sources** — remote repos by URL, website crawling; hosted embedder
  backends.

For architecture and how the pieces fit together, see
[ARCHITECTURE.md](ARCHITECTURE.md).
