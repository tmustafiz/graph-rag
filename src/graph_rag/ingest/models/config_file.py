from pydantic import BaseModel


class ConfigFile(BaseModel):
    """A Spring / Java application-config file — `application*` or `bootstrap*`
    (`.yml` / `.yaml` / `.properties`), or a `*.properties` / `*.yml` under a
    `resources` directory.

    `path` (identical to the owning `Source.path`) is the unique key; `format`
    is `properties` or `yaml`. Feeds `(:ConfigFile)-[:HAS_PROPERTY]->(:ConfigProperty)`.
    """

    path: str
    format: str
