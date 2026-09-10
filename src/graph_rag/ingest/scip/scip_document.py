from dataclasses import dataclass, field

from .scip_occurrence import ScipOccurrence
from .scip_symbol import ScipSymbol


@dataclass
class ScipDocument:
    """One `Document` from a SCIP index — a single source file, its
    `relative_path` (repo-root-relative, forward slashes), the symbols defined
    in it, and every occurrence within it.
    """

    relative_path: str
    language: str = ""
    symbols: list[ScipSymbol] = field(default_factory=list)
    occurrences: list[ScipOccurrence] = field(default_factory=list)
