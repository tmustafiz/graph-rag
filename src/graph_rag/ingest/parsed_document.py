from pydantic import BaseModel

from graph_rag.ingest.chunk import Chunk
from graph_rag.ingest.section import Section
from graph_rag.ingest.source import Source


class ParsedDocument(BaseModel):
    """A parser's output: one `Source`, its `Section` tree, and their `Chunk`s."""

    source: Source
    sections: list[Section]
    chunks: list[Chunk]
