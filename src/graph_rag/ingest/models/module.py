from pydantic import BaseModel, Field


class Module(BaseModel):
    """A Maven or Gradle build module.

    `path` — the module directory, absolute — is the unique key in the graph.
    `packages` are the base Java package prefixes the module owns (its
    `groupId` / Gradle `group`, augmented by the resolver with the packages of
    the `.java` files found under it); the resolver uses them to mark a
    `CodeEntity` `IMPORTS` target as internal vs external. `source_roots` are
    absolute directories (`src/main/java`, `src/test/java`, and
    `target/generated-sources` / `build/generated` when they exist on disk)
    that belong to this module.
    """

    path: str
    artifact: str
    group: str | None = None
    version: str | None = None
    build_tool: str  # "maven" | "gradle"
    packages: list[str] = Field(default_factory=list)
    source_roots: list[str] = Field(default_factory=list)
