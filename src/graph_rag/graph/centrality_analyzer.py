from typing import LiteralString, cast

from neo4j import Driver

_PROJECTION_NAME = "code-deps"

# Direct dependency edges — PageRank always needs at least one of these present,
# and they keep their natural direction ("many callers reach X" → X ranks high).
_DIRECT_TYPES: tuple[str, ...] = ("CALLS", "IMPORTS")

# Framework-mediated edges (v0.7.0): a controller `IS_BEAN`→ bean `INJECTS`→ repo
# bean ←`IS_BEAN` repository, an `@EventListener` reached via `EventType`, a Camel
# `process` step's `INVOKES`, a `@FeignClient` `CALLS_SERVICE`, a `@Mapper`
# `EXECUTES`, a controller route `HANDLED_BY` its method. Projected UNDIRECTED so
# framework-mediated rank actually reaches the target `CodeEntity` regardless of
# each edge's stored direction.
_FRAMEWORK_TYPES: tuple[str, ...] = (
    "IS_BEAN",
    "INJECTS",
    "PUBLISHES",
    "CONSUMED_BY",
    "HANDLED_BY",
    "CALLS_SERVICE",
    "RESOLVES_TO",
    "INVOKES",
    "EXECUTES",
)

# Node labels the edges above connect. Only those that exist are projected —
# `gds.graph.project` validates every label / type against the DB token store and
# throws when one has zero instances (so a plain Python / pre-v0.7.0 DB used to
# abort instead of scoring).
_NODE_LABELS: tuple[str, ...] = (
    "CodeEntity",
    "Bean",
    "EventType",
    "Destination",
    "HttpEndpoint",
    "CamelStep",
    "SqlStatement",
)

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
            if not any(direct in present_types for direct in _DIRECT_TYPES):
                return 0
            present_labels = set(
                session.run(cast(LiteralString, _PRESENT_LABELS)).single()["labels"]
            )
            labels = [label for label in _NODE_LABELS if label in present_labels]
            relationships = {
                rel_type: {
                    "orientation": "UNDIRECTED" if rel_type in _FRAMEWORK_TYPES else "NATURAL"
                }
                for rel_type in (*_DIRECT_TYPES, *_FRAMEWORK_TYPES)
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
