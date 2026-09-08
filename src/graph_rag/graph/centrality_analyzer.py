from typing import LiteralString, cast

from neo4j import Driver

_PROJECTION_NAME = "code-deps"

# Direct `CALLS` / `IMPORTS` plus the framework-mediated edges (v0.7.0): a
# controller `IS_BEAN`→ bean `INJECTS`→ repo bean ←`IS_BEAN` repository, an
# `@EventListener` reached via `EventType`, a Camel `process` step's `INVOKES`,
# a `@FeignClient` `CALLS_SERVICE`, a `@Mapper` `EXECUTES`. PageRank runs over
# the union so "riskiest to change" reflects framework coupling, not just
# source calls; the extra node labels are projected only so their edges connect
# (`get_central_code_entities` still filters to `CodeEntity` with a `name`).
_PROJECT_GRAPH = """
CALL gds.graph.project(
    $name,
    ['CodeEntity', 'Bean', 'EventType', 'Destination', 'HttpEndpoint', 'CamelStep',
     'SqlStatement'],
    ['CALLS', 'IMPORTS', 'IS_BEAN', 'INJECTS', 'PUBLISHES', 'CONSUMED_BY',
     'CALLS_SERVICE', 'RESOLVES_TO', 'INVOKES', 'EXECUTES']
)
YIELD nodeCount, relationshipCount
RETURN nodeCount, relationshipCount
"""

_RUN_PAGERANK = """
CALL gds.pageRank.write($name, {writeProperty: 'pagerank'})
YIELD nodePropertiesWritten
RETURN nodePropertiesWritten
"""

_DROP_GRAPH = "CALL gds.graph.drop($name, false)"


class CentralityAnalyzer:
    """Runs GDS PageRank over the `CodeEntity` dependency graph — direct
    `CALLS`/`IMPORTS` plus the framework-mediated edges (`IS_BEAN` / `INJECTS`,
    `PUBLISHES` / `CONSUMED_BY`, Camel `INVOKES`, `CALLS_SERVICE`, `EXECUTES`) —
    writing each entity's score to `CodeEntity.pagerank`. An entity many others
    reach (directly or through a bean / event / route) ranks higher, surfacing
    what's most central (and riskiest to change) in the ingested codebase.

    Scores every `CodeEntity` node reachable via `CALLS`/`IMPORTS`, including
    external-library stub nodes that exist only as edge targets (e.g.
    `typing.cast`) and were never fully parsed — callers that only want this
    repo's own entities should filter on `name IS NOT NULL`, since stub nodes
    have no `name`/`kind`/`docstring` set.

    Uses `code-deps` as a throwaway in-memory GDS projection per run: create,
    run, drop — nothing about the projection itself persists, only the
    written-back `pagerank` property does.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def compute_code_pagerank(self) -> int:
        """Returns how many `CodeEntity` nodes were scored (0 if there are
        no `CALLS`/`IMPORTS` edges to project).
        """
        with self._driver.session() as session:
            projected = session.run(
                cast(LiteralString, _PROJECT_GRAPH), name=_PROJECTION_NAME
            ).single()
            if projected is None or projected["relationshipCount"] == 0:
                session.run(cast(LiteralString, _DROP_GRAPH), name=_PROJECTION_NAME)
                return 0
            try:
                record = session.run(
                    cast(LiteralString, _RUN_PAGERANK), name=_PROJECTION_NAME
                ).single()
                return record["nodePropertiesWritten"] if record else 0
            finally:
                session.run(cast(LiteralString, _DROP_GRAPH), name=_PROJECTION_NAME)
