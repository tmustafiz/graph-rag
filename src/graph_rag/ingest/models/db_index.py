from pydantic import BaseModel, Field


class DbIndex(BaseModel):
    """A `CREATE INDEX` (`DbIndex.qualified_name` —
    `schema.table.index_name` — is the unique key in the graph).

    `columns` are the covered column names in index order. `HAS_INDEX` links
    the owning `DbTable` to this node.
    """

    qualified_name: str
    name: str
    table_qualified_name: str
    columns: list[str] = Field(default_factory=list)
    unique: bool = False
