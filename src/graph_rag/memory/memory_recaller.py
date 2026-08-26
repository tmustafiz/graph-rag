from datetime import UTC, datetime
from typing import LiteralString, cast

from neo4j import Driver, ManagedTransaction

from ..ingest.embedders import Embedder
from .agent_memory_result import AgentMemoryResult

_VECTOR_SEARCH_MEMORY = """
CALL db.index.vector.queryNodes('agent_memory_embedding', $k, $vector)
YIELD node AS m, score
WHERE m.archived_at IS NULL
RETURN m.id AS id, m.content AS content, m.kind AS kind, m.created_at AS created_at,
       m.importance AS importance, score
"""

_FULLTEXT_SEARCH_MEMORY = """
CALL db.index.fulltext.queryNodes('agent_memory_content_fulltext', $query) YIELD node AS m, score
WHERE m.archived_at IS NULL
RETURN m.id AS id, score
ORDER BY score DESC
LIMIT $k
"""

_TOUCH_MEMORIES = """
UNWIND $ids AS id
MATCH (m:AgentMemory {id: id})
SET m.last_accessed_at = $accessed_at, m.access_count = m.access_count + 1
"""

VECTOR_WEIGHT = 0.7
FULLTEXT_WEIGHT = 0.3
CANDIDATE_MULTIPLIER = 4


class MemoryRecaller:
    """Hybrid (vector + full-text) search over `AgentMemory.content`.

    Every returned hit has its `last_accessed_at`/`access_count` bumped —
    recall reinforces a memory, same as human memory.
    """

    def __init__(self, driver: Driver, embedder: Embedder) -> None:
        self._driver = driver
        self._embedder = embedder

    def recall(self, query: str, top_k: int = 5) -> list[AgentMemoryResult]:
        vector = self._embedder.embed([query])[0]
        candidate_k = top_k * CANDIDATE_MULTIPLIER
        with self._driver.session() as session:
            vector_rows = [
                dict(row)
                for row in session.run(
                    cast(LiteralString, _VECTOR_SEARCH_MEMORY), k=candidate_k, vector=vector
                )
            ]
            fulltext_scores = {
                row["id"]: row["score"]
                for row in session.run(
                    cast(LiteralString, _FULLTEXT_SEARCH_MEMORY),
                    {"query": query, "k": candidate_k},
                )
            }

            by_id = {row["id"]: row for row in vector_rows}
            combined = _combine_scores(
                {mid: row["score"] for mid, row in by_id.items()}, fulltext_scores
            )
            ranked_ids = sorted(combined, key=lambda mid: combined[mid], reverse=True)[:top_k]
            if ranked_ids:
                session.execute_write(self._touch, ranked_ids)

        return [
            AgentMemoryResult(
                id=mid,
                content=by_id[mid]["content"],
                kind=by_id[mid]["kind"],
                created_at=by_id[mid]["created_at"],
                importance=by_id[mid]["importance"],
                score=combined[mid],
            )
            for mid in ranked_ids
        ]

    @staticmethod
    def _touch(tx: ManagedTransaction, ids: list[str]) -> None:
        tx.run(
            cast(LiteralString, _TOUCH_MEMORIES),
            ids=ids,
            accessed_at=datetime.now(UTC).isoformat(),
        )


def _combine_scores(
    vector_scores: dict[str, float], fulltext_scores: dict[str, float]
) -> dict[str, float]:
    """Blend min-max-normalized vector similarity with an optional full-text boost."""
    vector_norm = _min_max_normalize(vector_scores)
    fulltext_norm = _min_max_normalize(fulltext_scores)
    return {
        mid: VECTOR_WEIGHT * score + FULLTEXT_WEIGHT * fulltext_norm.get(mid, 0.0)
        for mid, score in vector_norm.items()
    }


def _min_max_normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    if high == low:
        return dict.fromkeys(scores, 1.0)
    return {mid: (score - low) / (high - low) for mid, score in scores.items()}
