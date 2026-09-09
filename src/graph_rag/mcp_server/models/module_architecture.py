from pydantic import BaseModel, Field


class ModuleArchitecture(BaseModel):
    """The framework-relevant contents of one Maven/Gradle module (or the
    catch-all `unassigned` bucket for nodes not in any module).
    """

    module: str  # Module.artifact, or "unassigned"
    beans: list[str] = Field(default_factory=list)  # "name [stereotype]"
    endpoints: list[str] = Field(default_factory=list)  # "METHOD /path"
    routes: list[str] = Field(default_factory=list)  # "route_id: from_uri"
    listeners: list[str] = Field(default_factory=list)  # "qualified_name <- event/topic"
    scheduled_jobs: list[str] = Field(default_factory=list)  # "qualified_name (cron)"
