import re

# Table name after a FROM / JOIN (read) or INTO / UPDATE / `DELETE FROM` (write).
# Best-effort: one identifier, optionally schema-qualified, quoting stripped.
_READ = re.compile(r"\b(?:from|join)\s+([A-Za-z_][\w.$]*)", re.IGNORECASE)
_WRITE = re.compile(
    r"\b(?:insert\s+into|update|delete\s+from|merge\s+into)\s+([A-Za-z_][\w.$]*)",
    re.IGNORECASE,
)
_QUOTES = '`"[]'

# Stripped before the scan so a `from` / `join` word inside a string literal
# (`note LIKE '%from customer%'`) or a comment (`-- join audit_log`) doesn't
# produce a phantom table. Block comments first (they can wrap `--` and `'`),
# then string literals, then line comments.
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_LINE_COMMENT = re.compile(r"--[^\n]*")


class SqlTableScanner:
    """Pulls table names + access mode out of a (flattened) SQL string —
    good enough for the MyBatis mapper graph, not a real SQL parser.
    """

    @classmethod
    def scan(cls, sql: str) -> list[dict[str, str]]:
        sql = cls._strip_noise(sql)
        found: dict[str, str] = {}
        for match in _WRITE.finditer(sql):
            found[cls._clean(match.group(1))] = "write"
        for match in _READ.finditer(sql):
            name = cls._clean(match.group(1))
            found.setdefault(name, "read")
        return [{"name": name, "mode": mode} for name, mode in found.items() if name]

    @staticmethod
    def _strip_noise(sql: str) -> str:
        sql = _BLOCK_COMMENT.sub(" ", sql)
        sql = _STRING_LITERAL.sub(" ", sql)
        return _LINE_COMMENT.sub(" ", sql)

    @staticmethod
    def _clean(raw: str) -> str:
        return raw.strip().strip(_QUOTES).rsplit(".", 1)[-1].strip(_QUOTES)
