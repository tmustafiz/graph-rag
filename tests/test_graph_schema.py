"""#166 — the framework graph vocabulary (`schema.py`) is the single source of
truth for the label / relationship-type names the v0.7.0 layer adds. These
guards fail if `CentralityAnalyzer`'s projection list drifts from what
`graph_writer` / the resolvers actually write, or from the constrained labels.
"""

import re
from pathlib import Path

import graph_rag.graph as graph_pkg
from graph_rag.graph.schema import (
    CONSTRAINTS,
    DIRECT_RELATIONSHIP_TYPES,
    FRAMEWORK_NODE_LABELS,
    FRAMEWORK_RELATIONSHIP_TYPES,
)

_GRAPH_DIR = Path(graph_pkg.__file__).parent
_GRAPH_SOURCE = "\n".join(
    path.read_text()
    for path in sorted(_GRAPH_DIR.glob("*.py"))
    if path.name != "centrality_analyzer.py"
)


def test_direct_relationship_types_are_the_base_code_graph() -> None:
    assert DIRECT_RELATIONSHIP_TYPES == ("CALLS", "IMPORTS")


def test_every_framework_relationship_type_is_actually_written() -> None:
    """A type in the projection list that no `graph/` module MERGEs would be
    dead weight (best case) or a rename left behind (worst case)."""
    for rel_type in FRAMEWORK_RELATIONSHIP_TYPES:
        assert re.search(rf"\[\s*\w*\s*:\s*{rel_type}\b", _GRAPH_SOURCE), (
            f"{rel_type} is in FRAMEWORK_RELATIONSHIP_TYPES but no graph/ module writes it"
        )


def test_every_framework_node_label_has_a_uniqueness_constraint() -> None:
    """The labels the projection names must be ones ingestion actually upserts —
    i.e. `schema.py` owns a constraint for each."""
    constrained = set(re.findall(r"FOR \(n:(\w+)\)", "\n".join(CONSTRAINTS)))
    for label in FRAMEWORK_NODE_LABELS:
        assert label in constrained, f"{label} has no uniqueness constraint in schema.CONSTRAINTS"


def test_centrality_analyzer_holds_no_private_copy_of_the_vocabulary() -> None:
    source = (_GRAPH_DIR / "centrality_analyzer.py").read_text()
    assert re.search(r"from \.schema import\b", source)
    # it must consume the shared constants, not re-list the label / type literals
    for literal in ('"IS_BEAN"', '"INVOKES"', '"CamelStep"', '"EventType"'):
        assert literal not in source
