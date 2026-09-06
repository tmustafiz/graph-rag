import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..models import CodeEntity

if TYPE_CHECKING:
    from sqlglot import exp

logger = logging.getLogger(__name__)

# A procedural object always starts its `CREATE` at the start of a line.
_CREATE_RE = re.compile(
    r"^[ \t]*CREATE\s+(?:OR\s+REPLACE\s+)?(?:EDITIONABLE\s+|NONEDITIONABLE\s+)?"
    r"(PACKAGE\s+BODY|PACKAGE|PROCEDURE|FUNCTION|TRIGGER)\b",
    re.IGNORECASE | re.MULTILINE,
)
# Oracle's stand-alone statement terminator: a lone `/` on its own line.
_SLASH_TERMINATOR_RE = re.compile(r"^[ \t]*/[ \t]*$", re.MULTILINE)

_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LITERAL_RE = re.compile(r"'(?:''|[^'])*'")
_LEADING_COMMENT_RE = re.compile(
    r"(?:[ \t]*(?:--[^\n]*|/\*.*?\*/)[ \t]*\n)+", re.DOTALL | re.MULTILINE
)

_QUALIFIED_NAME = r'[A-Za-z_"\[][\w$".\]]*'
_WRITE_PATTERNS = (
    re.compile(rf"\bINSERT\s+INTO\s+({_QUALIFIED_NAME})", re.IGNORECASE),
    re.compile(rf"\bUPDATE\s+({_QUALIFIED_NAME})", re.IGNORECASE),
    re.compile(rf"\bDELETE\s+FROM\s+({_QUALIFIED_NAME})", re.IGNORECASE),
    re.compile(rf"\bMERGE\s+INTO\s+({_QUALIFIED_NAME})", re.IGNORECASE),
)
_READ_PATTERNS = (
    re.compile(rf"\bFROM\s+({_QUALIFIED_NAME})", re.IGNORECASE),
    re.compile(rf"\bJOIN\s+({_QUALIFIED_NAME})", re.IGNORECASE),
)
_EXPLICIT_CALL_RE = re.compile(
    rf"\b(?:CALL|PERFORM|EXEC|EXECUTE)\s+(?:FUNCTION\s+)?({_QUALIFIED_NAME})", re.IGNORECASE
)
_INVOCATION_RE = re.compile(rf"({_QUALIFIED_NAME})\s*\(")
_WHITESPACE_RE = re.compile(r"\s+")
# Tables that are not real tables.
_PSEUDO_TABLES = {"dual"}
# Keywords that `_INVOCATION_RE` catches before a `(` but that are never calls.
_NON_CALL_TOKENS = {
    "if",
    "while",
    "for",
    "loop",
    "case",
    "return",
    "values",
    "in",
    "and",
    "or",
    "not",
    "on",
    "when",
    "coalesce",
    "nvl",
    "count",
    "sum",
    "min",
    "max",
    "avg",
    "cast",
    "trim",
    "substr",
    "substring",
    "to_char",
    "to_date",
    "to_number",
    "nextval",
    "currval",
    "decode",
    "round",
    "trunc",
    "length",
    "upper",
    "lower",
    "concat",
    "exists",
}

_OBJECT_KINDS = {
    "PACKAGE": "package",
    "PACKAGE BODY": "package_body",
    "PROCEDURE": "procedure",
    "FUNCTION": "function",
    "TRIGGER": "trigger",
}


@dataclass
class _RoutineDraft:
    """A routine parsed from one `CREATE …` chunk, before `CALLS` resolution."""

    qualified_name: str
    name: str
    kind: str
    signature: str | None
    docstring: str | None
    parent_qualified_name: str | None
    body_text: str
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    trigger_table: str | None = None
    body_analyzed: bool = True


class ProceduralSqlExtractor:
    """Turns procedural SQL — Oracle PL/SQL, PostgreSQL PL/pgSQL, T-SQL — into
    `procedure` / `function` / `package` / `package_body` / `trigger`
    `CodeEntity` nodes with a best-effort `CALLS` graph and `READS` / `WRITES`
    (and, for triggers, `ON`) edges to `DbTable` nodes.

    `sqlglot` is tried per `CREATE` chunk; where it can't (Oracle packages and
    triggers, PL/pgSQL `$$…$$` bodies) the header and body fall back to a
    delimiter-scoped regex sweep. A routine whose body cannot be analyzed still
    yields its header entity, with a logged warning.
    """

    def extract(self, text: str, *, dialect: str | None, file_path: str) -> list[CodeEntity]:
        parsed: list[_RoutineDraft] = []
        for chunk, object_type in self._slice(text):
            parsed.extend(self._parse_chunk(chunk, object_type, dialect))

        if not parsed:
            return []

        # A packaged routine is declared in the spec and defined in the body —
        # fold the two into one entity (spec first, so it keeps the signature
        # and doc comment; the body contributes the code and its edges).
        drafts: list[_RoutineDraft] = []
        by_qualified_name: dict[str, _RoutineDraft] = {}
        for draft in parsed:
            existing = by_qualified_name.get(draft.qualified_name)
            if existing is None:
                by_qualified_name[draft.qualified_name] = draft
                drafts.append(draft)
            else:
                _merge_drafts(existing, draft)

        known_routines = self._known_routine_index(drafts)
        known_qualified = {
            draft.qualified_name for draft in drafts if draft.kind in ("procedure", "function")
        }
        packages_by_simple: dict[str, str] = {}
        for draft in drafts:
            if draft.kind == "package":
                packages_by_simple[draft.qualified_name.rsplit(".", 1)[-1]] = draft.qualified_name
            elif draft.kind == "package_body":
                spec_qn = draft.qualified_name.removesuffix("#body")
                packages_by_simple.setdefault(spec_qn.rsplit(".", 1)[-1], spec_qn)

        entities: list[CodeEntity] = []
        for draft in drafts:
            calls = self._resolve_calls(
                draft,
                known_routines=known_routines,
                known_qualified=known_qualified,
                packages_by_simple=packages_by_simple,
            )
            if draft.body_text and not draft.body_analyzed:
                logger.warning(
                    "procedural SQL: could not analyze the body of %s in %s "
                    "(header entity kept, no edges)",
                    draft.qualified_name,
                    file_path,
                )
            entities.append(
                CodeEntity(
                    qualified_name=draft.qualified_name,
                    name=draft.name,
                    kind=draft.kind,
                    language="sql",
                    embed_text=draft.docstring or self._synthesized_summary(draft),
                    file_path=file_path,
                    signature=draft.signature,
                    docstring=draft.docstring,
                    parent_qualified_name=draft.parent_qualified_name,
                    calls=calls,
                    reads=_unique(draft.reads),
                    writes=_unique(draft.writes),
                    trigger_table=draft.trigger_table,
                )
            )
        return entities

    # -- chunking -------------------------------------------------------

    @classmethod
    def _slice(cls, text: str) -> list[tuple[str, str]]:
        matches = list(_CREATE_RE.finditer(text))
        chunks: list[tuple[str, str]] = []
        for index, match in enumerate(matches):
            start = _extend_over_leading_comments(text, match.start())
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[start:end]
            terminator = _SLASH_TERMINATOR_RE.search(body)
            if terminator is not None:
                body = body[: terminator.start()]
            object_type = _WHITESPACE_RE.sub(" ", match.group(1).upper())
            chunks.append((body, object_type))
        return chunks

    # -- per-chunk parsing -----------------------------------------

    def _parse_chunk(
        self, chunk: str, object_type: str, dialect: str | None
    ) -> list[_RoutineDraft]:
        docstring = self._leading_comment(chunk)
        kind = _OBJECT_KINDS[object_type]

        if object_type in ("PROCEDURE", "FUNCTION"):
            drafts = self._parse_via_sqlglot(chunk, kind, docstring, dialect)
            if drafts is not None:
                return drafts

        if object_type == "PACKAGE":
            return self._parse_package_spec(chunk, docstring)
        if object_type == "PACKAGE BODY":
            return self._parse_package_body(chunk, docstring)
        if object_type == "TRIGGER":
            return [self._parse_trigger(chunk, docstring)]
        return [self._parse_standalone_routine(chunk, kind, docstring)]

    def _parse_via_sqlglot(
        self, chunk: str, kind: str, docstring: str | None, dialect: str | None
    ) -> list[_RoutineDraft] | None:
        try:
            import sqlglot
            from sqlglot import exp
        except ModuleNotFoundError:  # pragma: no cover - guarded by SqlParser
            return None
        try:
            statement = sqlglot.parse_one(chunk, read=dialect)
        except Exception:  # noqa: BLE001 - any sqlglot failure means fall back
            return None
        if not isinstance(statement, exp.Create):
            return None
        header = statement.this
        if not isinstance(header, (exp.StoredProcedure, exp.UserDefinedFunction)):
            return None

        qualified_name, name = _identity(header.this)
        signature = self._sqlglot_signature(statement, header, kind)
        body = statement.expression

        draft = _RoutineDraft(
            qualified_name=qualified_name,
            name=name,
            kind=kind,
            signature=signature,
            docstring=docstring,
            parent_qualified_name=None,
            body_text="",
        )
        if isinstance(body, exp.Block):
            self._read_write_from_block(body, draft)
        elif isinstance(body, exp.Heredoc):
            draft.body_text = body.name or ""
            self._sweep_body(draft.body_text, draft)
        elif body is not None:
            draft.body_text = body.sql(dialect=dialect)
            self._sweep_body(draft.body_text, draft)
        return [draft]

    @staticmethod
    def _sqlglot_signature(
        statement: "exp.Create", header: "exp.Expression", kind: str
    ) -> str | None:
        from sqlglot import exp

        params: list[str] = []
        for column_def in header.expressions:
            if not isinstance(column_def, exp.ColumnDef):
                continue
            part = column_def.this.name or column_def.this.sql()
            type_node = column_def.args.get("kind")
            if type_node is not None:
                part = f"{part} {type_node.sql()}"
            if column_def.args.get("output"):
                part = f"{part} OUTPUT"
            params.append(part)
        rendered = f"{kind} {header.this.name}({', '.join(params)})"
        returns = statement.find(exp.ReturnsProperty)
        if returns is not None and returns.this is not None:
            rendered = f"{rendered} RETURNS {returns.this.sql()}"
        return rendered

    def _read_write_from_block(self, block: "exp.Block", draft: _RoutineDraft) -> None:
        from sqlglot import exp

        for statement in block.expressions:
            if isinstance(statement, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
                target = _table_of(statement.this)
                if target:
                    draft.writes.append(target)
                for table in statement.find_all(exp.Table):
                    identity = _table_identity(table)
                    if identity and identity != target:
                        draft.reads.append(identity)
            elif isinstance(statement, exp.Execute):
                called = _table_identity(statement.this) if statement.this is not None else None
                if called:
                    draft.body_text += f"\nEXEC {called}"
            else:
                for table in statement.find_all(exp.Table):
                    identity = _table_identity(table)
                    if identity:
                        draft.reads.append(identity)

    # -- regex-path parsing ---------------------------------------

    def _parse_package_spec(self, chunk: str, docstring: str | None) -> list[_RoutineDraft]:
        match = re.search(
            rf"PACKAGE\s+({_QUALIFIED_NAME})\s+(?:AS|IS)\b(.*)", chunk, re.IGNORECASE | re.DOTALL
        )
        if match is None:
            return []
        package_qn = _normalize_name(match.group(1))
        body = match.group(2)
        drafts = [
            _RoutineDraft(
                qualified_name=package_qn,
                name=package_qn.rsplit(".", 1)[-1],
                kind="package",
                signature=f"package {package_qn}",
                docstring=docstring,
                parent_qualified_name=None,
                body_text="",
            )
        ]
        for routine_kind, routine_name, params, return_type in _iter_routine_declarations(body):
            drafts.append(
                _RoutineDraft(
                    qualified_name=f"{package_qn}.{routine_name}",
                    name=routine_name,
                    kind=routine_kind,
                    signature=_routine_signature(routine_kind, routine_name, params, return_type),
                    docstring=None,
                    parent_qualified_name=package_qn,
                    body_text="",
                )
            )
        return drafts

    def _parse_package_body(self, chunk: str, docstring: str | None) -> list[_RoutineDraft]:
        match = re.search(
            rf"PACKAGE\s+BODY\s+({_QUALIFIED_NAME})\s+(?:AS|IS)\b(.*)",
            chunk,
            re.IGNORECASE | re.DOTALL,
        )
        if match is None:
            return []
        package_qn = _normalize_name(match.group(1))
        inner = match.group(2)
        drafts = [
            _RoutineDraft(
                qualified_name=f"{package_qn}#body",
                name=package_qn.rsplit(".", 1)[-1],
                kind="package_body",
                signature=f"package body {package_qn}",
                docstring=docstring,
                parent_qualified_name=package_qn,
                body_text="",
            )
        ]
        for routine_kind, routine_name, params, return_type, body_text in _iter_routine_bodies(
            inner
        ):
            draft = _RoutineDraft(
                qualified_name=f"{package_qn}.{routine_name}",
                name=routine_name,
                kind=routine_kind,
                signature=_routine_signature(routine_kind, routine_name, params, return_type),
                docstring=None,
                parent_qualified_name=package_qn,
                body_text=body_text,
            )
            self._sweep_body(body_text, draft)
            drafts.append(draft)
        return drafts

    def _parse_standalone_routine(
        self, chunk: str, kind: str, docstring: str | None
    ) -> _RoutineDraft:
        match = re.search(
            rf"(?:PROCEDURE|FUNCTION)\s+({_QUALIFIED_NAME})\s*(\([^;]*?\))?\s*"
            rf"(?:RETURN\s+([\w$%.]+)\s*)?(?:IS|AS)\b(.*)",
            chunk,
            re.IGNORECASE | re.DOTALL,
        )
        if match is None:
            name = _first_name(chunk)
            return _RoutineDraft(
                qualified_name=name,
                name=name.rsplit(".", 1)[-1],
                kind=kind,
                signature=None,
                docstring=docstring,
                parent_qualified_name=None,
                body_text=chunk,
                body_analyzed=False,
            )
        qualified_name = _normalize_name(match.group(1))
        params = match.group(2) or ""
        return_type = match.group(3)
        body_text = match.group(4) or ""
        draft = _RoutineDraft(
            qualified_name=qualified_name,
            name=qualified_name.rsplit(".", 1)[-1],
            kind=kind,
            signature=_routine_signature(
                kind, qualified_name.rsplit(".", 1)[-1], params, return_type
            ),
            docstring=docstring,
            parent_qualified_name=None,
            body_text=body_text,
        )
        self._sweep_body(body_text, draft)
        return draft

    def _parse_trigger(self, chunk: str, docstring: str | None) -> _RoutineDraft:
        match = re.search(
            rf"TRIGGER\s+({_QUALIFIED_NAME}).*?\bON\s+({_QUALIFIED_NAME})(.*)",
            chunk,
            re.IGNORECASE | re.DOTALL,
        )
        if match is None:
            name = _first_name(chunk)
            return _RoutineDraft(
                qualified_name=name,
                name=name.rsplit(".", 1)[-1],
                kind="trigger",
                signature=None,
                docstring=docstring,
                parent_qualified_name=None,
                body_text=chunk,
                body_analyzed=False,
            )
        qualified_name = _normalize_name(match.group(1))
        trigger_table = _normalize_name(match.group(2))
        body_text = match.group(3) or ""
        draft = _RoutineDraft(
            qualified_name=qualified_name,
            name=qualified_name.rsplit(".", 1)[-1],
            kind="trigger",
            signature=f"trigger {qualified_name} ON {trigger_table}",
            docstring=docstring,
            parent_qualified_name=None,
            body_text=body_text,
            trigger_table=trigger_table,
        )
        self._sweep_body(body_text, draft)
        return draft

    # -- body sweep + call resolution ---------------------------

    def _sweep_body(self, body_text: str, draft: _RoutineDraft) -> None:
        if not body_text.strip():
            return
        clean = _strip_noise(body_text)
        writes = {
            _normalize_name(match.group(1))
            for pattern in _WRITE_PATTERNS
            for match in pattern.finditer(clean)
        }
        reads = {
            _normalize_name(match.group(1))
            for pattern in _READ_PATTERNS
            for match in pattern.finditer(clean)
        }
        draft.writes.extend(sorted(writes))
        draft.reads.extend(
            sorted(
                identity
                for identity in reads
                if identity not in writes and identity.lower() not in _PSEUDO_TABLES
            )
        )

    def _resolve_calls(
        self,
        draft: _RoutineDraft,
        *,
        known_routines: dict[str, str | None],
        known_qualified: set[str],
        packages_by_simple: dict[str, str],
    ) -> list[str]:
        if not draft.body_text.strip():
            return []
        clean = _strip_noise(draft.body_text)
        resolved: dict[str, None] = {}
        for pattern, explicit in ((_EXPLICIT_CALL_RE, True), (_INVOCATION_RE, False)):
            for match in pattern.finditer(clean):
                raw = match.group(1)
                if not explicit and raw.lower() in _NON_CALL_TOKENS:
                    continue
                target = self._match_call(
                    raw, known_routines, known_qualified, packages_by_simple, draft.qualified_name
                )
                if target:
                    resolved[target] = None
        return list(resolved)

    @staticmethod
    def _match_call(
        raw: str,
        known_routines: dict[str, str | None],
        known_qualified: set[str],
        packages_by_simple: dict[str, str],
        self_qualified_name: str,
    ) -> str | None:
        name = _normalize_name(raw)
        if name == self_qualified_name:
            return None
        if name in known_qualified:
            return name
        if "." in name:
            prefix, routine = name.rsplit(".", 1)
            package = packages_by_simple.get(prefix) or packages_by_simple.get(
                prefix.rsplit(".", 1)[-1]
            )
            candidate = f"{package}.{routine}" if package else None
            if candidate and candidate in known_qualified and candidate != self_qualified_name:
                return candidate
            return None
        target = known_routines.get(name)
        return target if target and target != self_qualified_name else None

    @staticmethod
    def _known_routine_index(drafts: list[_RoutineDraft]) -> dict[str, str | None]:
        """Simple routine name → qualified name, or `None` when ambiguous."""
        index: dict[str, str | None] = {}
        for draft in drafts:
            if draft.kind not in ("procedure", "function"):
                continue
            simple = draft.name
            if simple in index and index[simple] != draft.qualified_name:
                index[simple] = None
            else:
                index.setdefault(simple, draft.qualified_name)
        return index

    # -- misc helpers -------------------------------------------

    @staticmethod
    def _leading_comment(chunk: str) -> str | None:
        match = _LEADING_COMMENT_RE.match(chunk)
        if match is None:
            return None
        lines: list[str] = []
        for line in match.group(0).splitlines():
            stripped = line.strip()
            stripped = re.sub(r"^/\*+|\*+/$", "", stripped).strip()
            stripped = re.sub(r"^(?:--+|\*+)", "", stripped).strip()
            if stripped and "grag:dialect" not in stripped:
                lines.append(stripped)
        return " ".join(lines) or None

    @staticmethod
    def _synthesized_summary(draft: _RoutineDraft) -> str:
        summary = draft.signature or f"{draft.kind} {draft.qualified_name}"
        if draft.trigger_table:
            summary = f"{summary}. Fires on {draft.trigger_table}"
        if draft.writes:
            summary = f"{summary}. Writes: {', '.join(_unique(draft.writes))}"
        if draft.reads:
            summary = f"{summary}. Reads: {', '.join(_unique(draft.reads))}"
        return summary


# -- module-level helpers ----------------------------------------------


def _identity(table: "exp.Expression") -> tuple[str, str]:
    identity = _table_identity(table)
    return identity, identity.rsplit(".", 1)[-1]


def _table_of(node: "exp.Expression | None") -> str | None:
    from sqlglot import exp

    if node is None:
        return None
    if isinstance(node, exp.Schema):
        node = node.this
    return _table_identity(node)


def _table_identity(table: "exp.Expression") -> str:
    from sqlglot import exp

    if not isinstance(table, exp.Table):
        return _normalize_name(table.name or table.sql())
    parts = [part for part in (table.catalog, table.db, table.name) if part]
    return ".".join(parts) if parts else table.name


def _merge_drafts(base: _RoutineDraft, extra: _RoutineDraft) -> None:
    base.body_text = base.body_text or extra.body_text
    base.signature = base.signature or extra.signature
    base.docstring = base.docstring or extra.docstring
    base.trigger_table = base.trigger_table or extra.trigger_table
    base.reads.extend(extra.reads)
    base.writes.extend(extra.writes)
    base.body_analyzed = base.body_analyzed and extra.body_analyzed


def _extend_over_leading_comments(text: str, start: int) -> int:
    """Move `start` back over any run of comment-only lines directly above the
    `CREATE`, so the chunk carries its own leading doc comment.
    """
    line_start = text.rfind("\n", 0, start) + 1
    while line_start > 0:
        previous_line_start = text.rfind("\n", 0, line_start - 1) + 1
        candidate = text[previous_line_start : line_start - 1].strip()
        if candidate.startswith("--") or candidate.startswith("/*") or candidate.endswith("*/"):
            line_start = previous_line_start
        else:
            break
    return line_start


def _normalize_name(raw: str) -> str:
    segments = [segment.strip(' "[]`') for segment in raw.strip().split(".")]
    return ".".join(segment for segment in segments if segment)


def _strip_noise(sql: str) -> str:
    sql = _BLOCK_COMMENT_RE.sub(" ", sql)
    sql = _LINE_COMMENT_RE.sub(" ", sql)
    sql = _STRING_LITERAL_RE.sub("''", sql)
    return sql


def _unique(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        if value:
            seen.setdefault(value, None)
    return list(seen)


def _collapse(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _routine_signature(kind: str, name: str, params: str | None, return_type: str | None) -> str:
    rendered = f"{kind} {name}({_collapse((params or '').strip('()'))})"
    if return_type:
        rendered = f"{rendered} RETURN {return_type.strip()}"
    return rendered


def _first_name(chunk: str) -> str:
    match = re.search(rf"(?:PROCEDURE|FUNCTION|TRIGGER|PACKAGE)\s+({_QUALIFIED_NAME})", chunk, re.I)
    return _normalize_name(match.group(1)) if match else "unknown"


def _iter_routine_declarations(spec_body: str):
    """`(kind, name, params, return_type)` for each `PROCEDURE`/`FUNCTION`
    declaration in a package spec.
    """
    pattern = re.compile(
        r"\b(PROCEDURE|FUNCTION)\s+(\w+)\s*(\([^;]*?\))?\s*(?:RETURN\s+([\w$%.]+))?\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(spec_body):
        yield (
            match.group(1).lower(),
            match.group(2),
            match.group(3) or "",
            match.group(4),
        )


def _iter_routine_bodies(package_body: str):
    """`(kind, name, params, return_type, body_text)` for each routine defined
    in a package body — body spans from the routine header to the next routine
    header (or the package's trailing `END`).
    """
    header = re.compile(
        r"\b(PROCEDURE|FUNCTION)\s+(\w+)\s*(\([^;]*?\))?\s*"
        r"(?:RETURN\s+([\w$%.]+)\s*)?(?:IS|AS)\b",
        re.IGNORECASE | re.DOTALL,
    )
    matches = list(header.finditer(package_body))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(package_body)
        yield (
            match.group(1).lower(),
            match.group(2),
            match.group(3) or "",
            match.group(4),
            package_body[start:end],
        )
