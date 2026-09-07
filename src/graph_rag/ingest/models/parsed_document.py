from pydantic import BaseModel, Field

from .annotation import Annotation
from .chunk import Chunk
from .code_entity import CodeEntity
from .db_column import DbColumn
from .db_index import DbIndex
from .db_reference import DbReference
from .db_table import DbTable
from .db_view import DbView
from .policy_rule import PolicyRule
from .section import Section
from .source import Source


class ParsedDocument(BaseModel):
    """A parser's output: one `Source`, plus whichever shape fits its source
    type — a `Section`/`Chunk` tree (prose sources like PDF/Markdown), a
    `CodeEntity` list (source code), a `PolicyRule` list (Checkov YAML), or a
    `DbTable`/`DbColumn`/`DbView`/`DbIndex` set (SQL DDL).
    """

    source: Source
    sections: list[Section] = Field(default_factory=list)
    chunks: list[Chunk] = Field(default_factory=list)
    code_entities: list[CodeEntity] = Field(default_factory=list)
    # Structured annotations on the code entities above, each carrying its
    # `owner_qualified_name`; feeds `(CodeEntity)-[:ANNOTATED_WITH]->(:Annotation)`.
    annotations: list[Annotation] = Field(default_factory=list)
    policy_rules: list[PolicyRule] = Field(default_factory=list)
    db_tables: list[DbTable] = Field(default_factory=list)
    db_columns: list[DbColumn] = Field(default_factory=list)
    db_views: list[DbView] = Field(default_factory=list)
    db_indexes: list[DbIndex] = Field(default_factory=list)
    db_references: list[DbReference] = Field(default_factory=list)
    # Paths of other `Source` files this one pulls in — stylesheet `@import` /
    # `@use` / `@forward`; feeds `(Source)-[:IMPORTS]->(Source)` edges.
    source_imports: list[str] = Field(default_factory=list)
