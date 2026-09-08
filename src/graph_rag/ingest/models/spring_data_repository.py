from pydantic import BaseModel, Field


class SpringDataRepository(BaseModel):
    """A Spring Data repository interface — one extending `Repository` /
    `CrudRepository` / `JpaRepository` / … (or carrying `@RepositoryDefinition`).

    `qualified_name` is the owning `CodeEntity`. `entity_type` / `id_type` are
    the managed domain type and its id, taken from the base interface's type
    parameters (`JpaRepository<Order, Long>`) or `@RepositoryDefinition`, kept as
    written (simple or FQN) for the resolver to bind. `base` is the recognised
    Spring Data super-interface's simple name; `reactive` flags the reactive
    bases.

    The `method_*` lists are parallel (one declared method per index):
    `method_query_kinds[i]` ∈ `derived` / `jpql` / `native` / `modifying` /
    `procedure` / `inherited`; `method_query_texts[i]` is the `@Query` / stored
    procedure string (empty when none); `method_properties[i]` is the
    comma-joined property paths parsed from a derived-query method name (empty
    otherwise).

    Consumed by the `SpringDataResolver` pass, which tags the `CodeEntity`
    `:Repository`, tags each method `CodeEntity` with `query_kind` / `query_text`
    / `query_properties`, and wires `(:Repository)-[:MANAGES]->(:JpaEntity)`.
    """

    qualified_name: str
    simple_name: str
    base: str
    entity_type: str | None = None
    id_type: str | None = None
    reactive: bool = False
    method_qns: list[str] = Field(default_factory=list)
    method_names: list[str] = Field(default_factory=list)
    method_query_kinds: list[str] = Field(default_factory=list)
    method_query_texts: list[str] = Field(default_factory=list)
    method_properties: list[str] = Field(default_factory=list)
