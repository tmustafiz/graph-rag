from typing import Any

from ..models import Annotation, CodeEntity, SqlStatement
from .sql_table_scanner import SqlTableScanner

# `@Select` / `@Insert` / … annotation simple name → statement kind.
_ANNOTATION_KINDS = {
    "Select": "select",
    "Insert": "insert",
    "Update": "update",
    "Delete": "delete",
}


class MyBatisExtractor:
    """Derives `SqlStatement`s from `@Select` / `@Insert` / `@Update` /
    `@Delete` annotations on `@Mapper` interface methods in a parsed `.java`
    file — the SQL is the annotation `value` (string or `{...}` array joined).

    Unlike the XML form, the method is right here, so `method_qn` is set and
    the `EXECUTES` edge needs no resolver pass.
    """

    @classmethod
    def extract(
        cls, entities: list[CodeEntity], annotations: list[Annotation]
    ) -> list[SqlStatement]:
        methods = {entity.qualified_name: entity for entity in entities if entity.kind == "method"}

        statements: list[SqlStatement] = []
        for annotation in annotations:
            kind = _ANNOTATION_KINDS.get(annotation.name)
            if kind is None or annotation.target != "method":
                continue
            method = methods.get(annotation.owner_qualified_name)
            if method is None or method.parent_qualified_name is None:
                continue
            text = cls._sql_text(annotation.attributes.get("value"))
            if not text:
                continue
            statements.append(
                SqlStatement(
                    mapper_qn=method.parent_qualified_name,
                    statement_id=method.name,
                    kind=kind,
                    text=text,
                    origin="mybatis-annotation",
                    method_qn=method.qualified_name,
                    tables=SqlTableScanner.scan(text),
                    file_path=method.file_path,
                )
            )
        return statements

    @staticmethod
    def _sql_text(raw: Any) -> str:
        if raw is None:
            return ""
        items = raw if isinstance(raw, (list, tuple)) else [raw]
        return " ".join(str(item).strip() for item in items if str(item).strip())
