import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from ..models import ParsedDocument, Source, SqlStatement
from .sql_table_scanner import SqlTableScanner
from .xml_namespace import local_name as _local

logger = logging.getLogger(__name__)

_STATEMENT_TAGS = {"select", "insert", "update", "delete"}
_WS = re.compile(r"\s+")


class MyBatisMapperParser:
    """Parses a MyBatis mapper XML (`<mapper namespace="com.acme.OrderMapper">`)
    into `SqlStatement`s.

    Each `<select|insert|update|delete id="...">` becomes one statement: its SQL
    text is flattened — `<include refid="...">` expanded against the file's
    `<sql>` fragments, dynamic `<if>` / `<where>` / `<set>` / `<trim>` /
    `<foreach>` / `<choose>` tags unwrapped (all branches kept, best-effort) —
    and scanned for table names. `namespace` is the `@Mapper` interface FQN by
    MyBatis convention; `MyBatisResolver` binds each statement to the matching
    interface method after ingest.
    """

    @staticmethod
    def can_handle(path: Path) -> bool:
        if path.suffix.lower() != ".xml" or path.name == "pom.xml":
            return False
        try:
            root = ElementTree.fromstring(  # noqa: S314 - local project config, not untrusted
                path.read_bytes()
            )
        except (ElementTree.ParseError, OSError):
            return False
        return _local(root.tag) == "mapper" and root.get("namespace") is not None

    def parse(self, path: Path) -> ParsedDocument:
        raw = path.read_bytes()
        source = Source(
            path=str(path),
            source_type="mybatis-mapper",
            content_hash=hashlib.sha256(raw).hexdigest(),
            ingested_at=datetime.now(UTC),
        )
        try:
            root = ElementTree.fromstring(raw)  # noqa: S314 - local project config, not untrusted
        except ElementTree.ParseError as exc:
            logger.warning("could not parse %s as a MyBatis mapper: %s", path, exc)
            return ParsedDocument(source=source)

        namespace = root.get("namespace") or ""
        fragments = {
            element.get("id"): self._flatten(element, {})
            for element in root
            if _local(element.tag) == "sql" and element.get("id")
        }

        statements: list[SqlStatement] = []
        for element in root:
            kind = _local(element.tag)
            if kind not in _STATEMENT_TAGS or not element.get("id"):
                continue
            text = self._flatten(element, fragments)
            statements.append(
                SqlStatement(
                    mapper_qn=namespace,
                    statement_id=element.get("id", ""),
                    kind=kind,
                    text=text,
                    origin="mybatis-xml",
                    tables=SqlTableScanner.scan(text),
                    file_path=str(path),
                )
            )
        return ParsedDocument(source=source, sql_statements=statements)

    @classmethod
    def _flatten(cls, element: ElementTree.Element, fragments: dict[str | None, str]) -> str:
        parts: list[str] = [element.text or ""]
        for child in element:
            tag = _local(child.tag)
            if tag == "include":
                parts.append(fragments.get(child.get("refid"), ""))
            else:
                # <if>/<where>/<set>/<trim>/<foreach>/<choose>/<when>/<otherwise>
                # and anything else: unwrap and keep the body.
                parts.append(cls._flatten(child, fragments))
            parts.append(child.tail or "")
        return _WS.sub(" ", "".join(parts)).strip()
