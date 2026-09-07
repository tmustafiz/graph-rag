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

## `sql-schema/`

Two hand-written Postgres migration files — a `sales` schema with regions,
customers, orders, and a reporting view. Ingest them to try the schema graph:

```bash
uv run grag-mcp ingest examples/sql-schema   # needs the [sql] extra
```

Then, from an MCP client:

- `get_neighbors("sales.orders")` → `HAS_COLUMN` to its columns, `HAS_INDEX`
  to `idx_orders_customer`, `REFERENCES` out to `sales.customer` /
  `sales.region`
- `get_neighbors("sales.orders.customer_id")` → `REFERENCES` →
  `sales.customer.id`
- `get_neighbors("sales.v_expedited_orders")` → `DEPENDS_ON` →
  `sales.orders`, `sales.customer`
- `002_reporting.sql` adds a foreign key to `sales.orders` with an
  `ALTER TABLE` even though the table is created in `001_core.sql` — the
  `REFERENCES` edge still lands.

`procedures/order_ops.sql` is an Oracle PL/SQL package + trigger over the same
tables — ingest the whole directory (`examples/sql-schema`) and try:

- `get_neighbors("sales.order_ops.submit")` → `CALLS` → `sales.order_ops.publish`,
  `WRITES` → `sales.orders`
- `get_neighbors("sales.orders")` → incoming `WRITES` from the package
  routines, `READS` from `sales.order_ops.open_count`
- `get_neighbors("sales.trg_order_line_audit")` → `ON` → `sales.order_line`,
  `WRITES` → `sales.orders`

## `stylesheets/`

An SCSS entrypoint (`app.scss`) and the `_tokens.scss` partial it pulls in —
for the `.css` / `.scss` / `.sass` / `.less` parser and the plain `search`
tool.

```bash
uv run grag-mcp ingest examples/stylesheets   # needs the [css] extra
```

Then, from an MCP client:

- `search("button hover background")` → the `.btn:hover` rule chunk
- `search("--accent custom property")` → the `--accent` token chunk from
  `_tokens.scss`
- `get_neighbors("<abs path>/examples/stylesheets/app.scss")` → `IMPORTS` →
  `_tokens.scss` (from `@forward` / `@import`)

## `agent-memory/`

Copy-paste templates for wiring a coding agent in a **different** project up
to graph-rag's `remember`/`recall`/`forget` tools as its own persistent
working memory, for Claude Code and VS Code Copilot Chat — an always-on
instructions snippet, a skill/prompt file, and a `SessionStart` hook that
recalls relevant memories automatically. See
[`agent-memory/README.md`](agent-memory/README.md).
