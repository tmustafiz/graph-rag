import re

# A SCIP symbol string is: `<scheme> <manager> <package> <version> <descriptors>`
# (space-separated, spaces inside a field escaped as `  `). The descriptors are a
# run of: `name/` (namespace), `name#` (type), `name.` (term), `name().` (method),
# `(name)` (parameter), `[name]` (type parameter), `:name` (meta). scip-java
# disambiguates overloads past the first with a token between the method parens
# (`submit(+1).`, `submit(String).`), so the method branch accepts any run of
# non-`)` characters there and keeps it as part of the name.
_DESCRIPTOR = re.compile(
    r"""
    (?P<name>
        (?:[^\s./#()\[\]:`]+ | `[^`]+`)
    )
    (?:
        \( (?P<disambiguator>[^)]*) \) (?P<method>\.)
        |
        (?P<suffix> [.#/] )
    )
    |
    \( (?P<param>[^)]*) \)
    |
    \[ (?P<typeparam>[^\]]*) \]
    |
    : (?P<meta>[^\s]*)
    """,
    re.VERBOSE,
)
_LOCAL = re.compile(r"^local\b")


class ScipSymbolParser:
    """Turns a raw SCIP symbol string into a readable, globally-unique
    `qualified_name` plus a best-effort `kind` and simple `name`.

    `com/acme/OrderService#submit().` → `com.acme.OrderService.submit` (method);
    `com/acme/OrderService#` → `com.acme.OrderService` (type);
    `com/acme/OrderService#total.` → `com.acme.OrderService.total` (field).
    A `local N` symbol (indexer-local, not cross-file) returns `None`.
    """

    @classmethod
    def parse(cls, symbol: str) -> tuple[str, str, str] | None:
        symbol = symbol.strip()
        if not symbol or _LOCAL.match(symbol):
            return None
        descriptors = cls._descriptor_part(symbol)
        parts: list[str] = []
        last_suffix = ""
        for match in _DESCRIPTOR.finditer(descriptors):
            if match.group("name") is None:
                continue
            name = match.group("name").strip("`")
            if match.group("method") is not None:
                disambiguator = match.group("disambiguator") or ""
                parts.append(f"{name}({disambiguator})" if disambiguator else name)
                last_suffix = "()."
            else:
                parts.append(name)
                last_suffix = match.group("suffix")
        if not parts:
            return None
        qualified_name = ".".join(parts)
        kind = cls._kind_from_suffix(last_suffix)
        return qualified_name, kind, parts[-1]

    @staticmethod
    def _descriptor_part(symbol: str) -> str:
        # 5 space-separated fields; anything past the 4th space is the descriptors.
        fields = symbol.split(" ")
        return " ".join(fields[4:]) if len(fields) > 4 else symbol

    @staticmethod
    def _kind_from_suffix(suffix: str) -> str:
        return {
            "().": "method",
            "#": "type",
            ".": "term",
            "/": "namespace",
        }.get(suffix, "symbol")
