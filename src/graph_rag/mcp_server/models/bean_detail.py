from pydantic import BaseModel, Field

from .bean_edge import BeanEdge


class BeanDetail(BaseModel):
    """The Spring bean for a `CodeEntity` / bean id, with its wiring — what it
    injects, what injects it, what produces it (an `@Bean` method's
    `@Configuration`), and the `ConfigProperty` keys it binds (`@Value` /
    `@ConfigurationProperties` / XML `${…}`).
    """

    bean_id: str
    name: str
    stereotype: str | None = None
    scope: str | None = None
    primary: bool = False
    bean_type: str | None = None
    # "xml" for a `<beans>`-context bean, else null (annotation-wired).
    defined_in: str | None = None
    injects: list[BeanEdge] = Field(default_factory=list)
    injected_by: list[BeanEdge] = Field(default_factory=list)
    produces: list[BeanEdge] = Field(default_factory=list)
    produced_by: list[BeanEdge] = Field(default_factory=list)
    binds: list[str] = Field(default_factory=list)
    # JSON list, present when the resolver could not bind an injection point.
    unresolved_injections: str | None = None
