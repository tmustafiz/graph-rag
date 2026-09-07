import hashlib

from pydantic import BaseModel, Field, computed_field


class SpringXmlBean(BaseModel):
    """One `<bean>` (or inner bean) definition parsed from a Spring XML context
    file (`applicationContext.xml`, `*-context.xml`, `WEB-INF/*-servlet.xml`, …).

    This is the raw, per-file intermediate representation. The post-ingest
    `SpringXmlResolver` pass turns it (and its `ref` strings) into the unified
    `(:Bean {defined_in:'xml'})` graph shared with the annotation-wired beans.

    `bean_id` is the `id` attribute, or the first `name` token, or a generated
    `<simple-class>#<n>` for an anonymous inner bean. `property_names` and
    `property_refs` are parallel lists (one `<property name ref>` per index).
    `value_placeholder_keys` holds the `${key}` keys seen in `value=` attributes,
    best-effort linked to `ConfigProperty`s by the resolver. `profile` is the
    enclosing `<beans profile="...">` if the bean sits in a profile-scoped block.
    """

    source_path: str
    bean_id: str
    bean_name: str
    class_name: str | None = None
    profile: str | None = None
    scope: str | None = None
    parent: str | None = None
    factory_bean: str | None = None
    factory_method: str | None = None
    primary: bool = False
    abstract: bool = False
    lazy_init: bool = False
    aliases: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    constructor_arg_refs: list[str] = Field(default_factory=list)
    property_names: list[str] = Field(default_factory=list)
    property_refs: list[str] = Field(default_factory=list)
    value_placeholder_keys: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        parts = (self.source_path, self.bean_id)
        return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()
