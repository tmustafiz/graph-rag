import re

# Table name after a FROM / JOIN (read) or INTO / UPDATE / `DELETE FROM` (write).
# Best-effort: one identifier, optionally schema-qualified, quoting stripped.
_READ = re.compile(r"\b(?:from|join)\s+([A-Za-z_][\w.$]*)", re.IGNORECASE)
_WRITE = re.compile(
    r"\b(?:insert\s+into|update|delete\s+from|merge\s+into)\s+([A-Za-z_][\w.$]*)",
    re.IGNORECASE,
)
_QUOTES = '`"[]'


class SqlTableScanner:
    """Pulls table names + access mode out of a (flattened) SQL string —
    good enough for the MyBatis mapper graph, not a real SQL parser.
    """

    @classmethod
    def scan(cls, sql: str) -> list[dict[str, str]]:
        found: dict[str, str] = {}
        for match in _WRITE.finditer(sql):
            found[cls._clean(match.group(1))] = "write"
        for match in _READ.finditer(sql):
            name = cls._clean(match.group(1))
            found.setdefault(name, "read")
        return [{"name": name, "mode": mode} for name, mode in found.items() if name]

    @staticmethod
    def _clean(raw: str) -> str:
        return raw.strip().strip(_QUOTES).rsplit(".", 1)[-1].strip(_QUOTES)
