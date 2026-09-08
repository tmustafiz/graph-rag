import logging
import re
from typing import Any, LiteralString, NamedTuple, cast

from neo4j import Driver, ManagedTransaction

logger = logging.getLogger(__name__)

_OUTBOUND = """
MATCH (h:HttpEndpoint)
WHERE h.outbound = true
RETURN h.id AS id, h.http_method AS method, h.path AS path
"""

_INBOUND = """
MATCH (h:HttpEndpoint)
WHERE coalesce(h.outbound, false) = false
RETURN h.id AS id, h.http_method AS method, h.path AS path
"""

_CLEAR_RESOLVES_TO = "MATCH (:HttpEndpoint)-[r:RESOLVES_TO]->() DELETE r"

_MERGE_RESOLVES_TO = """
UNWIND $pairs AS pair
MATCH (o:HttpEndpoint {id: pair.from})
MATCH (i:HttpEndpoint {id: pair.to})
MERGE (o)-[:RESOLVES_TO]->(i)
"""

_PATH_VAR = re.compile(r"\{[^}]*\}")


class _Assembled(NamedTuple):
    resolves_to: list[dict[str, str]]


class ServiceCallResolver:
    """Post-ingest pass that links a declarative HTTP client's outbound
    `HttpEndpoint` to the ingested `@RestController` route it actually calls —
    `(:HttpEndpoint {outbound:true})-[:RESOLVES_TO]->(:HttpEndpoint inbound)` —
    yielding a cross-service call graph when both services are in the graph.

    Match key is `(http_method, path)` with path variables normalized to `{}`
    (`/orders/{id}` == `/orders/{orderId}`) and a trailing slash trimmed. `*`
    on either method matches any. An outbound endpoint with zero or several
    inbound matches is left standalone (no edge).
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def resolve(self) -> dict[str, int]:
        with self._driver.session() as session:
            result = session.execute_write(self._rebuild)
        logger.info("service-call graph resolved: %s", result)
        return result

    @classmethod
    def _rebuild(cls, tx: ManagedTransaction) -> dict[str, int]:
        outbound = [dict(row) for row in tx.run(cast(LiteralString, _OUTBOUND))]
        tx.run(cast(LiteralString, _CLEAR_RESOLVES_TO))
        if not outbound:
            return {"outbound": 0, "resolves_to": 0}
        inbound = [dict(row) for row in tx.run(cast(LiteralString, _INBOUND))]
        assembled = cls._assemble(outbound, inbound)
        if assembled.resolves_to:
            tx.run(cast(LiteralString, _MERGE_RESOLVES_TO), pairs=assembled.resolves_to)
        return {"outbound": len(outbound), "resolves_to": len(assembled.resolves_to)}

    # -- assembly (pure — unit-tested without Neo4j) --

    @classmethod
    def _assemble(cls, outbound: list[dict[str, Any]], inbound: list[dict[str, Any]]) -> _Assembled:
        by_path: dict[str, list[dict[str, Any]]] = {}
        for row in inbound:
            by_path.setdefault(cls._normalize_path(row["path"]), []).append(row)

        pairs: list[dict[str, str]] = []
        for out in outbound:
            candidates = by_path.get(cls._normalize_path(out["path"]), [])
            method = (out.get("method") or "*").upper()
            matched = [
                row
                for row in candidates
                if method == "*" or (row.get("method") or "*").upper() in ("*", method)
            ]
            if len(matched) == 1:
                pairs.append({"from": out["id"], "to": matched[0]["id"]})
        return _Assembled(pairs)

    @staticmethod
    def _normalize_path(path: str | None) -> str:
        text = _PATH_VAR.sub("{}", path or "")
        if len(text) > 1:
            text = text.rstrip("/")
        return text or "/"
