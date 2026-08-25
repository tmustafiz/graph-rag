from pydantic import BaseModel, Field


class CodeEntity(BaseModel):
    """A Python module, class, function, or method (`qualified_name` is the
    unique key in the graph, e.g. `graph_rag.ingest.chunker.Chunker.chunk`).
    """

    qualified_name: str
    name: str
    kind: str  # "module" | "class" | "function" | "method"
    embed_text: str
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    signature: str | None = None
    docstring: str | None = None
    parent_qualified_name: str | None = None
    calls: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None
