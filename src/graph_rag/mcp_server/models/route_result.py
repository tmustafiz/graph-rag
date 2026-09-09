from pydantic import BaseModel, Field


class RouteResult(BaseModel):
    """One Apache Camel route from `get_routes` — its `from` endpoint, the
    endpoints it sends to, an ordered step summary, and the `CodeEntity`s its
    `process` / `bean` steps invoke.
    """

    route_id: str
    from_uri: str
    to_uris: list[str] = Field(default_factory=list)  # every TO target, conditional or not
    # the subset of `to_uris` reached only through a `choice` branch (best-effort;
    # see `JavaParser._camel_route_from_chain`) — never removed from `to_uris`
    conditional_to_uris: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)  # "kind(uri?)" per step, in order
    invokes: list[str] = Field(default_factory=list)  # CodeEntity qualified_names
    on_exception: list[str] = Field(default_factory=list)
    module: str | None = None
    source_path: str | None = None
