import logging
import re
from typing import Any, LiteralString, cast

from neo4j import Driver
from neo4j.exceptions import ClientError

from graph_rag.ingest.embedders import Embedder

from .cross_encoder_reranker import CrossEncoderReranker
from .models import (
    ArchitectureOutline,
    BeanDetail,
    BeanEdge,
    CodeCentralityResult,
    CodeSearchResult,
    EndpointResult,
    MessageFlowResult,
    ModuleArchitecture,
    NeighborResult,
    OutlineNode,
    PolicyResult,
    RouteResult,
    SearchResult,
    SectionDetail,
    SectionOutlineEntry,
    ServiceCallEndpoint,
    ServiceCallResult,
    SourceInfo,
)
from .query_rewriter import QueryRewriter

logger = logging.getLogger(__name__)

# Lucene query-parser metacharacters. `db.index.fulltext.queryNodes` parses its
# argument as a Lucene query, so an unescaped one of these in a natural-language
# query (a pasted CLI flag, `resource:type`, a path, code) raises a
# ParseException and 500s the whole search.
_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/&|])')


def _escape_lucene(query: str) -> str:
    """Backslash-escape Lucene metacharacters so an arbitrary string is matched
    as literal terms instead of raising a parser error.
    """
    return _LUCENE_SPECIAL.sub(r"\\\1", query)


_VECTOR_SEARCH = """
CALL db.index.vector.queryNodes('chunk_embedding', $k, $vector)
YIELD node AS chunk, score
MATCH (sec:Section)-[:HAS_CHUNK]->(chunk)
MATCH (src:Source)-[:HAS_SECTION]->(sec)
WHERE ($source_type IS NULL OR src.type = $source_type)
  AND ($source_path IS NULL OR src.path = $source_path)
RETURN chunk.id AS chunk_id, chunk.text AS text, chunk.start_page AS start_page,
       chunk.end_page AS end_page, sec.breadcrumb AS breadcrumb,
       src.path AS source_path, src.type AS source_type, score
"""

_FULLTEXT_SEARCH = """
CALL db.index.fulltext.queryNodes('chunk_text_fulltext', $query) YIELD node AS chunk, score
MATCH (sec:Section)-[:HAS_CHUNK]->(chunk)
MATCH (src:Source)-[:HAS_SECTION]->(sec)
WHERE ($source_type IS NULL OR src.type = $source_type)
  AND ($source_path IS NULL OR src.path = $source_path)
RETURN chunk.id AS chunk_id, score
ORDER BY score DESC
LIMIT $k
"""

_GET_SECTION = """
MATCH (sec:Section {id: $section_id})<-[:HAS_SECTION]-(src:Source)
OPTIONAL MATCH (parent:Section)-[:PARENT_OF]->(sec)
OPTIONAL MATCH (sec)-[:PARENT_OF]->(child:Section)
RETURN sec.title AS title, sec.breadcrumb AS breadcrumb, src.path AS source_path,
       parent.id AS parent_id, parent.title AS parent_title,
       [c IN collect(DISTINCT child) | {id: c.id, title: c.title}] AS children
"""

_GET_SECTION_CHUNKS = """
MATCH (:Section {id: $section_id})-[:HAS_CHUNK]->(chunk:Chunk)
RETURN chunk.text AS text
ORDER BY chunk.order
"""

_LIST_SOURCES = """
MATCH (src:Source)
RETURN src.path AS path, src.type AS source_type,
       src.ingested_at AS ingested_at, src.version AS version
ORDER BY src.path
"""

_FIND_POLICIES_FOR = """
MATCH (p:PolicyRule)-[:APPLIES_TO]->(:Concept {name: $resource_type})
OPTIONAL MATCH (p)-[:APPLIES_TO]->(other:Concept)
RETURN p.id AS id, p.name AS name, p.category AS category, p.severity AS severity,
       p.guideline AS guideline, p.provider AS provider, p.file_path AS source_path,
       collect(DISTINCT other.name) AS resource_types
ORDER BY p.id
"""

# `n` is matched by whichever unique key its label actually uses (Source.path,
# Section/Chunk/PolicyRule/AgentMemory.id, CodeEntity.qualified_name, Concept.name) —
# a full node scan, but this is a local dev/agent tool, not a high-scale service.
_GET_NEIGHBORS_OUTGOING = """
MATCH (n)-[r]->(m)
WHERE (n.id = $node_id OR n.qualified_name = $node_id OR n.path = $node_id OR n.name = $node_id)
  AND ($rel_types IS NULL OR type(r) IN $rel_types)
RETURN type(r) AS relationship_type, labels(m)[0] AS node_label,
       coalesce(m.id, m.qualified_name, m.path, m.name) AS node_key,
       coalesce(m.title, m.name, m.path, m.key, m.embed_text,
                left(m.content, 100), left(m.text, 100)) AS summary
"""

_GET_NEIGHBORS_INCOMING = """
MATCH (n)<-[r]-(m)
WHERE (n.id = $node_id OR n.qualified_name = $node_id OR n.path = $node_id OR n.name = $node_id)
  AND ($rel_types IS NULL OR type(r) IN $rel_types)
RETURN type(r) AS relationship_type, labels(m)[0] AS node_label,
       coalesce(m.id, m.qualified_name, m.path, m.name) AS node_key,
       coalesce(m.title, m.name, m.path, m.key, m.embed_text,
                left(m.content, 100), left(m.text, 100)) AS summary
"""

_GET_OUTLINE = """
MATCH (src:Source {path: $source_path})-[:HAS_SECTION]->(sec:Section)
OPTIONAL MATCH (parent:Section)-[:PARENT_OF]->(sec)
RETURN sec.id AS id, sec.title AS title, sec.order AS order, parent.id AS parent_id
ORDER BY sec.order
"""

_GET_CITATION = """
MATCH (chunk:Chunk {id: $chunk_id})<-[:HAS_CHUNK]-(sec:Section)<-[:HAS_SECTION]-(src:Source)
RETURN sec.breadcrumb AS breadcrumb, src.path AS source_path,
       chunk.start_page AS start_page, chunk.end_page AS end_page
"""

_GET_CENTRAL_CODE_ENTITIES = """
MATCH (e:CodeEntity)
WHERE e.pagerank IS NOT NULL AND e.name IS NOT NULL
RETURN e.qualified_name AS qualified_name, e.name AS name, e.kind AS kind,
       e.file_path AS file_path, e.pagerank AS pagerank
ORDER BY e.pagerank DESC
LIMIT $top_k
"""

# Optional graph filters for `search_code`, behind `$x IS NULL OR …` guards so
# an unset filter pays only a null check. Used by `_FILTERED_CODE_KEYS` to
# resolve the matching `qualified_name` set before the hybrid search runs.
# `stereotype` matches a Spring `Bean.stereotype` (via `IS_BEAN`) or a bare
# type-level `@Annotation` name; `annotation` matches an `Annotation` simple
# name or FQN anywhere on the entity; `module` matches the owning
# `Module.artifact` or a path suffix.
_CODE_FILTERS = """
WHERE ($stereotype IS NULL
       OR (e)-[:IS_BEAN]->(:Bean {stereotype: $stereotype})
       OR EXISTS {
         MATCH (e)-[:ANNOTATED_WITH]->(sa:Annotation {target: 'type'})
         WHERE sa.name = $stereotype
       })
  AND ($annotation IS NULL OR EXISTS {
         MATCH (e)-[:ANNOTATED_WITH]->(aa:Annotation)
         WHERE aa.name = $annotation OR aa.fqn = $annotation
       })
  AND ($module IS NULL OR EXISTS {
         MATCH (ms:Source)-[:DEFINES]->(e)
         MATCH (ms)-[:IN_MODULE]->(mm:Module)
         WHERE mm.artifact = $module OR mm.path = $module
               OR mm.path ENDS WITH ('/' + $module)
       })
  AND ($route IS NULL OR EXISTS {
         MATCH (:Route {route_id: $route})-[:STEP]->(:CamelStep)-[:INVOKES]->(e)
       })
  AND ($endpoint IS NULL OR EXISTS {
         MATCH (he:HttpEndpoint)-[:HANDLED_BY]->(e)
         WHERE he.path =~ $endpoint
       })
  AND ($listens_to IS NULL
       OR EXISTS {
         MATCH (le:EventType)-[:CONSUMED_BY]->(e)
         WHERE le.fqn = $listens_to OR le.simple_name = $listens_to
       }
       OR EXISTS { MATCH (ld:Destination {name: $listens_to})-[:CONSUMED_BY]->(e) }
       OR EXISTS {
         MATCH (e)-[:CONTAINS]->(lm:CodeEntity)
         MATCH (le2:EventType)-[:CONSUMED_BY]->(lm)
         WHERE le2.fqn = $listens_to OR le2.simple_name = $listens_to
       }
       OR EXISTS {
         MATCH (e)-[:CONTAINS]->(lm2:CodeEntity)
         MATCH (:Destination {name: $listens_to})-[:CONSUMED_BY]->(lm2)
       })
  AND ($behavior IS NULL
       OR $behavior IN coalesce(e.behaviors, [])
       OR EXISTS {
         MATCH (e)-[:CONTAINS]->(bm:CodeEntity)
         WHERE $behavior IN coalesce(bm.behaviors, [])
       })
"""

# `search_code`'s graph filters resolve an allow-set of `qualified_name`s up
# front (see `_FILTERED_CODE_KEYS`); the ANN / full-text passes below stay
# unfiltered and are intersected with that set in Python. Filtering inside the
# index call would only see the `$k` embedding-nearest rows, so a filter that
# excludes all of them would silently return nothing even when matches exist
# (#117).
_FILTERED_CODE_KEYS = f"""
MATCH (e:CodeEntity)
{_CODE_FILTERS}
RETURN e.qualified_name AS qualified_name
"""

_VECTOR_SEARCH_CODE = """
CALL db.index.vector.queryNodes('code_entity_embedding', $k, $vector)
YIELD node AS e, score
RETURN e.qualified_name AS qualified_name, e.name AS name, e.kind AS kind,
       e.language AS language,
       e.docstring AS docstring, e.signature AS signature, e.file_path AS file_path,
       e.start_line AS start_line, e.end_line AS end_line, score
"""

_FULLTEXT_SEARCH_CODE = """
CALL db.index.fulltext.queryNodes('code_entity_text_fulltext', $query) YIELD node AS e, score
RETURN e.qualified_name AS qualified_name, score
ORDER BY score DESC
LIMIT $k
"""

_GET_BEANS_FOR = """
MATCH (b:Bean)
WHERE b.id = $key OR EXISTS { MATCH (:CodeEntity {qualified_name: $key})-[:IS_BEAN]->(b) }
OPTIONAL MATCH (b)-[ri:INJECTS]->(it:Bean)
OPTIONAL MATCH (si:Bean)-[rin:INJECTS]->(b)
OPTIONAL MATCH (b)-[:PRODUCES]->(pt:Bean)
OPTIONAL MATCH (pb:Bean)-[:PRODUCES]->(b)
OPTIONAL MATCH (b)-[:BINDS]->(cp:ConfigProperty)
RETURN b.id AS bean_id, b.name AS name, b.stereotype AS stereotype, b.scope AS scope,
       coalesce(b.primary, false) AS primary, b.bean_type AS bean_type,
       b.defined_in AS defined_in, b.unresolved_injections AS unresolved_injections,
       collect(DISTINCT {bean_id: it.id, name: it.name, stereotype: it.stereotype, via: ri.via})
         AS injects,
       collect(DISTINCT {bean_id: si.id, name: si.name, stereotype: si.stereotype, via: rin.via})
         AS injected_by,
       collect(DISTINCT {bean_id: pt.id, name: pt.name, stereotype: pt.stereotype}) AS produces,
       collect(DISTINCT {bean_id: pb.id, name: pb.name, stereotype: pb.stereotype}) AS produced_by,
       collect(DISTINCT cp.key) AS binds
"""

_GET_ENDPOINTS = """
MATCH (h:HttpEndpoint)
WHERE coalesce(h.outbound, false) = false
  AND ($http_method IS NULL OR h.http_method = $http_method)
  AND ($path_regex IS NULL OR h.path =~ $path_regex)
OPTIONAL MATCH (h)-[:HANDLED_BY]->(handler:CodeEntity)
OPTIONAL MATCH (h)-[:IN_MODULE]->(mod:Module)
WITH h, handler, mod
WHERE $module IS NULL OR mod.artifact = $module OR mod.path ENDS WITH ('/' + $module)
RETURN h.http_method AS http_method, h.path AS path, h.framework AS framework,
       h.produces AS produces, h.consumes AS consumes, h.embed_text AS summary,
       handler.qualified_name AS handler_qualified_name, mod.artifact AS module
ORDER BY h.path, h.http_method
LIMIT $limit
"""

_GET_ROUTES = """
MATCH (r:Route)
OPTIONAL MATCH (r)-[:FROM|TO]->(ep:CamelEndpoint)
WITH r, collect(DISTINCT ep.uri) AS all_uris
WHERE $uri_regex IS NULL OR any(u IN all_uris WHERE u =~ $uri_regex)
OPTIONAL MATCH (r)-[t_to:TO]->(toe:CamelEndpoint)
OPTIONAL MATCH (r)-[:STEP]->(step:CamelStep)
OPTIONAL MATCH (step)-[:INVOKES]->(inv:CodeEntity)
OPTIONAL MATCH (rs:Source)-[:DEFINES]->(r)
OPTIONAL MATCH (rs)-[:IN_MODULE]->(mod:Module)
WITH r, rs, mod,
     collect(DISTINCT CASE WHEN NOT coalesce(t_to.conditional, false) THEN toe.uri END) AS to_uris,
     collect(DISTINCT inv.qualified_name) AS invokes,
     collect(DISTINCT {i: step.index, k: step.kind, u: step.uri}) AS raw_steps
WHERE $module IS NULL OR mod.artifact = $module OR mod.path ENDS WITH ('/' + $module)
RETURN r.route_id AS route_id, r.from_uri AS from_uri, r.on_exception AS on_exception,
       [u IN to_uris WHERE u IS NOT NULL] AS to_uris,
       [q IN invokes WHERE q IS NOT NULL] AS invokes,
       [s IN raw_steps WHERE s.k IS NOT NULL AND s.i IS NOT NULL] AS raw_steps,
       mod.artifact AS module, rs.path AS source_path
ORDER BY r.route_id
LIMIT $limit
"""

_GET_MESSAGE_FLOWS = """
MATCH (et:EventType)
WHERE et.fqn = $name OR et.simple_name = $name
OPTIONAL MATCH (pub:CodeEntity)-[:PUBLISHES]->(et)
OPTIONAL MATCH (et)-[:CONSUMED_BY]->(con:CodeEntity)
RETURN 'event' AS kind, et.fqn AS name, null AS broker,
       [q IN collect(DISTINCT pub.qualified_name) WHERE q IS NOT NULL] AS publishers,
       [q IN collect(DISTINCT con.qualified_name) WHERE q IS NOT NULL] AS consumers
UNION
MATCH (d:Destination)
WHERE d.name = $name
OPTIONAL MATCH (dp:CodeEntity)-[:PRODUCES_TO]->(d)
OPTIONAL MATCH (d)-[:CONSUMED_BY]->(dc:CodeEntity)
RETURN 'destination' AS kind, d.name AS name, d.broker AS broker,
       [q IN collect(DISTINCT dp.qualified_name) WHERE q IS NOT NULL] AS publishers,
       [q IN collect(DISTINCT dc.qualified_name) WHERE q IS NOT NULL] AS consumers
"""

_GET_SERVICE_CALLS = """
MATCH (e:CodeEntity {qualified_name: $qualified_name})
OPTIONAL MATCH (inh:HttpEndpoint)-[:HANDLED_BY]->(e)
OPTIONAL MATCH (e)-[:CALLS_SERVICE]->(out:HttpEndpoint)
OPTIONAL MATCH (out)-[:RESOLVES_TO]->(:HttpEndpoint)-[:HANDLED_BY]->(th:CodeEntity)
RETURN
  collect(DISTINCT {m: inh.http_method, p: inh.path}) AS inbound,
  collect(DISTINCT {m: out.http_method, p: out.path, svc: out.target_service,
                    th: th.qualified_name}) AS outbound
"""

# The module filter accepts either the exact Maven artifactId or a path suffix
# (`mod.path ENDS WITH '/' + $module`), matching `get_endpoints` / `get_routes` /
# `search_code`; `'unassigned'` stays reachable when no module is passed.
_MODULE_FILTER = (
    "WHERE $module IS NULL OR module = $module "
    "OR (modpath IS NOT NULL AND modpath ENDS WITH ('/' + $module))"
)

_GET_ARCHITECTURE_OUTLINE = f"""
MATCH (c:CodeEntity)-[:IS_BEAN]->(b:Bean)
OPTIONAL MATCH (bs:Source)-[:DEFINES]->(c)
OPTIONAL MATCH (bs)-[:IN_MODULE]->(bm:Module)
WITH coalesce(bm.artifact, 'unassigned') AS module, bm.path AS modpath, 'bean' AS cat,
     b.name + ' [' + coalesce(b.stereotype, '?') + ']' AS item
{_MODULE_FILTER}
RETURN module, cat, item
UNION
MATCH (h:HttpEndpoint)
WHERE coalesce(h.outbound, false) = false
OPTIONAL MATCH (h)-[:IN_MODULE]->(hm:Module)
WITH coalesce(hm.artifact, 'unassigned') AS module, hm.path AS modpath, 'endpoint' AS cat,
     h.http_method + ' ' + h.path AS item
{_MODULE_FILTER}
RETURN module, cat, item
UNION
MATCH (r:Route)
OPTIONAL MATCH (rs:Source)-[:DEFINES]->(r)
OPTIONAL MATCH (rs)-[:IN_MODULE]->(rm:Module)
WITH coalesce(rm.artifact, 'unassigned') AS module, rm.path AS modpath, 'route' AS cat,
     r.route_id + ': ' + r.from_uri AS item
{_MODULE_FILTER}
RETURN module, cat, item
UNION
MATCH (src)-[:CONSUMED_BY]->(lc:CodeEntity)
WHERE src:EventType OR src:Destination
OPTIONAL MATCH (ls:Source)-[:DEFINES]->(lc)
OPTIONAL MATCH (ls)-[:IN_MODULE]->(lm:Module)
WITH coalesce(lm.artifact, 'unassigned') AS module, lm.path AS modpath, 'listener' AS cat,
     lc.qualified_name + ' <- ' + coalesce(src.fqn, src.name) AS item
{_MODULE_FILTER}
RETURN module, cat, item
UNION
MATCH (sc:CodeEntity)-[:HAS_BEHAVIOR {{marker: 'scheduled'}}]->(smk:BehaviorMarker)
OPTIONAL MATCH (ss:Source)-[:DEFINES]->(sc)
OPTIONAL MATCH (ss)-[:IN_MODULE]->(sm:Module)
WITH coalesce(sm.artifact, 'unassigned') AS module, sm.path AS modpath, 'scheduled' AS cat,
     sc.qualified_name + coalesce(' (' + smk.attributes + ')', '') AS item
{_MODULE_FILTER}
RETURN module, cat, item
"""

_GET_BEAN_FRAMEWORK_CONTEXT = """
MATCH (c:CodeEntity)-[:IS_BEAN]->(:Bean {id: $bean_id})
OPTIONAL MATCH (c)-[:CONTAINS]->(child:CodeEntity)
WITH collect(DISTINCT child) + collect(DISTINCT c) AS members
UNWIND members AS mem
OPTIONAL MATCH (mem)-[:PUBLISHES]->(pet:EventType)
OPTIONAL MATCH (let:EventType)-[:CONSUMED_BY]->(mem)
OPTIONAL MATCH (ld:Destination)-[:CONSUMED_BY]->(mem)
OPTIONAL MATCH (mem)-[:CALLS_SERVICE]->(oe:HttpEndpoint)
OPTIONAL MATCH (rt:Route)-[:STEP]->(:CamelStep)-[:INVOKES]->(mem)
RETURN
  [q IN collect(DISTINCT pet.fqn) WHERE q IS NOT NULL] AS publishes,
  [q IN collect(DISTINCT coalesce(let.fqn, ld.name)) WHERE q IS NOT NULL] AS listens_to,
  [q IN collect(DISTINCT
     oe.http_method + ' ' + oe.path + ' -> ' + coalesce(oe.target_service, '?'))
   WHERE q IS NOT NULL] AS calls_services,
  [q IN collect(DISTINCT rt.route_id) WHERE q IS NOT NULL] AS invoked_by_routes,
  [b IN collect(DISTINCT mem.behaviors) WHERE b IS NOT NULL] AS behavior_lists
"""

_VECTOR_SEARCH_POLICY = """
CALL db.index.vector.queryNodes('policy_rule_embedding', $k, $vector)
YIELD node AS p, score
OPTIONAL MATCH (p)-[:APPLIES_TO]->(c:Concept)
RETURN p.id AS id, p.name AS name, p.category AS category, p.severity AS severity,
       p.guideline AS guideline, p.provider AS provider, p.file_path AS source_path,
       collect(DISTINCT c.name) AS resource_types, score
"""

_FULLTEXT_SEARCH_POLICY = """
CALL db.index.fulltext.queryNodes('policy_rule_text_fulltext', $query) YIELD node AS p, score
RETURN p.id AS id, score
ORDER BY score DESC
LIMIT $k
"""

VECTOR_WEIGHT = 0.7
FULLTEXT_WEIGHT = 0.3
CANDIDATE_MULTIPLIER = 4
# Upper bound on how far `search_code` over-fetches from the vector / full-text
# indexes when a graph filter is set, so a large filtered set still gets a
# representative slice ranked (#117) without an unbounded scan.
MAX_CODE_CANDIDATE_K = 1000


class Retriever:
    """Read-only Neo4j queries backing the MCP server's tools."""

    def __init__(
        self,
        driver: Driver,
        embedder: Embedder,
        reranker: CrossEncoderReranker | None = None,
        query_rewriter: QueryRewriter | None = None,
    ) -> None:
        self._driver = driver
        self._embedder = embedder
        self._reranker = reranker
        self._query_rewriter = query_rewriter

    def _search_queries(self, query: str) -> list[str]:
        """The query strings to run hybrid search for: just `query` normally, or
        `query` plus rewritten variants when a `QueryRewriter` is configured.
        """
        if self._query_rewriter is None:
            return [query]
        return self._query_rewriter.rewrite(query)

    @staticmethod
    def _fulltext_scores(
        session: Any, cypher: LiteralString, params: dict[str, Any], id_key: str
    ) -> dict[str, float]:
        """Run one full-text query and return `{id: score}`. A malformed Lucene
        query (despite `_escape_lucene`) degrades to no full-text boost rather
        than failing the search — the vector half still stands.
        """
        try:
            return {row[id_key]: row["score"] for row in session.run(cypher, params)}
        except ClientError as exc:
            logger.warning("full-text search skipped for %r: %s", params.get("query"), exc)
            return {}

    def _maybe_rerank(
        self,
        query: str,
        ranked_ids: list[str],
        documents: dict[str, str],
        fused_scores: dict[str, float],
    ) -> tuple[list[str], dict[str, float]]:
        """With a reranker configured, re-score the fused shortlist with the
        cross-encoder and return it ordered by that score (the fused score
        breaks ties, so the hybrid signal still decides otherwise-equal hits),
        alongside `{id: rerank_score}`. Without one, return the fused order
        and an empty rerank-score map.
        """
        if self._reranker is None or not ranked_ids:
            return ranked_ids, {}
        rerank_scores = dict(
            zip(
                ranked_ids,
                self._reranker.rerank(query, [documents[rid] for rid in ranked_ids]),
                strict=True,
            )
        )
        ordered = sorted(
            ranked_ids, key=lambda rid: (rerank_scores[rid], fused_scores[rid]), reverse=True
        )
        return ordered, rerank_scores

    def _prose_candidates(
        self,
        session: Any,
        query: str,
        candidate_k: int,
        source_type: str | None,
        source_path: str | None,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
        """One hybrid-search pass for `search`: `({chunk_id: row}, {chunk_id: fused_score})`."""
        vector = self._embedder.embed([query])[0]
        vector_rows = [
            dict(row)
            for row in session.run(
                cast(LiteralString, _VECTOR_SEARCH),
                k=candidate_k,
                vector=vector,
                source_type=source_type,
                source_path=source_path,
            )
        ]
        fulltext_scores = self._fulltext_scores(
            session,
            cast(LiteralString, _FULLTEXT_SEARCH),
            {
                "query": _escape_lucene(query),
                "k": candidate_k,
                "source_type": source_type,
                "source_path": source_path,
            },
            "chunk_id",
        )
        by_id = {row["chunk_id"]: row for row in vector_rows}
        combined = combine_scores(
            {chunk_id: row["score"] for chunk_id, row in by_id.items()}, fulltext_scores
        )
        return by_id, combined

    def search(
        self,
        query: str,
        top_k: int = 5,
        source_type: str | None = None,
        source_path: str | None = None,
    ) -> list[SearchResult]:
        candidate_k = top_k * CANDIDATE_MULTIPLIER
        by_id: dict[str, dict[str, Any]] = {}
        combined_scores: dict[str, float] = {}
        with self._driver.session() as session:
            for variant in self._search_queries(query):
                rows, scores = self._prose_candidates(
                    session, variant, candidate_k, source_type, source_path
                )
                by_id.update(rows)
                _merge_keeping_max(combined_scores, scores)

        ranked_ids = sorted(combined_scores, key=lambda cid: combined_scores[cid], reverse=True)
        ranked_ids, rerank_scores = self._maybe_rerank(
            query,
            ranked_ids,
            {cid: _prose_document(by_id[cid]) for cid in ranked_ids},
            combined_scores,
        )
        return [
            SearchResult(
                chunk_id=cid,
                text=by_id[cid]["text"],
                breadcrumb=by_id[cid]["breadcrumb"],
                source_path=by_id[cid]["source_path"],
                source_type=by_id[cid]["source_type"],
                start_page=by_id[cid]["start_page"],
                end_page=by_id[cid]["end_page"],
                score=combined_scores[cid],
                rerank_score=rerank_scores.get(cid),
            )
            for cid in ranked_ids[:top_k]
        ]

    def get_section(self, section_id: str, max_chars: int = 8000) -> SectionDetail | None:
        with self._driver.session() as session:
            record = session.run(cast(LiteralString, _GET_SECTION), section_id=section_id).single()
            if record is None:
                return None
            chunk_rows = session.run(
                cast(LiteralString, _GET_SECTION_CHUNKS), section_id=section_id
            )
            text = "\n\n".join(row["text"] for row in chunk_rows)

        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]

        parent = (
            SectionOutlineEntry(id=record["parent_id"], title=record["parent_title"])
            if record["parent_id"] is not None
            else None
        )
        children = [SectionOutlineEntry(id=c["id"], title=c["title"]) for c in record["children"]]
        return SectionDetail(
            id=section_id,
            title=record["title"],
            breadcrumb=record["breadcrumb"],
            source_path=record["source_path"],
            text=text,
            truncated=truncated,
            parent=parent,
            children=children,
        )

    def list_sources(self) -> list[SourceInfo]:
        with self._driver.session() as session:
            return [
                SourceInfo(
                    path=row["path"],
                    source_type=row["source_type"],
                    ingested_at=row["ingested_at"],
                    version=row["version"],
                )
                for row in session.run(cast(LiteralString, _LIST_SOURCES))
            ]

    def find_policies_for(self, resource_type: str) -> list[PolicyResult]:
        """Exact-match graph traversal: policies whose `APPLIES_TO` edge names
        `resource_type` precisely (e.g. `aws_db_instance`). No fuzzy fallback —
        an empty result means either no policy applies, or the exact spelling
        is off; try `search_policies` with a natural-language description
        instead of guessing variants.
        """
        with self._driver.session() as session:
            rows = session.run(cast(LiteralString, _FIND_POLICIES_FOR), resource_type=resource_type)
            return [
                PolicyResult(
                    id=row["id"],
                    name=row["name"],
                    category=row["category"],
                    severity=row["severity"],
                    guideline=row["guideline"],
                    provider=row["provider"],
                    source_path=row["source_path"],
                    resource_types=row["resource_types"],
                )
                for row in rows
            ]

    def get_neighbors(
        self, node_id: str, rel_types: list[str] | None = None
    ) -> list[NeighborResult]:
        """Every node directly connected to `node_id` (matched by whichever
        unique key its label uses), in both relationship directions.
        """
        with self._driver.session() as session:
            outgoing = session.run(
                cast(LiteralString, _GET_NEIGHBORS_OUTGOING),
                {"node_id": node_id, "rel_types": rel_types},
            )
            incoming = session.run(
                cast(LiteralString, _GET_NEIGHBORS_INCOMING),
                {"node_id": node_id, "rel_types": rel_types},
            )
            return [
                *_neighbor_results(outgoing, "outgoing"),
                *_neighbor_results(incoming, "incoming"),
            ]

    def get_outline(self, source_path: str) -> list[OutlineNode]:
        """The section outline (table of contents) for a prose source, as a
        nested tree — lets an agent browse structure without walking
        `get_section` one call at a time.
        """
        with self._driver.session() as session:
            rows = [
                dict(row)
                for row in session.run(cast(LiteralString, _GET_OUTLINE), source_path=source_path)
            ]
        return _build_outline_tree(rows)

    def cite(self, chunk_id: str) -> str | None:
        """A human-readable citation string for a chunk, or `None` if it doesn't exist."""
        with self._driver.session() as session:
            record = session.run(cast(LiteralString, _GET_CITATION), chunk_id=chunk_id).single()
        return None if record is None else _format_citation(dict(record))

    def get_central_code_entities(self, top_k: int = 10) -> list[CodeCentralityResult]:
        """The most central `CodeEntity` nodes by PageRank over the
        `CALLS`/`IMPORTS` graph (see `CentralityAnalyzer` /
        `grag-mcp compute-centrality`) — empty until that's been run at
        least once.
        """
        with self._driver.session() as session:
            rows = session.run(cast(LiteralString, _GET_CENTRAL_CODE_ENTITIES), top_k=top_k)
            return [
                CodeCentralityResult(
                    qualified_name=row["qualified_name"],
                    name=row["name"],
                    kind=row["kind"],
                    file_path=row["file_path"],
                    pagerank=row["pagerank"],
                )
                for row in rows
            ]

    def get_beans_for(self, qualified_name: str) -> BeanDetail | None:
        """The Spring bean for a `CodeEntity.qualified_name` (or a `Bean.id`),
        with its `INJECTS` / `PRODUCES` wiring in both directions and the
        `ConfigProperty` keys it `BINDS`. `None` if no bean matches.
        """
        with self._driver.session() as session:
            record = session.run(cast(LiteralString, _GET_BEANS_FOR), key=qualified_name).single()
            if record is None:
                return None
            row = dict(record)
            context = session.run(
                cast(LiteralString, _GET_BEAN_FRAMEWORK_CONTEXT), bean_id=row["bean_id"]
            ).single()
        context_map: dict[str, Any] = dict(context) if context else {}
        behavior_lists = context_map.get("behavior_lists") or []
        behaviors = sorted({slug for slugs in behavior_lists for slug in slugs})
        return BeanDetail(
            bean_id=row["bean_id"],
            name=row["name"],
            stereotype=row["stereotype"],
            scope=row["scope"],
            primary=bool(row["primary"]),
            bean_type=row["bean_type"],
            defined_in=row["defined_in"],
            injects=_bean_edges(row["injects"]),
            injected_by=_bean_edges(row["injected_by"]),
            produces=_bean_edges(row["produces"]),
            produced_by=_bean_edges(row["produced_by"]),
            binds=[key for key in row["binds"] if key],
            unresolved_injections=row["unresolved_injections"],
            publishes=list(context_map.get("publishes") or []),
            listens_to=list(context_map.get("listens_to") or []),
            calls_services=list(context_map.get("calls_services") or []),
            invoked_by_routes=list(context_map.get("invoked_by_routes") or []),
            behaviors=behaviors,
        )

    def get_endpoints(
        self,
        path_glob: str | None = None,
        http_method: str | None = None,
        module: str | None = None,
        limit: int = 100,
    ) -> list[EndpointResult]:
        """Spring MVC / JAX-RS `HttpEndpoint`s, optionally filtered by a
        `path_glob` (`*` / `?` wildcards; substring match unless pinned with
        `^` / `$`), an exact `http_method` (`GET` / `POST` / … / `EXCEPTION`),
        and/or the owning `Module.artifact`. Ordered by path then method.
        """
        params = {
            "path_regex": _glob_to_regex(path_glob) if path_glob else None,
            "http_method": http_method.upper() if http_method else None,
            "module": module,
            "limit": limit,
        }
        with self._driver.session() as session:
            rows = session.run(cast(LiteralString, _GET_ENDPOINTS), params)
            return [
                EndpointResult(
                    http_method=row["http_method"],
                    path=row["path"],
                    framework=row["framework"],
                    handler_qualified_name=row["handler_qualified_name"],
                    module=row["module"],
                    produces=row["produces"] or [],
                    consumes=row["consumes"] or [],
                    summary=row["summary"],
                )
                for row in rows
            ]

    def get_routes(
        self, uri_glob: str | None = None, module: str | None = None, limit: int = 100
    ) -> list[RouteResult]:
        """Apache Camel routes (`Route` nodes), optionally filtered by a
        `uri_glob` matched against the route's `from` and any `to` endpoint URI
        (`*` / `?`; substring unless pinned with `^` / `$`), and/or the owning
        `Module.artifact`. Each result carries the ordered step list and the
        `CodeEntity`s its `process` / `bean` steps invoke.
        """
        params = {
            "uri_regex": _glob_to_regex(uri_glob) if uri_glob else None,
            "module": module,
            "limit": limit,
        }
        with self._driver.session() as session:
            rows = [dict(row) for row in session.run(cast(LiteralString, _GET_ROUTES), params)]
        return [
            RouteResult(
                route_id=row["route_id"],
                from_uri=row["from_uri"],
                to_uris=row["to_uris"],
                steps=[
                    step["k"] + (f"({step['u']})" if step["u"] else "")
                    for step in sorted(
                        row["raw_steps"],
                        key=lambda step: step["i"] if step["i"] is not None else 0,
                    )
                ],
                invokes=row["invokes"],
                on_exception=row["on_exception"] or [],
                module=row["module"],
                source_path=row["source_path"],
            )
            for row in rows
        ]

    def get_message_flows(self, event_or_topic: str) -> list[MessageFlowResult]:
        """Publisher ↔ consumer flows for an application event type
        (`EventType.fqn` or simple name) or a broker destination
        (`Destination.name` — a Kafka topic / Rabbit queue / …). Returns up to
        two results (one per kind that matches the name).
        """
        with self._driver.session() as session:
            rows = [
                dict(row)
                for row in session.run(cast(LiteralString, _GET_MESSAGE_FLOWS), name=event_or_topic)
            ]
        return [
            MessageFlowResult(
                kind=row["kind"],
                name=row["name"],
                broker=row["broker"],
                publishers=row["publishers"],
                consumers=row["consumers"],
            )
            for row in rows
            if row["name"] and (row["publishers"] or row["consumers"])
        ]

    def get_service_calls(self, qualified_name: str) -> ServiceCallResult:
        """The inbound (`@RestController` routes it handles) and outbound
        (`@FeignClient` / `@HttpExchange` calls it declares, with the ingested
        controller route each resolves to) HTTP edges touching one
        `CodeEntity.qualified_name`.
        """
        with self._driver.session() as session:
            record = session.run(
                cast(LiteralString, _GET_SERVICE_CALLS), qualified_name=qualified_name
            ).single()
        endpoints: list[ServiceCallEndpoint] = []
        if record is not None:
            row = dict(record)
            for inbound in row["inbound"]:
                if inbound.get("m"):
                    endpoints.append(
                        ServiceCallEndpoint(
                            direction="inbound",
                            http_method=inbound["m"],
                            path=inbound["p"],
                        )
                    )
            for outbound in row["outbound"]:
                if outbound.get("m"):
                    endpoints.append(
                        ServiceCallEndpoint(
                            direction="outbound",
                            http_method=outbound["m"],
                            path=outbound["p"],
                            target_service=outbound.get("svc"),
                            resolves_to_handler=outbound.get("th"),
                        )
                    )
        return ServiceCallResult(qualified_name=qualified_name, endpoints=endpoints)

    def get_architecture_outline(self, module: str | None = None) -> ArchitectureOutline:
        """Beans, HTTP endpoints, Camel routes, message listeners, and scheduled
        jobs grouped by Maven/Gradle module (nodes in no module land in an
        `unassigned` bucket). Optionally restricted to one `Module.artifact`.
        """
        with self._driver.session() as session:
            rows = [
                dict(row)
                for row in session.run(
                    cast(LiteralString, _GET_ARCHITECTURE_OUTLINE), module=module
                )
            ]
        by_module: dict[str, ModuleArchitecture] = {}
        bucket = {
            "bean": "beans",
            "endpoint": "endpoints",
            "route": "routes",
            "listener": "listeners",
            "scheduled": "scheduled_jobs",
        }
        for row in rows:
            architecture = by_module.setdefault(
                row["module"], ModuleArchitecture(module=row["module"])
            )
            getattr(architecture, bucket[row["cat"]]).append(row["item"])
        for architecture in by_module.values():
            for field_name in bucket.values():
                getattr(architecture, field_name).sort()
        return ArchitectureOutline(
            modules=sorted(by_module.values(), key=lambda architecture: architecture.module)
        )

    def _code_candidates(
        self,
        session: Any,
        query: str,
        candidate_k: int,
        allowed: set[str] | None,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
        """One hybrid-search pass for `search_code`: `({qualified_name: row}, {qn: score})`.
        When `allowed` is set, both halves are intersected with it *after* the
        index call so the graph filter can't be starved by the `$k` truncation.
        """
        vector = self._embedder.embed([query])[0]
        vector_rows = [
            dict(row)
            for row in session.run(
                cast(LiteralString, _VECTOR_SEARCH_CODE),
                k=candidate_k,
                vector=vector,
            )
        ]
        fulltext_scores = self._fulltext_scores(
            session,
            cast(LiteralString, _FULLTEXT_SEARCH_CODE),
            {"query": _escape_lucene(query), "k": candidate_k},
            "qualified_name",
        )
        if allowed is not None:
            vector_rows = [row for row in vector_rows if row["qualified_name"] in allowed]
            fulltext_scores = {qn: score for qn, score in fulltext_scores.items() if qn in allowed}
        by_id = {row["qualified_name"]: row for row in vector_rows}
        combined = combine_scores({qn: row["score"] for qn, row in by_id.items()}, fulltext_scores)
        return by_id, combined

    def _filtered_code_keys(self, filters: dict[str, str | None]) -> set[str]:
        """The `qualified_name`s matching the `search_code` graph filters,
        resolved on the graph alone (no embedding) so the ANN pass can be
        intersected against the full matching set rather than pre-truncated.
        """
        with self._driver.session() as session:
            return {
                row["qualified_name"]
                for row in session.run(
                    cast(LiteralString, _FILTERED_CODE_KEYS),
                    stereotype=filters["stereotype"],
                    annotation=filters["annotation"],
                    module=filters["module"],
                    route=filters["route"],
                    endpoint=filters["endpoint"],
                    listens_to=filters["listens_to"],
                    behavior=filters["behavior"],
                )
            }

    def search_code(
        self,
        query: str,
        top_k: int = 5,
        stereotype: str | None = None,
        annotation: str | None = None,
        module: str | None = None,
        route: str | None = None,
        endpoint: str | None = None,
        listens_to: str | None = None,
        behavior: str | None = None,
    ) -> list[CodeSearchResult]:
        """Hybrid (vector + full-text) search over `CodeEntity` nodes —
        the code-search complement to `search` (which covers prose chunks only).
        Optional filters narrow the hits to the Spring / Java-framework graph:
        `stereotype` / `annotation` / `module`, plus `route` (a `Route.route_id`
        whose steps invoke the entity), `endpoint` (a path glob a handler on the
        entity serves), `listens_to` (an `EventType` fqn/simple or `Destination`
        name the entity — or a method it contains — consumes), and `behavior`
        (`transactional` / `scheduled` / `async` / `retryable` / `cacheable` /
        `pre_authorize` / …).
        """
        filters: dict[str, str | None] = {
            "stereotype": stereotype,
            "annotation": annotation,
            "module": module,
            "route": route,
            "endpoint": _glob_to_regex(endpoint) if endpoint else None,
            "listens_to": listens_to,
            "behavior": behavior,
        }
        candidate_k = top_k * CANDIDATE_MULTIPLIER
        allowed: set[str] | None = None
        if any(value is not None for value in filters.values()):
            allowed = self._filtered_code_keys(filters)
            if not allowed:
                return []
            # over-fetch so the index truncation still reaches enough of the
            # (usually small) filtered set to rank it properly (#117)
            candidate_k = min(len(allowed) + candidate_k, MAX_CODE_CANDIDATE_K)

        by_id: dict[str, dict[str, Any]] = {}
        combined_scores: dict[str, float] = {}
        with self._driver.session() as session:
            for variant in self._search_queries(query):
                rows, scores = self._code_candidates(session, variant, candidate_k, allowed)
                by_id.update(rows)
                _merge_keeping_max(combined_scores, scores)

        ranked_ids = sorted(combined_scores, key=lambda qn: combined_scores[qn], reverse=True)
        ranked_ids, rerank_scores = self._maybe_rerank(
            query, ranked_ids, {qn: _code_document(by_id[qn]) for qn in ranked_ids}, combined_scores
        )
        return [
            CodeSearchResult(
                qualified_name=qn,
                name=by_id[qn]["name"],
                kind=by_id[qn]["kind"],
                language=by_id[qn].get("language") or "python",
                docstring=by_id[qn]["docstring"],
                signature=by_id[qn]["signature"],
                file_path=by_id[qn]["file_path"],
                start_line=by_id[qn]["start_line"],
                end_line=by_id[qn]["end_line"],
                score=combined_scores[qn],
                rerank_score=rerank_scores.get(qn),
            )
            for qn in ranked_ids[:top_k]
        ]

    def _policy_candidates(
        self, session: Any, query: str, candidate_k: int
    ) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
        """One hybrid-search pass for `search_policies`: `({policy_id: row}, {pid: score})`."""
        vector = self._embedder.embed([query])[0]
        vector_rows = [
            dict(row)
            for row in session.run(
                cast(LiteralString, _VECTOR_SEARCH_POLICY), k=candidate_k, vector=vector
            )
        ]
        fulltext_scores = self._fulltext_scores(
            session,
            cast(LiteralString, _FULLTEXT_SEARCH_POLICY),
            {"query": _escape_lucene(query), "k": candidate_k},
            "id",
        )
        by_id = {row["id"]: row for row in vector_rows}
        combined = combine_scores(
            {pid: row["score"] for pid, row in by_id.items()}, fulltext_scores
        )
        return by_id, combined

    def search_policies(self, query: str, top_k: int = 5) -> list[PolicyResult]:
        """Hybrid (vector + full-text) search over `PolicyRule` content — the
        semantic/fuzzy complement to `find_policies_for`'s exact-match
        traversal, for when the exact Terraform resource type isn't known.
        """
        candidate_k = top_k * CANDIDATE_MULTIPLIER
        by_id: dict[str, dict[str, Any]] = {}
        combined_scores: dict[str, float] = {}
        with self._driver.session() as session:
            for variant in self._search_queries(query):
                rows, scores = self._policy_candidates(session, variant, candidate_k)
                by_id.update(rows)
                _merge_keeping_max(combined_scores, scores)

        ranked_ids = sorted(combined_scores, key=lambda pid: combined_scores[pid], reverse=True)
        ranked_ids, rerank_scores = self._maybe_rerank(
            query,
            ranked_ids,
            {pid: _policy_document(by_id[pid]) for pid in ranked_ids},
            combined_scores,
        )
        return [
            PolicyResult(
                id=pid,
                name=by_id[pid]["name"],
                category=by_id[pid]["category"],
                severity=by_id[pid]["severity"],
                guideline=by_id[pid]["guideline"],
                provider=by_id[pid]["provider"],
                source_path=by_id[pid]["source_path"],
                resource_types=by_id[pid]["resource_types"],
                score=combined_scores[pid],
                rerank_score=rerank_scores.get(pid),
            )
            for pid in ranked_ids[:top_k]
        ]


def _merge_keeping_max(into: dict[str, float], additions: dict[str, float]) -> None:
    """Fold one query variant's fused scores into the running best-per-id map,
    in place — a hit keeps its highest fused score across all rewritten queries,
    so a chunk that only a sub-query surfaces still competes on that score.
    """
    for key, score in additions.items():
        if score > into.get(key, float("-inf")):
            into[key] = score


def combine_scores(
    vector_scores: dict[str, float], fulltext_scores: dict[str, float]
) -> dict[str, float]:
    """Blend min-max-normalized vector similarity with an optional full-text boost."""
    vector_norm = _min_max_normalize(vector_scores)
    fulltext_norm = _min_max_normalize(fulltext_scores)
    return {
        chunk_id: VECTOR_WEIGHT * score + FULLTEXT_WEIGHT * fulltext_norm.get(chunk_id, 0.0)
        for chunk_id, score in vector_norm.items()
    }


def _prose_document(row: dict[str, Any]) -> str:
    """The text a cross-encoder scores a prose hit against. The section
    breadcrumb is prepended so the reranker sees the structural context that
    hybrid search gets from the graph, not just the bare chunk body.
    """
    return f"{row['breadcrumb']}\n\n{row['text']}"


def _code_document(row: dict[str, Any]) -> str:
    """The text a cross-encoder scores a code hit against — name, signature, docstring."""
    return " ".join(part for part in (row["name"], row["signature"], row["docstring"]) if part)


def _policy_document(row: dict[str, Any]) -> str:
    """The text a cross-encoder scores a policy hit against — name and guideline."""
    return " ".join(part for part in (row["name"], row["guideline"]) if part)


def _min_max_normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    if high == low:
        return dict.fromkeys(scores, 1.0)
    return {chunk_id: (score - low) / (high - low) for chunk_id, score in scores.items()}


def _bean_edges(rows: list[dict[str, Any]] | None) -> list[BeanEdge]:
    """Drop the all-null placeholder map a Cypher `collect(DISTINCT {…})` emits
    when its `OPTIONAL MATCH` found nothing, and shape the rest as `BeanEdge`s.
    """
    return [
        BeanEdge(
            bean_id=row["bean_id"],
            name=row.get("name") or row["bean_id"],
            stereotype=row.get("stereotype"),
            via=row.get("via"),
        )
        for row in (rows or [])
        if row and row.get("bean_id")
    ]


def _glob_to_regex(glob: str) -> str:
    """A shell-style `path_glob` (`*` = any run, `?` = one char) as a Neo4j
    `=~` regex. Neo4j anchors `=~` whole-string, so each end that the caller
    hasn't pinned with `^` / `$` is padded with `.*` — a bare fragment like
    `orders` then matches any path that contains it. Every other metacharacter
    is escaped.
    """
    anchored_start = glob.startswith("^")
    anchored_end = glob.endswith("$")
    core = glob[1:] if anchored_start else glob
    core = core[:-1] if anchored_end else core
    body = "".join(
        ".*" if char == "*" else "." if char == "?" else re.escape(char) for char in core
    )
    prefix = "" if anchored_start or body.startswith(".*") else ".*"
    suffix = "" if anchored_end or body.endswith(".*") else ".*"
    return prefix + body + suffix


def _neighbor_results(rows: Any, direction: str) -> list[NeighborResult]:
    return [
        NeighborResult(
            relationship_type=row["relationship_type"],
            direction=direction,
            node_label=row["node_label"],
            node_key=row["node_key"],
            summary=row["summary"],
        )
        for row in rows
    ]


def _build_outline_tree(rows: list[dict]) -> list[OutlineNode]:
    """Reassembles flat `(id, title, parent_id)` rows (ordered by `order`) into
    a nested `OutlineNode` tree — rows are expected in parent-before-or-after-
    child order, so a two-pass build (create all, then link) handles either.
    """
    nodes = {row["id"]: OutlineNode(id=row["id"], title=row["title"]) for row in rows}
    roots: list[OutlineNode] = []
    for row in rows:
        node = nodes[row["id"]]
        parent_id = row["parent_id"]
        if parent_id is None:
            roots.append(node)
        else:
            nodes[parent_id].children.append(node)
    return roots


def _format_citation(row: dict) -> str:
    citation = f"{row['source_path']} — {row['breadcrumb']}"
    start_page, end_page = row["start_page"], row["end_page"]
    if start_page is not None:
        pages = f"p. {start_page}" if start_page == end_page else f"pp. {start_page}–{end_page}"
        citation += f" ({pages})"
    return citation
