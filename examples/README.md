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
