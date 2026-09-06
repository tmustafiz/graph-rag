from pydantic import BaseModel, Field


class DbColumn(BaseModel):
    """One column of a `DbTable`.

    `qualified_name` is `schema.table.column` (dialect-qualified, matching the
    owning table) and is the unique key in the graph. `references` carries the
    `schema.table.column` of every column this one points at via a `FOREIGN
    KEY` / inline `REFERENCES` clause (inline or `ALTER TABLE … ADD
    CONSTRAINT`), each feeding a `REFERENCES` edge.
    """

    qualified_name: str
    name: str
    table_qualified_name: str
    data_type: str | None = None
    nullable: bool = True
    default: str | None = None
    primary_key: bool = False
    references: list[str] = Field(default_factory=list)
