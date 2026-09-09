from pydantic import BaseModel


class ServiceCallEndpoint(BaseModel):
    """One HTTP edge touching a `CodeEntity` — inbound (it handles the route) or
    outbound (it declares the call, via `@FeignClient` / `@HttpExchange`).
    """

    direction: str  # "inbound" | "outbound"
    http_method: str
    path: str
    target_service: str | None = None  # outbound: the callee service (Feign name / url)
    resolves_to_handler: str | None = None  # outbound: the ingested controller method it hits
