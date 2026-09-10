from dataclasses import dataclass, field


@dataclass
class ScipSymbol:
    """A `SymbolInformation` record from a SCIP index — one definition, plus its
    documentation and its relationships to other symbols.

    `symbol` is the raw SCIP symbol string (globally unique by construction:
    scheme + package manager + package + version + descriptors). `kind` is the
    numeric `SymbolInformation.Kind` (0 when the indexer left it unset — the
    descriptor suffix is then the fallback). `relationships` is a list of
    `(symbol, is_reference, is_implementation, is_type_definition)` tuples.
    """

    symbol: str
    display_name: str = ""
    kind: int = 0
    documentation: list[str] = field(default_factory=list)
    # (target_symbol, is_reference, is_implementation, is_type_definition)
    relationships: list[tuple[str, bool, bool, bool]] = field(default_factory=list)
