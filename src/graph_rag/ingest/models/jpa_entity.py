from pydantic import BaseModel, Field


class JpaEntity(BaseModel):
    """A JPA persistent type — `@Entity` / `@Embeddable` / `@MappedSuperclass`.

    `qualified_name` is the owning `CodeEntity`. `table` is the mapped table
    name (`@Table(name=…)` when given, else the simple class name — Hibernate's
    default). The `association_*` lists are parallel (one JPA relationship per
    index): `association_fields[i]` on this entity is a `association_kinds[i]`
    (`one-to-many` / `many-to-one` / `many-to-many` / `one-to-one`) to
    `association_targets[i]` (the field's element type, best-effort), with
    `association_mapped_by[i]` the inverse-side `mappedBy` (empty when owning).

    Consumed by the `SpringDataResolver` pass, which tags the `CodeEntity`
    `:JpaEntity` and wires `PERSISTS_AS` / `RELATES_TO`.
    """

    qualified_name: str
    simple_name: str
    kind: str  # "entity" | "embeddable" | "mapped-superclass"
    table: str | None = None
    id_fields: list[str] = Field(default_factory=list)
    association_fields: list[str] = Field(default_factory=list)
    association_targets: list[str] = Field(default_factory=list)
    association_kinds: list[str] = Field(default_factory=list)
    association_mapped_by: list[str] = Field(default_factory=list)
