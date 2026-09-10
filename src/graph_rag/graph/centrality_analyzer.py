from typing import LiteralString, cast

from neo4j import Driver

from .schema import (
    DIRECT_RELATIONSHIP_TYPES,
    FRAMEWORK_NODE_LABELS,
    FRAMEWORK_RELATIONSHIP_TYPES,
)

_PROJECTION_NAME = "code-deps"

# The projection vocabulary lives in `schema.py` (single source of truth):
#   - `DIRECT_RELATIONSHIP_TYPES` — `CALLS` / `IMPORTS`, kept NATURAL so
#     "many callers reach X" ranks X high; PageRank needs >=1 of these present.
#   - `FRAMEWORK_RELATIONSHIP_TYPES` — the v0.7.0 framework-mediated edges
#     (`IS_BEAN` / `INJECTS`, `PUBLISHES` / `CONSUMED_BY`, `HANDLED_BY`,
#     Camel `INVOKES`, `CALLS_SERVICE`, `RESOLVES_TO`, `EXECUTES`), projected
#     UNDIRECTED so framework rank reaches the target `CodeEntity` whichever way
#     each edge is stored.
#   - `FRAMEWORK_NODE_LABELS` — the node labels those edges connect.
# Only the subset actually present in the DB is projected: `gds.graph.project`
# validates every label / type against the token store and throws on one with
# zero instances (a plain-Python / pre-v0.7.0 DB projects just `CALLS`/`IMPORTS`).

_PRESENT_TYPES = (
    "CALL db.relationshipTypes() YIELD relationshipType RETURN collect(relationshipType) AS types"
)
_PRESENT_LABELS = "CALL db.labels() YIELD label RETURN collect(label) AS labels"

_PROJECT_GRAPH = """
CALL gds.graph.project($name, $labels, $relationships)
YIELD nodeCount, relationshipCount
RETURN nodeCount, relationshipCount
"""

_RUN_PAGERANK = """
CALL gds.pageRank.write($name, {writeProperty: 'pagerank'})
YIELD nodePropertiesWritten
RETURN nodePropertiesWritten
"""

_COUNT_SCORED = "MATCH (c:CodeEntity) WHERE c.pagerank IS NOT NULL RETURN count(c) AS scored"

_DROP_GRAPH = "CALL gds.graph.drop($name, false)"


class CentralityAnalyzer:
    """Runs GDS PageRank over the `CodeEntity` dependency graph — direct
    `CALLS`/`IMPORTS` plus whichever framework-mediated edges (`IS_BEAN` /
    `INJECTS`, `PUBLISHES` / `CONSUMED_BY`, `HANDLED_BY`, Camel `INVOKES`,
    `CALLS_SERVICE`, `EXECUTES`) actually exist in this database — writing each
    entity's score to `CodeEntity.pagerank`. An entity many others reach
    (directly or through a bean / event / route) ranks higher, surfacing what's
    most central (and riskiest to change) in the ingested codebase.

    The projection is built from `db.relationshipTypes()` / `db.labels()` so a
    non-Spring / plain-Python / pre-v0.7.0 database projects only `CALLS` /
    `IMPORTS` and still scores instead of throwing.

    `compute_code_pagerank` returns the number of `CodeEntity` nodes scored.
    `gds.pageRank.write` also stamps `pagerank` on the projected framework nodes
    (`Bean`, `HttpEndpoint`, …) that exist only as edge waypoints — callers that
    want this repo's own entities filter on `:CodeEntity` + `name IS NOT NULL`
    (stub nodes have no `name`/`kind`/`docstring`).

    Uses `code-deps` as a throwaway in-memory GDS projection per run: create,
    run, drop — only the written-back `pagerank` property persists.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def compute_code_pagerank(self) -> int:
        """Returns how many `CodeEntity` nodes were scored (0 if there are
        no `CALLS`/`IMPORTS` edges to project).
        """
        with self._driver.session() as session:
            present_types = set(session.run(cast(LiteralString, _PRESENT_TYPES)).single()["types"])
            if not any(direct in present_types for direct in DIRECT_RELATIONSHIP_TYPES):
                return 0
            present_labels = set(
                session.run(cast(LiteralString, _PRESENT_LABELS)).single()["labels"]
            )
            labels = [label for label in FRAMEWORK_NODE_LABELS if label in present_labels]
            relationships = {
                rel_type: {
                    "orientation": "UNDIRECTED"
                    if rel_type in FRAMEWORK_RELATIONSHIP_TYPES
                    else "NATURAL"
                }
                for rel_type in (*DIRECT_RELATIONSHIP_TYPES, *FRAMEWORK_RELATIONSHIP_TYPES)
                if rel_type in present_types
            }
            try:
                projected = session.run(
                    cast(LiteralString, _PROJECT_GRAPH),
                    name=_PROJECTION_NAME,
                    labels=labels,
                    relationships=relationships,
                ).single()
                if projected is None or projected["relationshipCount"] == 0:
                    return 0
                session.run(cast(LiteralString, _RUN_PAGERANK), name=_PROJECTION_NAME).single()
                scored = session.run(cast(LiteralString, _COUNT_SCORED)).single()
                return scored["scored"] if scored else 0
            finally:
                session.run(cast(LiteralString, _DROP_GRAPH), name=_PROJECTION_NAME)
