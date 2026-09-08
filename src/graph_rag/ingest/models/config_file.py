from pydantic import BaseModel, Field


class ConfigFile(BaseModel):
    """A Spring / Java application-config file — `application*` or `bootstrap*`
    (`.yml` / `.yaml` / `.properties`), a `*.properties` / `*.yml` under a
    `resources` directory, or a Spring XML `<beans>` context.

    `path` (identical to the owning `Source.path`) is the unique key; `format`
    is `properties`, `yaml`, or `spring-xml`. Feeds
    `(:ConfigFile)-[:HAS_PROPERTY]->(:ConfigProperty)`.

    The four list fields are populated only for `format == "spring-xml"`:
    `<context:component-scan base-package>` roots, `<context:property-placeholder
    location>` paths, `<import resource>` paths, and the distinct non-`beans`
    namespace elements seen (`aop:config`, `tx:annotation-driven`, `util:list`, …
    — recorded now, modelled properly in a later milestone).
    """

    path: str
    format: str
    scan_packages: list[str] = Field(default_factory=list)
    placeholder_locations: list[str] = Field(default_factory=list)
    import_resources: list[str] = Field(default_factory=list)
    namespace_elements: list[str] = Field(default_factory=list)
