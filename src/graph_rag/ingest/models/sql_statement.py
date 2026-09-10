import hashlib

from pydantic import BaseModel, Field, computed_field


class SqlStatement(BaseModel):
    """A MyBatis mapper statement — the SQL a `@Mapper` interface method runs.

    Comes from a mapper XML (`<select|insert|update|delete id=...>` under
    `<mapper namespace=...>`, with `<include>` fragments expanded and dynamic
    `<if>`/`<where>`/`<foreach>` tags flattened best-effort) or an
    `@Select` / `@Insert` / `@Update` / `@Delete` annotation on the method.

    `mapper_qn` is the XML `namespace` (= the interface FQN by MyBatis
    convention) or, for the annotation form, the interface FQN directly.
    `method_qn` is set for the annotation form (same file); for XML it is
    filled by `MyBatisResolver` matching `(mapper_qn, statement_id)` to an
    ingested method. Feeds `(:CodeEntity)-[:EXECUTES]->(:SqlStatement)` and
    `(:SqlStatement)-[:ACCESSES {mode}]->(:DbTable)` (a stub `DbTable {name}`
    when the schema was not separately ingested).
    """

    mapper_qn: str
    statement_id: str
    kind: str  # "select" | "insert" | "update" | "delete"
    text: str
    origin: str  # "mybatis-xml" | "mybatis-annotation"
    method_qn: str | None = None
    # [{"name": "<table>", "mode": "read" | "write"}]
    tables: list[dict[str, str]] = Field(default_factory=list)
    file_path: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        key = "\x00".join((self.mapper_qn, self.statement_id, self.kind, self.origin))
        return hashlib.sha256(key.encode("utf-8")).hexdigest()
