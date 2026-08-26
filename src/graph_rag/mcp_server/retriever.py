from typing import Any, LiteralString, cast

from neo4j import Driver

from graph_rag.ingest.embedders import Embedder

from .models import (
    CodeCentralityResult,
    CodeSearchResult,
    NeighborResult,
    OutlineNode,
    PolicyResult,
    SearchResult,
    SectionDetail,
    SectionOutlineEntry,
    SourceInfo,
)

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
       coalesce(m.title, m.name, m.path, left(m.content, 100), left(m.text, 100)) AS summary
"""

_GET_NEIGHBORS_INCOMING = """
MATCH (n)<-[r]-(m)
WHERE (n.id = $node_id OR n.qualified_name = $node_id OR n.path = $node_id OR n.name = $node_id)
  AND ($rel_types IS NULL OR type(r) IN $rel_types)
RETURN type(r) AS relationship_type, labels(m)[0] AS node_label,
       coalesce(m.id, m.qualified_name, m.path, m.name) AS node_key,
       coalesce(m.title, m.name, m.path, left(m.content, 100), left(m.text, 100)) AS summary
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

_VECTOR_SEARCH_CODE = """
CALL db.index.vector.queryNodes('code_entity_embedding', $k, $vector)
YIELD node AS e, score
RETURN e.qualified_name AS qualified_name, e.name AS name, e.kind AS kind,
       e.docstring AS docstring, e.signature AS signature, e.file_path AS file_path,
       e.start_line AS start_line, e.end_line AS end_line, score
"""

_FULLTEXT_SEARCH_CODE = """
CALL db.index.fulltext.queryNodes('code_entity_text_fulltext', $query) YIELD node AS e, score
RETURN e.qualified_name AS qualified_name, score
ORDER BY score DESC
LIMIT $k
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


class Retriever:
    """Read-only Neo4j queries backing the MCP server's tools."""

    def __init__(self, driver: Driver, embedder: Embedder) -> None:
        self._driver = driver
        self._embedder = embedder

    def search(
        self,
        query: str,
        top_k: int = 5,
        source_type: str | None = None,
        source_path: str | None = None,
    ) -> list[SearchResult]:
        vector = self._embedder.embed([query])[0]
        candidate_k = top_k * CANDIDATE_MULTIPLIER
        with self._driver.session() as session:
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
            fulltext_scores = {
                row["chunk_id"]: row["score"]
                for row in session.run(
                    cast(LiteralString, _FULLTEXT_SEARCH),
                    {
                        "query": query,
                        "k": candidate_k,
                        "source_type": source_type,
                        "source_path": source_path,
                    },
                )
            }

        by_id = {row["chunk_id"]: row for row in vector_rows}
        combined_scores = combine_scores(
            {chunk_id: row["score"] for chunk_id, row in by_id.items()}, fulltext_scores
        )
        ranked_ids = sorted(combined_scores, key=lambda cid: combined_scores[cid], reverse=True)
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
        `graph-rag compute-centrality`) — empty until that's been run at
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

    def search_code(self, query: str, top_k: int = 5) -> list[CodeSearchResult]:
        """Hybrid (vector + full-text) search over `CodeEntity` nodes —
        the code-search complement to `search` (which covers prose chunks only).
        """
        vector = self._embedder.embed([query])[0]
        candidate_k = top_k * CANDIDATE_MULTIPLIER
        with self._driver.session() as session:
            vector_rows = [
                dict(row)
                for row in session.run(
                    cast(LiteralString, _VECTOR_SEARCH_CODE), k=candidate_k, vector=vector
                )
            ]
            fulltext_scores = {
                row["qualified_name"]: row["score"]
                for row in session.run(
                    cast(LiteralString, _FULLTEXT_SEARCH_CODE),
                    {"query": query, "k": candidate_k},
                )
            }

        by_id = {row["qualified_name"]: row for row in vector_rows}
        combined_scores = combine_scores(
            {qn: row["score"] for qn, row in by_id.items()}, fulltext_scores
        )
        ranked_ids = sorted(combined_scores, key=lambda qn: combined_scores[qn], reverse=True)
        return [
            CodeSearchResult(
                qualified_name=qn,
                name=by_id[qn]["name"],
                kind=by_id[qn]["kind"],
                docstring=by_id[qn]["docstring"],
                signature=by_id[qn]["signature"],
                file_path=by_id[qn]["file_path"],
                start_line=by_id[qn]["start_line"],
                end_line=by_id[qn]["end_line"],
                score=combined_scores[qn],
            )
            for qn in ranked_ids[:top_k]
        ]

    def search_policies(self, query: str, top_k: int = 5) -> list[PolicyResult]:
        """Hybrid (vector + full-text) search over `PolicyRule` content — the
        semantic/fuzzy complement to `find_policies_for`'s exact-match
        traversal, for when the exact Terraform resource type isn't known.
        """
        vector = self._embedder.embed([query])[0]
        candidate_k = top_k * CANDIDATE_MULTIPLIER
        with self._driver.session() as session:
            vector_rows = [
                dict(row)
                for row in session.run(
                    cast(LiteralString, _VECTOR_SEARCH_POLICY), k=candidate_k, vector=vector
                )
            ]
            fulltext_scores = {
                row["id"]: row["score"]
                for row in session.run(
                    cast(LiteralString, _FULLTEXT_SEARCH_POLICY),
                    {"query": query, "k": candidate_k},
                )
            }

        by_id = {row["id"]: row for row in vector_rows}
        combined_scores = combine_scores(
            {pid: row["score"] for pid, row in by_id.items()}, fulltext_scores
        )
        ranked_ids = sorted(combined_scores, key=lambda pid: combined_scores[pid], reverse=True)
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
            )
            for pid in ranked_ids[:top_k]
        ]


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


def _min_max_normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    if high == low:
        return dict.fromkeys(scores, 1.0)
    return {chunk_id: (score - low) / (high - low) for chunk_id, score in scores.items()}


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
