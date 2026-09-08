import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field, computed_field


class Annotation(BaseModel):
    """A Java annotation as written on a code element.

    Captured for types, methods, constructors, fields, and parameters. Feeds
    `(CodeEntity)-[:ANNOTATED_WITH]->(:Annotation)` and is the foundation the
    Spring / JPA / Camel framework models build on.

    `attributes` holds the parsed element-value pairs
    (`@RequestMapping(path="/x", method=RequestMethod.GET)` →
    `{"path": "/x", "method": "RequestMethod.GET"}`). Neo4j cannot store a
    nested map as a property, so `attributes_json` is what the graph writer
    persists. `fqn` is resolved against the file's imports where possible and
    otherwise equals `name`.
    """

    owner_qualified_name: str
    # "type" | "method" | "constructor" | "field" | "param:<name>"
    target: str
    name: str
    fqn: str
    line: int
    attributes: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def attributes_json(self) -> str:
        return json.dumps(self.attributes, sort_keys=True, default=str)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        """Stable key: one annotation per (owner, target, fqn, source line)."""
        key = "\x00".join((self.owner_qualified_name, self.target, self.fqn, str(self.line)))
        return hashlib.sha256(key.encode("utf-8")).hexdigest()
