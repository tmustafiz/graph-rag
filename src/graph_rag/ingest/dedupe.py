from collections.abc import Iterable


def dedupe(items: Iterable[str], *, keep_empty: bool = False) -> list[str]:
    """Order-preserving de-duplication of a string sequence.

    First occurrence wins. Falsy entries (`""`, `None`) are dropped unless
    `keep_empty=True`. Replaces the ~8 hand-rolled `_dedupe` / `_unique`
    copies across the parsers and the SCIP ingestor (#166).
    """
    seen: dict[str, None] = {}
    for item in items:
        if item or keep_empty:
            seen.setdefault(item, None)
    return list(seen)
