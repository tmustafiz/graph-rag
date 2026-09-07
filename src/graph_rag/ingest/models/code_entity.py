from pydantic import BaseModel, Field


class CodeEntity(BaseModel):
    """A source-code unit — module/file, class, function, method, and whatever
    else a language parser emits (interface, enum, package, procedure, …).

    `qualified_name` is the single unique key in the graph across every
    language, so each parser must namespace it well enough that two languages
    can't collide — Python uses dotted module ancestry
    (`graph_rag.ingest.chunker.Chunker.chunk`); a language with no global
    module namespace should prefix with its repo-relative path or a language
    tag. `kind` is a free-form, per-language vocabulary (Python:
    `module` | `class` | `function` | `method`).
    """

    qualified_name: str
    name: str
    kind: str
    # Source language, set by the parser. Defaults to "python" — the only
    # language with a parser today — so existing callers stay valid.
    language: str = "python"
    embed_text: str
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    signature: str | None = None
    docstring: str | None = None
    parent_qualified_name: str | None = None
    # `True` for a member a parser materialised that has no source span of its
    # own — a compile-time-synthesized Lombok accessor / constructor / `log`
    # field. `origin` names what synthesized it (e.g. `"lombok"`).
    synthetic: bool = False
    origin: str | None = None
    calls: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    # Other `CodeEntity` qualified names this one renders — set only by the
    # React enrichment pass for `component` entities; feeds `RENDERS` edges.
    renders: list[str] = Field(default_factory=list)
    # `DbTable` qualified names a SQL routine (`procedure` / `function` /
    # `trigger`) reads from / writes to — set only by the procedural-SQL
    # parser; feed `READS` / `WRITES` edges. `trigger_table` is the table a
    # `trigger` fires on, feeding an `ON` edge.
    reads: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    trigger_table: str | None = None
    embedding: list[float] | None = None
