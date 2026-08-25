from pydantic import BaseModel, Field

from .chunk import Chunk
from .code_entity import CodeEntity
from .policy_rule import PolicyRule
from .section import Section
from .source import Source


class ParsedDocument(BaseModel):
    """A parser's output: one `Source`, plus whichever shape fits its source
    type — a `Section`/`Chunk` tree (prose sources like PDF/Markdown), a
    `CodeEntity` list (source code), or a `PolicyRule` list (Checkov YAML).
    """

    source: Source
    sections: list[Section] = Field(default_factory=list)
    chunks: list[Chunk] = Field(default_factory=list)
    code_entities: list[CodeEntity] = Field(default_factory=list)
    policy_rules: list[PolicyRule] = Field(default_factory=list)
