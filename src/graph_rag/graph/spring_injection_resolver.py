import json
import logging
from typing import Any, LiteralString, NamedTuple, cast

from neo4j import Driver, ManagedTransaction

logger = logging.getLogger(__name__)

# Every Spring Data repository interface is a bean, even without `@Repository`.
_REPO_DEFS = "MATCH (d:SpringDataRepoDef) RETURN d.qualified_name AS qn"

_CODE_ENTITY_NAMES = """
MATCH (c:CodeEntity)
WHERE c.qualified_name IN $qns
RETURN c.qualified_name AS qn, c.name AS name
"""

_MERGE_REPO_BEANS = """
UNWIND $rows AS row
MERGE (b:Bean {id: row.qn})
SET b.name = coalesce(b.name, row.name),
    b.bean_type = coalesce(b.bean_type, row.qn),
    b.stereotype = coalesce(b.stereotype, 'Repository'),
    b.defined_in = coalesce(b.defined_in, 'spring-data'),
    b.unresolved_injections = coalesce(b.unresolved_injections, '[]')
WITH b, row
MATCH (c:CodeEntity {qualified_name: row.qn})
MERGE (c)-[:IS_BEAN]->(b)
"""

_ALL_BEANS = """
MATCH (b:Bean)
RETURN b.id AS id, b.name AS name, b.bean_type AS bean_type,
       b.unresolved_injections AS unresolved
"""

_BEAN_SUPERTYPES = """
MATCH (c:CodeEntity)-[:IS_BEAN]->(b:Bean)
MATCH (c)-[:EXTENDS|IMPLEMENTS*1..]->(s:CodeEntity)
RETURN b.id AS id, collect(DISTINCT s.qualified_name) AS supertypes
"""

_MERGE_INJECTS = """
UNWIND $rows AS row
MATCH (s:Bean {id: row.from})
MATCH (t:Bean {id: row.to})
MERGE (s)-[r:INJECTS]->(t)
SET r.via = row.via
"""

_SET_UNRESOLVED = """
UNWIND $rows AS row
MATCH (b:Bean {id: row.id})
SET b.unresolved_injections = row.unresolved_injections
"""


class _Assembled(NamedTuple):
    injects: list[dict[str, str]]
    unresolved_updates: list[dict[str, str]]


class SpringInjectionResolver:
    """Final Spring pass, after `SpringBeanResolver` / `SpringXmlResolver` /
    `SpringDataResolver`. Two jobs the earlier single-pass wiring can't do:

    * Every `SpringDataRepoDef` interface becomes a `(:Bean {stereotype:
      'Repository'})` + `IS_BEAN`, with `bean_type` = the interface FQN, so a
      constructor / `@Autowired` injection of `OrderRepository extends
      JpaRepository<Order, Long>` (no `@Repository` annotation) resolves by
      type (#114).
    * Re-runs injection resolution for every bean that still has
      `unresolved_injections`, now that the **complete** bean set (annotation +
      XML + repository) exists — an `@Service` `@Autowired`-ing a bean declared
      only in `applicationContext.xml`, or a repository, was recorded as "no
      matching bean" by the first pass because those beans didn't exist yet
      (#122). A now-unique match becomes an `INJECTS` edge and is dropped from
      `unresolved_injections`.

    Only adds edges / prunes resolved entries; `SpringBeanResolver` wipes and
    rebuilds every `:Bean` at the start of the chain, so this stays idempotent.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def resolve(self) -> dict[str, int]:
        with self._driver.session() as session:
            result = session.execute_write(self._rebuild)
        logger.info("spring injection graph resolved: %s", result)
        return result

    @classmethod
    def _rebuild(cls, tx: ManagedTransaction) -> dict[str, int]:
        repo_qns = [row["qn"] for row in tx.run(cast(LiteralString, _REPO_DEFS))]
        if repo_qns:
            names = {
                row["qn"]: row["name"]
                for row in tx.run(cast(LiteralString, _CODE_ENTITY_NAMES), qns=repo_qns)
            }
            repo_rows = [
                {"qn": qn, "name": cls._decapitalize(cls._simple_name(names.get(qn, qn)))}
                for qn in repo_qns
            ]
            tx.run(cast(LiteralString, _MERGE_REPO_BEANS), rows=repo_rows)

        beans = [dict(row) for row in tx.run(cast(LiteralString, _ALL_BEANS))]
        supertypes = {
            row["id"]: row["supertypes"] for row in tx.run(cast(LiteralString, _BEAN_SUPERTYPES))
        }
        assembled = cls._assemble(beans, supertypes)
        if assembled.injects:
            tx.run(cast(LiteralString, _MERGE_INJECTS), rows=assembled.injects)
        if assembled.unresolved_updates:
            tx.run(cast(LiteralString, _SET_UNRESOLVED), rows=assembled.unresolved_updates)
        return {
            "repository_beans": len(repo_qns),
            "rewired_injections": len(assembled.injects),
        }

    # -- assembly (pure — unit-tested without Neo4j) --

    @classmethod
    def _assemble(cls, beans: list[dict[str, Any]], supertypes: dict[str, list[str]]) -> _Assembled:
        by_id = {bean["id"]: bean for bean in beans}
        index: dict[str, set[str]] = {}

        def add(token: str | None, bean_id: str) -> None:
            if token:
                index.setdefault(token, set()).add(bean_id)

        for bean in beans:
            bean_type = bean.get("bean_type")
            add(bean_type, bean["id"])
            add(cls._simple_name(bean_type), bean["id"])
            for supertype in supertypes.get(bean["id"], []):
                add(supertype, bean["id"])
                add(cls._simple_name(supertype), bean["id"])

        injects: list[dict[str, str]] = []
        updates: list[dict[str, str]] = []
        for bean in beans:
            entries = cls._parse_entries(bean.get("unresolved"))
            if not entries:
                continue
            remaining: list[dict[str, Any]] = []
            for entry in entries:
                target = cls._match(entry, bean["id"], index, by_id)
                if target is None:
                    remaining.append(entry)
                else:
                    injects.append(
                        {
                            "from": bean["id"],
                            "to": target,
                            "via": entry.get("via") or "autowired",
                        }
                    )
            if len(remaining) != len(entries):
                updates.append({"id": bean["id"], "unresolved_injections": json.dumps(remaining)})
        return _Assembled(injects, updates)

    @classmethod
    def _match(
        cls,
        entry: dict[str, Any],
        source_id: str,
        index: dict[str, set[str]],
        by_id: dict[str, dict[str, Any]],
    ) -> str | None:
        element = entry.get("type")
        if not element:
            return None  # XML `ref`-keyed ambiguities don't get better with more beans
        candidates = set(index.get(element, set()))
        candidates |= set(index.get(cls._simple_name(element), set()))
        candidates.discard(source_id)
        qualifier = entry.get("qualifier") or ""
        if qualifier:
            candidates = {cid for cid in candidates if by_id.get(cid, {}).get("name") == qualifier}
        return next(iter(candidates)) if len(candidates) == 1 else None

    @staticmethod
    def _parse_entries(raw: Any) -> list[dict[str, Any]]:
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []

    @staticmethod
    def _simple_name(qualified_name: str | None) -> str:
        if not qualified_name:
            return ""
        tail = qualified_name.rsplit(".", 1)[-1].rsplit("#", 1)[-1]
        return tail.split("<", 1)[0].strip()

    @staticmethod
    def _decapitalize(name: str) -> str:
        if len(name) >= 2 and name[1].isupper():  # `URLRepository` → stays as-is
            return name
        return name[:1].lower() + name[1:]
