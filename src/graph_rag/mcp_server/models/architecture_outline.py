from pydantic import BaseModel, Field

from .module_architecture import ModuleArchitecture


class ArchitectureOutline(BaseModel):
    """`get_architecture_outline` — beans, HTTP endpoints, Camel routes,
    message listeners, and scheduled jobs, grouped by module.
    """

    modules: list[ModuleArchitecture] = Field(default_factory=list)
