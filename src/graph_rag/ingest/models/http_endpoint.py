import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field, computed_field


class HttpEndpoint(BaseModel):
    """One HTTP route exposed by a Spring MVC / JAX-RS handler method.

    A handler with several mappings (`@GetMapping({"/a", "/b"})`, or
    `@RequestMapping(method = {GET, POST})`) yields one `HttpEndpoint` per
    (method, path) pair. `bindings` describes each bound handler parameter
    (`{"kind": "path"|"query"|"body"|"header"|"model"|"form", "name": ...,
    "param_type": ...}`); Neo4j can't hold a list of maps, so `bindings_json`
    is what the graph writer persists. An *inbound* endpoint feeds
    `(:HttpEndpoint)-[:HANDLED_BY]->(:CodeEntity)` and, after the project-model
    resolver, `(:HttpEndpoint)-[:IN_MODULE]->(:Module)`.

    An *outbound* endpoint (`outbound=True`) is a declarative HTTP client call —
    a `@FeignClient` / `@HttpExchange` interface method.
    `handler_qualified_name` is then the client method, wired
    `(:CodeEntity)-[:CALLS_SERVICE]->(:HttpEndpoint)`, and `target_service`
    names the callee (Feign `name` / `value` / `url`). `ServiceCallResolver`
    adds `(:HttpEndpoint outbound)-[:RESOLVES_TO]->(:HttpEndpoint inbound)` when
    a matching controller route is in the graph.
    """

    handler_qualified_name: str
    http_method: str  # GET / POST / … or "*" when no method is constrained
    path: str
    framework: str  # "spring-mvc" | "jax-rs" | "feign" | "spring-http-interface"
    produces: list[str] = Field(default_factory=list)
    consumes: list[str] = Field(default_factory=list)
    params: list[str] = Field(default_factory=list)  # @RequestMapping params= / headers=
    bindings: list[dict[str, Any]] = Field(default_factory=list)
    outbound: bool = False
    target_service: str | None = None
    embed_text: str
    embedding: list[float] | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bindings_json(self) -> str:
        return json.dumps(self.bindings, sort_keys=True, default=str)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        key = "\x00".join((self.handler_qualified_name, self.http_method, self.path))
        return hashlib.sha256(key.encode("utf-8")).hexdigest()
