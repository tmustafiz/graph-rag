from pydantic import BaseModel, Field


class DbTable(BaseModel):
    """A `CREATE TABLE` (`DbTable.qualified_name` — `schema.table`,
    dialect-qualified — is the unique key in the graph).

    `references` holds the `schema.table` of every table this one points at
    through a `FOREIGN KEY` (per-column targets live on `DbColumn.references`);
    it feeds the table-level `REFERENCES` edge. `embed_text` is a rendered
    `CREATE TABLE …` summary so the node is searchable.
    """

    qualified_name: str
    name: str
    schema_name: str | None = None
    file_path: str | None = None
    references: list[str] = Field(default_factory=list)
    embed_text: str
    embedding: list[float] | None = None
