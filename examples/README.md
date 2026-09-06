# examples/

Small, original sample inputs for trying graph-rag's features. graph-rag does
**not** ship a document corpus — you point `grag-mcp ingest` at your own files
(see the "Bring your own documents" section of the top-level README). This
folder only holds enough to exercise the tooling on a fresh clone.

## `checkov-policies/`

Three hand-written custom Checkov policy definitions (`CKV2_CUSTOM_1..3`) — not
copied from Checkov's catalog. Ingest them to try `find_policies_for` and
`search_policies`:

```bash
uv run grag-mcp ingest examples/checkov-policies
```

Then, from an MCP client:

- `find_policies_for("aws_db_instance")` → the RDS encryption + public-access rules
- `search_policies("is my S3 bucket versioned")` → the S3 versioning rule

## `java/` and `js/`

Tiny source trees — a Java package and a TypeScript project — for exercising
the code parsers and `search_code`:

```bash
uv run grag-mcp ingest examples/java   # needs the [java] extra
uv run grag-mcp ingest examples/js     # needs the [js] extra
```

Then, from an MCP client:

- `search_code("where are expedited orders routed")` → `OrderService.submit`
  in both trees
- `get_neighbors("src.orders.order-service.OrderService.submit")` → its
  `CALLS` out to `publish` / `accepts`
- `js/` also has a `.tsx` pair (`src/ui/order-badge.tsx`) — `OrderBadgeList`
  is retagged `kind="component"` and `RENDERS` `OrderBadge`

## `agent-memory/`

Copy-paste templates for wiring a coding agent in a **different** project up
to graph-rag's `remember`/`recall`/`forget` tools as its own persistent
working memory, for Claude Code and VS Code Copilot Chat — an always-on
instructions snippet, a skill/prompt file, and a `SessionStart` hook that
recalls relevant memories automatically. See
[`agent-memory/README.md`](agent-memory/README.md).
