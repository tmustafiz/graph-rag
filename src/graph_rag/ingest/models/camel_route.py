import hashlib
from typing import Any

from pydantic import BaseModel, Field, computed_field


class CamelRoute(BaseModel):
    """One Apache Camel route from a `RouteBuilder.configure()` Java DSL chain —
    `from(uri).routeId(id).<step>.<step>...`.

    The fluent builder chain is exactly what the generic `CALLS` resolver skips
    (every step is a call on the previous call's result), so `JavaParser`
    resolves it here. `steps` is the ordered step list, each
    `{index, kind, uri?, ref?, predicate?}` — materialized by the graph writer
    into `(:Route)-[:STEP {index, kind, predicate?}]->(:CamelStep)` with
    `(:CamelStep)-[:INVOKES]->(:CodeEntity)` for `process` / `bean` steps
    (wired by `CamelResolver`). `to_uris` also feed
    `(:Route)-[:TO]->(:CamelEndpoint)`; `on_exception` are the exception FQNs
    from the builder's `onException(...)`.

    `route_id` is the explicit `.routeId(...)` / `.id(...)` or, absent that,
    `<file-stem>:<ordinal>`. `id` (the graph key) is a hash of the source path +
    ordinal, stable across a re-parse whether or not a `routeId` is set.
    """

    route_id: str
    from_uri: str
    source_path: str
    ordinal: int
    to_uris: list[str] = Field(default_factory=list)
    on_exception: list[str] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    embed_text: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        key = "\x00".join((self.source_path, str(self.ordinal)))
        return hashlib.sha256(key.encode("utf-8")).hexdigest()
