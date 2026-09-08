from pydantic import BaseModel


class EndpointResult(BaseModel):
    """One HTTP route from `get_endpoints` — a Spring MVC / JAX-RS
    `HttpEndpoint` with its handler and module.
    """

    http_method: str  # GET / POST / … / "*" / "EXCEPTION"
    path: str
    framework: str  # "spring-mvc" | "jax-rs"
    handler_qualified_name: str | None = None
    module: str | None = None  # owning `Module.artifact`, when the endpoint is in a module
    produces: list[str] = []
    consumes: list[str] = []
    summary: str | None = None  # `HttpEndpoint.embed_text` — natural-language description
