import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field, computed_field


class BehaviorMarker(BaseModel):
    """A cross-cutting behavioral annotation recorded against a `CodeEntity`.

    Enterprise reviewers ask "what runs in a transaction", "what is scheduled",
    "what is behind method security". Those behaviors are declared with
    annotations (`@Transactional`, `@Scheduled`, `@Async`, `@Retryable`,
    `@Cacheable`, `@PreAuthorize`, …) rather than expressed as source calls, so
    they are invisible in the `CALLS` graph. This model captures one such
    marker; the graph writer projects it as
    `(CodeEntity)-[:HAS_BEHAVIOR {marker}]->(:BehaviorMarker)` and copies the
    marker slug onto `CodeEntity.behaviors` for cheap "all scheduled jobs"
    scans.

    `marker` is a normalized slug (`transactional`, `async`, `scheduled`,
    `retryable`, `cacheable`, `cache_put`, `cache_evict`, `pre_authorize`,
    `post_authorize`, `secured`, `roles_allowed`). `attributes` is the parsed
    element-value map of the annotation; Neo4j cannot store a nested map, so
    `attributes_json` is what the writer persists.
    """

    owner_qualified_name: str
    # "type" when the annotation sits on the class (Spring applies a class-level
    # `@Transactional` to every public method) or "method" for a method-level one.
    target: str
    marker: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    line: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def attributes_json(self) -> str:
        return json.dumps(self.attributes, sort_keys=True, default=str)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        """Stable key: one marker per (owner, target, marker slug, source line)."""
        key = "\x00".join((self.owner_qualified_name, self.target, self.marker, str(self.line)))
        return hashlib.sha256(key.encode("utf-8")).hexdigest()
