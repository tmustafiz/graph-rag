from typing import LiteralString, cast

from neo4j import Driver

_PROJECTION_NAME = "code-deps"

_PROJECT_GRAPH = """
CALL gds.graph.project($name, 'CodeEntity', ['CALLS', 'IMPORTS'])
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
    """Runs GDS PageRank over the `CodeEntity` `CALLS`/`IMPORTS` dependency
    graph, writing each entity's score to `CodeEntity.pagerank` — an entity
    called/imported by many others ranks higher, surfacing what's most
    central (and riskiest to change) in the ingested codebase.

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
