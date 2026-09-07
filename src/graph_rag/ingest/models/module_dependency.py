from pydantic import BaseModel


class ModuleDependency(BaseModel):
    """One dependency edge declared by a module's build file.

    Exactly one of `target_path` (a sibling `Module` directory — a Maven
    reactor `<module>` or a Gradle `project(':x')`) or `target_gav`
    (`group:artifact`, or `project:<name>` before the resolver maps it to a
    sibling) is set. `scope` is the Maven scope / Gradle configuration
    (`compile`, `test`, `provided`, `runtime`, `implementation`, `api`, …);
    `reactor` marks a Maven aggregator → child edge.
    """

    module_path: str
    target_path: str | None = None
    target_gav: str | None = None
    scope: str | None = None
