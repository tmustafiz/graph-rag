import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ...settings import settings
from ..models import DbColumn, DbIndex, DbReference, DbTable, DbView, ParsedDocument, Source

if TYPE_CHECKING:
    from sqlglot import exp

logger = logging.getLogger(__name__)

_SUFFIX = ".sql"
# Per-file override, e.g. `-- grag:dialect=postgres`.
_DIALECT_MARKER_RE = re.compile(r"--\s*grag:dialect\s*=\s*([A-Za-z_]+)")
# Dialect labels that mean "sqlglot's dialect-agnostic parser" (its default).
_GENERIC_DIALECTS = {"", "ansi", "generic", "none", "standard"}
_DEFINITION_LIMIT = 400


class SqlParser:
    """Parses a `.sql` DDL file into a database-schema graph via `sqlglot`.

    Emits `DbTable` / `DbColumn` / `DbView` / `DbIndex` nodes (not `CodeEntity`)
    plus `HAS_COLUMN`, `REFERENCES` (column- and table-level, from inline and
    `ALTER TABLE … ADD CONSTRAINT` foreign keys), `DEPENDS_ON` (view → the
    tables/views in its `SELECT`) and `HAS_INDEX` edges. Query text and DML are
    ignored — this is a schema extractor.

    Dialect is `settings.sql_dialect` (env `GRAG_SQL_DIALECT`), overridable
    per file with a `-- grag:dialect=<name>` marker comment; an unknown
    dialect, or a file `sqlglot` cannot parse, logs a warning and yields a
    `Source` with no schema nodes rather than raising.
    """

    @staticmethod
    def can_handle(path: Path) -> bool:
        return path.suffix.lower() == _SUFFIX

    def parse(self, path: Path) -> ParsedDocument:
        try:
            import sqlglot
            from sqlglot.errors import SqlglotError
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Parsing SQL needs the optional 'sql' extra. Install it with "
                "`pip install 'grag-mcp[sql]'` (or `uv sync --extra sql`)."
            ) from exc

        raw = path.read_bytes()
        text = raw.decode("utf-8", "replace")
        source = Source(
            path=str(path),
            source_type="sql",
            content_hash=hashlib.sha256(raw).hexdigest(),
            ingested_at=datetime.now(UTC),
        )

        dialect = self._resolve_dialect(text)
        try:
            statements = sqlglot.parse(text, read=dialect)
        except SqlglotError as exc:
            logger.warning("sqlglot could not parse %s (dialect=%s): %s", path, dialect, exc)
            return ParsedDocument(source=source)

        builder = _SchemaBuilder(file_path=str(path), dialect=dialect)
        for statement in statements:
            if statement is not None:
                builder.consume(statement)

        return ParsedDocument(
            source=source,
            db_tables=builder.tables,
            db_columns=builder.columns,
            db_views=builder.views,
            db_indexes=builder.indexes,
            db_references=builder.references,
        )

    @staticmethod
    def _resolve_dialect(text: str) -> str | None:
        import sqlglot

        marker = _DIALECT_MARKER_RE.search(text)
        chosen = (marker.group(1) if marker else settings.sql_dialect) or ""
        if chosen.strip().lower() in _GENERIC_DIALECTS:
            return None
        name = chosen.strip().lower()
        try:
            sqlglot.Dialect.get_or_raise(name)
        except Exception as exc:  # noqa: BLE001 — sqlglot raises ValueError, but be defensive.
            logger.warning("unknown SQL dialect %r, falling back to generic: %s", name, exc)
            return None
        return name


class _SchemaBuilder:
    """Accumulates schema nodes as `SqlParser` feeds it top-level statements."""

    def __init__(self, *, file_path: str, dialect: str | None) -> None:
        self._file_path = file_path
        self._dialect = dialect
        self.tables: list[DbTable] = []
        self.columns: list[DbColumn] = []
        self.views: list[DbView] = []
        self.indexes: list[DbIndex] = []
        self.references: list[DbReference] = []
        self._columns_by_qualified_name: dict[str, DbColumn] = {}
        self._tables_by_qualified_name: dict[str, DbTable] = {}

    def consume(self, statement: "exp.Expression") -> None:
        from sqlglot import exp

        if isinstance(statement, exp.Create):
            kind = (statement.args.get("kind") or "").upper()
            if kind == "TABLE" and isinstance(statement.this, exp.Schema):
                self._add_table(statement)
            elif kind == "VIEW":
                self._add_view(statement)
            elif kind == "INDEX":
                self._add_index(statement)
        elif isinstance(statement, exp.Alter):
            self._apply_alter(statement)

    # -- CREATE TABLE -----------------------------------------------------

    def _add_table(self, statement: "exp.Create") -> None:
        from sqlglot import exp

        schema_expr: exp.Schema = statement.this
        table_qualified_name, schema_name, name = _table_identity(schema_expr.this)

        pk_columns = self._table_level_primary_key_columns(schema_expr)
        column_defs = [e for e in schema_expr.expressions if isinstance(e, exp.ColumnDef)]
        columns: list[DbColumn] = []
        table_references: list[str] = []
        for column_def in column_defs:
            column, inline_ref_tables = self._build_column(
                column_def,
                table_qualified_name=table_qualified_name,
                forced_primary_key=_identifier_text(column_def.this) in pk_columns,
            )
            columns.append(column)
            table_references.extend(inline_ref_tables)

        for foreign_key in schema_expr.find_all(exp.ForeignKey):
            table_references.extend(
                self._apply_foreign_key(foreign_key, {c.name: c for c in columns})
            )

        table = DbTable(
            qualified_name=table_qualified_name,
            name=name,
            schema_name=schema_name,
            file_path=self._file_path,
            references=_unique(table_references),
            embed_text=_table_embed_text(table_qualified_name, columns),
        )
        self.tables.append(table)
        self._tables_by_qualified_name[table_qualified_name] = table
        for column in columns:
            self.columns.append(column)
            self._columns_by_qualified_name[column.qualified_name] = column

    def _build_column(
        self, column_def: "exp.ColumnDef", *, table_qualified_name: str, forced_primary_key: bool
    ) -> tuple[DbColumn, list[str]]:
        """`(column, inline_reference_target_tables)` — the second element feeds
        the owning table's `REFERENCES` edge for inline `col … REFERENCES t(c)`.
        """
        from sqlglot import exp

        name = _identifier_text(column_def.this)
        data_type_node = column_def.args.get("kind")
        data_type = (
            data_type_node.sql(dialect=self._dialect) if data_type_node is not None else None
        )

        nullable = True
        primary_key = forced_primary_key
        default: str | None = None
        column_references: list[str] = []
        table_references: list[str] = []
        for constraint in column_def.constraints:
            kind = constraint.kind
            if isinstance(kind, exp.PrimaryKeyColumnConstraint):
                primary_key = True
            elif isinstance(kind, exp.NotNullColumnConstraint):
                nullable = bool(kind.args.get("allow_null"))
            elif isinstance(kind, exp.DefaultColumnConstraint) and kind.this is not None:
                default = kind.this.sql(dialect=self._dialect)
            elif isinstance(kind, exp.Reference):
                target_table, target_columns = _reference_target(kind)
                _append_unique(table_references, target_table)
                if target_columns:
                    _append_unique(column_references, f"{target_table}.{target_columns[0]}")

        column = DbColumn(
            qualified_name=f"{table_qualified_name}.{name}",
            name=name,
            table_qualified_name=table_qualified_name,
            data_type=data_type,
            # A primary-key column is implicitly NOT NULL.
            nullable=nullable and not primary_key,
            default=default,
            primary_key=primary_key,
            references=column_references,
        )
        return column, table_references

    @staticmethod
    def _table_level_primary_key_columns(schema_expr: "exp.Schema") -> set[str]:
        from sqlglot import exp

        names: set[str] = set()
        for primary_key in schema_expr.find_all(exp.PrimaryKey):
            for part in primary_key.expressions:
                names.add(_identifier_text(part))
        return names

    def _apply_foreign_key(
        self, foreign_key: "exp.ForeignKey", columns_by_name: dict[str, DbColumn]
    ) -> list[str]:
        """Wire a `FOREIGN KEY` onto its local `DbColumn`s; return the target
        table qualified name(s) for the table-level `REFERENCES` edge.
        """
        local_names = [_identifier_text(part) for part in foreign_key.expressions]
        reference = foreign_key.args.get("reference")
        if reference is None:
            return []
        target_table, target_columns = _reference_target(reference)
        for position, local_name in enumerate(local_names):
            column = columns_by_name.get(local_name)
            if column is not None and position < len(target_columns):
                _append_unique(column.references, f"{target_table}.{target_columns[position]}")
        return [target_table]

    # -- CREATE VIEW ----------------------------------------------------

    def _add_view(self, statement: "exp.Create") -> None:
        from sqlglot import exp

        target = statement.this
        if isinstance(target, exp.Schema):
            target = target.this
        view_qualified_name, schema_name, name = _table_identity(target)
        materialized = statement.find(exp.MaterializedProperty) is not None

        select = statement.expression
        depends_on: list[str] = []
        definition: str | None = None
        if select is not None:
            cte_names = {
                _identifier_text(cte.args.get("alias")) for cte in select.find_all(exp.CTE)
            }
            depends_on = _unique(
                identity
                for table in select.find_all(exp.Table)
                for identity in (_table_identity(table)[0],)
                if identity not in cte_names and identity != view_qualified_name
            )
            definition = select.sql(dialect=self._dialect)

        self.views.append(
            DbView(
                qualified_name=view_qualified_name,
                name=name,
                schema_name=schema_name,
                materialized=materialized,
                file_path=self._file_path,
                depends_on=depends_on,
                embed_text=_view_embed_text(
                    view_qualified_name, materialized, depends_on, definition
                ),
            )
        )

    # -- CREATE INDEX -------------------------------------------------

    def _add_index(self, statement: "exp.Create") -> None:
        from sqlglot import exp

        index_node = statement.this
        if not isinstance(index_node, exp.Index) or index_node.this is None:
            return
        table = index_node.args.get("table")
        if table is None:
            return
        table_qualified_name = _table_identity(table)[0]
        name = _identifier_text(index_node.this)
        params = index_node.args.get("params")
        column_nodes = params.args.get("columns", []) if params is not None else []
        columns = [_index_column_name(node) for node in column_nodes]
        self.indexes.append(
            DbIndex(
                qualified_name=f"{table_qualified_name}.{name}",
                name=name,
                table_qualified_name=table_qualified_name,
                columns=[column for column in columns if column],
                unique=bool(statement.args.get("unique")),
            )
        )

    # -- ALTER TABLE … ADD CONSTRAINT … FOREIGN KEY -----------------

    def _apply_alter(self, statement: "exp.Alter") -> None:
        from sqlglot import exp

        if not isinstance(statement.this, exp.Table):
            return
        table_qualified_name = _table_identity(statement.this)[0]
        table = self._tables_by_qualified_name.get(table_qualified_name)
        for foreign_key in statement.find_all(exp.ForeignKey):
            local_names = [_identifier_text(part) for part in foreign_key.expressions]
            reference = foreign_key.args.get("reference")
            if reference is None:
                continue
            target_table, target_columns = _reference_target(reference)
            for position, local_name in enumerate(local_names):
                if position >= len(target_columns):
                    continue
                from_column = f"{table_qualified_name}.{local_name}"
                to_column = f"{target_table}.{target_columns[position]}"
                column = self._columns_by_qualified_name.get(from_column)
                if column is not None:
                    _append_unique(column.references, to_column)
                else:
                    # `ALTER TABLE` in a different file from the `CREATE TABLE`.
                    self.references.append(
                        DbReference(
                            from_qualified_name=from_column,
                            to_qualified_name=to_column,
                            level="column",
                        )
                    )
            if table is not None:
                _append_unique(table.references, target_table)
            else:
                self.references.append(
                    DbReference(
                        from_qualified_name=table_qualified_name,
                        to_qualified_name=target_table,
                        level="table",
                    )
                )


# -- module-level helpers ------------------------------------------------


def _identifier_text(node: "exp.Expression | None") -> str:
    from sqlglot import exp

    if node is None:
        return ""
    if isinstance(node, exp.Identifier):
        return node.this
    if isinstance(node, (exp.Column, exp.Ordered)) and node.this is not None:
        return _identifier_text(node.this)
    return node.name or node.sql()


def _table_identity(table: "exp.Expression") -> tuple[str, str | None, str]:
    """`(qualified_name, schema_name, name)` for an `exp.Table` — dialect
    identifiers (catalog / schema / name) joined with dots, quotes stripped.
    """
    from sqlglot import exp

    if not isinstance(table, exp.Table):
        rendered = table.name or table.sql()
        return rendered, None, rendered
    parts = [part for part in (table.catalog, table.db, table.name) if part]
    qualified_name = ".".join(parts) if parts else table.name
    return qualified_name, (table.db or None), table.name


def _reference_target(reference: "exp.Reference") -> tuple[str, list[str]]:
    from sqlglot import exp

    target = reference.this
    if isinstance(target, exp.Schema):
        qualified_name = _table_identity(target.this)[0]
        columns = [_identifier_text(part) for part in target.expressions]
        return qualified_name, columns
    return _table_identity(target)[0], []


def _index_column_name(node: "exp.Expression") -> str:
    return _identifier_text(node)


def _unique(values) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        if value:
            seen.setdefault(value, None)
    return list(seen)


def _append_unique(target: list[str], value: str) -> None:
    if value and value not in target:
        target.append(value)


def _column_summary(column: DbColumn) -> str:
    parts = [column.name]
    if column.data_type:
        parts.append(column.data_type)
    if column.primary_key:
        parts.append("PRIMARY KEY")
    if not column.nullable:
        parts.append("NOT NULL")
    return " ".join(parts)


def _table_embed_text(qualified_name: str, columns: list[DbColumn]) -> str:
    summary = f"CREATE TABLE {qualified_name}."
    if columns:
        summary += " Columns: " + ", ".join(_column_summary(column) for column in columns) + "."
    foreign_keys = [
        f"{column.name} -> {target}" for column in columns for target in column.references
    ]
    if foreign_keys:
        summary += " Foreign keys: " + "; ".join(foreign_keys) + "."
    return summary


def _view_embed_text(
    qualified_name: str, materialized: bool, depends_on: list[str], definition: str | None
) -> str:
    summary = f"CREATE {'MATERIALIZED ' if materialized else ''}VIEW {qualified_name}."
    if depends_on:
        summary += " Depends on: " + ", ".join(depends_on) + "."
    if definition:
        summary += " " + definition[:_DEFINITION_LIMIT]
    return summary
