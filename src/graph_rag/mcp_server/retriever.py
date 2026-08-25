from typing import LiteralString, cast

from neo4j import Driver

from graph_rag.ingest.embedders import Embedder

from .models import PolicyResult, SearchResult, SectionDetail, SectionOutlineEntry, SourceInfo

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

    def get_section(self, section_id: str) -> SectionDetail | None:
        with self._driver.session() as session:
            record = session.run(cast(LiteralString, _GET_SECTION), section_id=section_id).single()
            if record is None:
                return None
            chunk_rows = session.run(
                cast(LiteralString, _GET_SECTION_CHUNKS), section_id=section_id
            )
            text = "\n\n".join(row["text"] for row in chunk_rows)

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
