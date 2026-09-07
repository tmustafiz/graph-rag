import logging
from typing import LiteralString, cast

from neo4j import Driver, ManagedTransaction

logger = logging.getLogger(__name__)

# Every Source file sits under exactly one module: the deepest `Module.path`
# that is a prefix of it. Rebuilt from scratch each run so a moved/removed
# file never keeps a stale edge.
_CLEAR_IN_MODULE = "MATCH ()-[r:IN_MODULE]->() DELETE r"

_LINK_IN_MODULE = """
MATCH (s:Source), (m:Module)
WHERE s.path STARTS WITH m.path + '/'
WITH s, m ORDER BY size(m.path) DESC
WITH s, head(collect(m)) AS nearest
MERGE (s)-[:IN_MODULE]->(nearest)
RETURN count(*) AS linked
"""

# HTTP endpoints inherit their defining Source's module.
_LINK_ENDPOINT_MODULE = """
MATCH (s:Source)-[:IN_MODULE]->(m:Module), (s)-[:DEFINES]->(ep:HttpEndpoint)
MERGE (ep)-[:IN_MODULE]->(m)
"""

# A declared dependency whose coordinates match another module in the graph —
# a Maven GAV that equals a sibling's `group:artifact`, or a Gradle
# `project:<name>` marker — is really a module→module edge.
_PROMOTE_SIBLING_DEPENDENCIES = """
MATCH (m:Module)-[d:DEPENDS_ON_EXTERNAL]->(e:ExternalArtifact)
MATCH (sibling:Module)
WHERE (
    e.group IS NOT NULL AND sibling.group = e.group AND sibling.artifact = e.artifact
) OR (
    e.gav STARTS WITH 'project:' AND sibling.path ENDS WITH '/' + substring(e.gav, 8)
)
WITH m, d, e, head(collect(sibling)) AS sibling
MERGE (m)-[nd:DEPENDS_ON]->(sibling)
SET nd.scope = d.scope
DELETE d
RETURN count(*) AS promoted
"""

_DROP_ORPHAN_PROJECT_ARTIFACTS = """
MATCH (e:ExternalArtifact)
WHERE e.gav STARTS WITH 'project:' AND NOT ()-[:DEPENDS_ON_EXTERNAL]->(e)
DETACH DELETE e
"""

_INTERNAL_PREFIXES = "MATCH (m:Module) UNWIND m.packages AS package RETURN DISTINCT package"

_IMPORT_EDGES = """
MATCH (:CodeEntity)-[r:IMPORTS]->(target:CodeEntity)
RETURN elementId(r) AS edge_id, target.qualified_name AS target,
       COUNT { (:Source)-[:DEFINES]->(target) } > 0 AS first_party
"""

_SET_IMPORT_EXTERNAL = """
UNWIND $rows AS row
MATCH ()-[r:IMPORTS]->()
WHERE elementId(r) = row.edge_id
SET r.external = row.external
"""


class ProjectModelResolver:
    """Second pass over a directory ingest that ties the Maven/Gradle module
    layer to the code graph:

    * `(Source)-[:IN_MODULE]->(Module)` — every file to its nearest module dir.
    * `DEPENDS_ON_EXTERNAL` → `DEPENDS_ON` when the target's coordinates match
      another `Module` (Maven sibling GAV, or a Gradle `project(':x')` marker).
    * `external` (bool) on every `(CodeEntity)-[:IMPORTS]->(CodeEntity)` edge —
      `false` when the target is first-party (some `Source` `DEFINES` it) or its
      FQN sits under a known module package prefix (`Module.packages`, seeded
      from `groupId` / Gradle `group`), `true` otherwise.

    All three steps are idempotent; `IN_MODULE` is rebuilt from scratch so a
    moved or deleted file leaves no stale edge.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def resolve(self) -> dict[str, int]:
        with self._driver.session() as session:
            linked = session.execute_write(self._rewire_in_module)
            promoted = session.execute_write(self._promote_sibling_dependencies)
            classified = session.execute_write(self._classify_imports)
        result = {
            "in_module": linked,
            "promoted_dependencies": promoted,
            "imports_classified": classified,
        }
        logger.info("project model resolved: %s", result)
        return result

    @staticmethod
    def _rewire_in_module(tx: ManagedTransaction) -> int:
        tx.run(cast(LiteralString, _CLEAR_IN_MODULE))
        record = tx.run(cast(LiteralString, _LINK_IN_MODULE)).single()
        tx.run(cast(LiteralString, _LINK_ENDPOINT_MODULE))
        return record["linked"] if record else 0

    @staticmethod
    def _promote_sibling_dependencies(tx: ManagedTransaction) -> int:
        record = tx.run(cast(LiteralString, _PROMOTE_SIBLING_DEPENDENCIES)).single()
        promoted = record["promoted"] if record else 0
        tx.run(cast(LiteralString, _DROP_ORPHAN_PROJECT_ARTIFACTS))
        return promoted

    @classmethod
    def _classify_imports(cls, tx: ManagedTransaction) -> int:
        prefixes = [row["package"] for row in tx.run(cast(LiteralString, _INTERNAL_PREFIXES))]
        rows = [
            {
                "edge_id": row["edge_id"],
                "external": cls._is_external(row["target"], row["first_party"], prefixes),
            }
            for row in tx.run(cast(LiteralString, _IMPORT_EDGES))
        ]
        if rows:
            tx.run(cast(LiteralString, _SET_IMPORT_EXTERNAL), rows=rows)
        return len(rows)

    @staticmethod
    def _is_external(target: str | None, first_party: bool, internal_prefixes: list[str]) -> bool:
        if first_party:
            return False
        if not target:
            return True
        return not any(
            target == prefix or target.startswith(f"{prefix}.") for prefix in internal_prefixes
        )
