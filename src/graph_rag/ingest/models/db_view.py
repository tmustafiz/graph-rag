from pydantic import BaseModel, Field


class DbView(BaseModel):
    """A `CREATE VIEW` / `CREATE MATERIALIZED VIEW` (`DbView.qualified_name` —
    `schema.view`, dialect-qualified — is the unique key in the graph).

    `depends_on` holds the `schema.name` of every table or view referenced in
    the view's `SELECT`, feeding `DEPENDS_ON` edges. `embed_text` is a rendered
    summary so the node is searchable.
    """

    qualified_name: str
    name: str
    schema_name: str | None = None
    materialized: bool = False
    file_path: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    embed_text: str
    embedding: list[float] | None = None
