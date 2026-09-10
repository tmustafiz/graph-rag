from dataclasses import dataclass, field

# `Occurrence.symbol_roles` bitset (SCIP spec).
ROLE_DEFINITION = 0x1
ROLE_IMPORT = 0x2
ROLE_WRITE_ACCESS = 0x4
ROLE_READ_ACCESS = 0x8


@dataclass
class ScipOccurrence:
    """One `Occurrence` — a use of a symbol at a source range.

    `range` is `[start_line, start_char, end_line, end_char]` (or 3 ints when
    start and end are on one line). `enclosing_range`, when present, is the
    range of the symbol whose body this occurrence sits in — used to attribute
    a reference to its calling method.
    """

    symbol: str
    symbol_roles: int = 0
    range: list[int] = field(default_factory=list)
    enclosing_range: list[int] = field(default_factory=list)

    @property
    def is_definition(self) -> bool:
        return bool(self.symbol_roles & ROLE_DEFINITION)

    @property
    def is_import(self) -> bool:
        return bool(self.symbol_roles & ROLE_IMPORT)

    @property
    def start_line(self) -> int | None:
        return self.range[0] if self.range else None
