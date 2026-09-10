from pydantic import BaseModel, Field

from .service_call_endpoint import ServiceCallEndpoint


class ServiceCallResult(BaseModel):
    """The in/out HTTP calls for one `CodeEntity.qualified_name`, from
    `get_service_calls` — a slice of the cross-service call graph.
    """

    qualified_name: str
    endpoints: list[ServiceCallEndpoint] = Field(default_factory=list)
