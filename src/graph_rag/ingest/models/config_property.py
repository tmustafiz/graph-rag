import hashlib

from pydantic import BaseModel, Field, computed_field


class ConfigProperty(BaseModel):
    """One resolved key/value from a `ConfigFile`.

    YAML nesting is flattened to a dotted key and list items get an `[index]`
    suffix, matching Spring's relaxed binding. `profile` is the Spring profile
    the value applies under (`None` = the default document / no profile).
    `references` holds the `id`s of other `ConfigProperty`s this value points at
    through a `${placeholder}` (best-effort, resolved within the same file).
    Values are always kept as strings.
    """

    file_path: str
    key: str
    value: str
    profile: str | None = None
    origin_line: int
    references: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        parts = (self.file_path, self.profile or "", self.key, str(self.origin_line))
        return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()
