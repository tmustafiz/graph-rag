import logging
import math
import re
from datetime import UTC, datetime
from typing import Any, LiteralString, cast

from neo4j import Driver, ManagedTransaction
from neo4j.exceptions import ClientError

from ..ingest.embedders import Embedder
from .agent_memory_result import AgentMemoryResult

logger = logging.getLogger(__name__)

_VECTOR_SEARCH_MEMORY = """
CALL db.index.vector.queryNodes('agent_memory_embedding', $k, $vector)
YIELD node AS m, score
WHERE m.archived_at IS NULL
  AND ($kind IS NULL OR m.kind = $kind)
  AND ($session_id IS NULL OR m.source_session_id = $session_id)
  AND ($about IS NULL OR m.about_qualified_name = $about)
RETURN m.id AS id, m.content AS content, m.kind AS kind, m.created_at AS created_at,
       m.last_accessed_at AS last_accessed_at, m.access_count AS access_count,
       m.importance AS importance, score
"""

_FULLTEXT_SEARCH_MEMORY = """
CALL db.index.fulltext.queryNodes('agent_memory_content_fulltext', $query) YIELD node AS m, score
WHERE m.archived_at IS NULL
  AND ($kind IS NULL OR m.kind = $kind)
  AND ($session_id IS NULL OR m.source_session_id = $session_id)
  AND ($about IS NULL OR m.about_qualified_name = $about)
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

# Additive boosts on top of the [0, 1] semantic-relevance score. Both are small
# enough that a clearly more relevant memory still wins, but they break ties and
# lift memories the agent has flagged or keeps coming back to.
IMPORTANCE_BOOST = 0.15
REINFORCEMENT_BOOST = 0.15
# `access_count` at which the frequency term saturates, and the half-life-ish
# decay constant for time since last access.
ACCESS_SATURATION = 10.0
RECENCY_TAU_DAYS = 30.0
# A hit is only reinforced (its access clock reset) when the raw cosine
# similarity clears this floor — a weak tail hit surfaced just to fill `top_k`
# shouldn't get its decay reset.
REINFORCE_MIN_SIMILARITY = 0.35

# Lucene query-parser metacharacters — see graph_rag.mcp_server.retriever, which
# carries the same helper for the document indexes. Kept local to avoid a
# memory -> mcp_server import; dedupe into a shared module if a third caller
# appears.
_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/&|])')


def _escape_lucene(query: str) -> str:
    return _LUCENE_SPECIAL.sub(r"\\\1", query)


class MemoryRecaller:
    """Hybrid (vector + full-text) search over `AgentMemory.content`, ranked by
    semantic relevance plus an `importance` boost and a recency/frequency boost.

    A returned hit whose similarity clears `REINFORCE_MIN_SIMILARITY` has its
    `last_accessed_at` / `access_count` bumped — recall reinforces a memory,
    same as human memory.
    """

    def __init__(self, driver: Driver, embedder: Embedder) -> None:
        self._driver = driver
        self._embedder = embedder

    def recall(
        self,
        query: str,
        top_k: int = 5,
        kind: str | None = None,
        about_qualified_name: str | None = None,
        session_id: str | None = None,
    ) -> list[AgentMemoryResult]:
        vector = self._embedder.embed([query])[0]
        candidate_k = top_k * CANDIDATE_MULTIPLIER
        filters = {"kind": kind, "about": about_qualified_name, "session_id": session_id}
        now = datetime.now(UTC)

        with self._driver.session() as session:
            vector_rows = [
                dict(row)
                for row in session.run(
                    cast(LiteralString, _VECTOR_SEARCH_MEMORY),
                    k=candidate_k,
                    vector=vector,
                    **filters,
                )
            ]
            fulltext_scores = self._fulltext_scores(
                session, {"query": _escape_lucene(query), "k": candidate_k, **filters}
            )

            by_id = {row["id"]: row for row in vector_rows}
            relevance = _combine_scores(
                {mid: row["score"] for mid, row in by_id.items()}, fulltext_scores
            )
            final = _final_scores(relevance, by_id, now)
            ranked_ids = sorted(final, key=lambda mid: final[mid], reverse=True)[:top_k]

            to_touch = [
                mid for mid in ranked_ids if by_id[mid]["score"] >= REINFORCE_MIN_SIMILARITY
            ]
            if to_touch:
                session.execute_write(self._touch, to_touch, now)

        return [
            AgentMemoryResult(
                id=mid,
                content=by_id[mid]["content"],
                kind=by_id[mid]["kind"],
                created_at=by_id[mid]["created_at"],
                last_accessed_at=by_id[mid]["last_accessed_at"],
                access_count=by_id[mid]["access_count"],
                importance=by_id[mid]["importance"],
                score=final[mid],
            )
            for mid in ranked_ids
        ]

    @staticmethod
    def _fulltext_scores(session: Any, params: dict[str, Any]) -> dict[str, float]:
        """`{id: score}` for the full-text half. A malformed Lucene query (despite
        `_escape_lucene`, e.g. a bare `AND`) degrades to no full-text signal
        rather than failing the recall — the vector half still stands.
        """
        try:
            return {
                row["id"]: row["score"]
                for row in session.run(cast(LiteralString, _FULLTEXT_SEARCH_MEMORY), params)
            }
        except ClientError as exc:
            logger.warning("full-text recall skipped for %r: %s", params.get("query"), exc)
            return {}

    @staticmethod
    def _touch(tx: ManagedTransaction, ids: list[str], now: datetime) -> None:
        tx.run(cast(LiteralString, _TOUCH_MEMORIES), ids=ids, accessed_at=now.isoformat())


def _combine_scores(
    vector_scores: dict[str, float], fulltext_scores: dict[str, float]
) -> dict[str, float]:
    """Blend min-max-normalized vector similarity with an optional full-text
    boost into a [0, 1] semantic-relevance score.
    """
    vector_norm = _min_max_normalize(vector_scores)
    fulltext_norm = _min_max_normalize(fulltext_scores)
    return {
        mid: VECTOR_WEIGHT * score + FULLTEXT_WEIGHT * fulltext_norm.get(mid, 0.0)
        for mid, score in vector_norm.items()
    }


def _final_scores(
    relevance: dict[str, float], rows: dict[str, dict], now: datetime
) -> dict[str, float]:
    """Relevance plus the `importance` and recency/frequency boosts."""
    return {
        mid: rel
        + (IMPORTANCE_BOOST if rows[mid]["importance"] else 0.0)
        + REINFORCEMENT_BOOST
        * _reinforcement(rows[mid]["access_count"], rows[mid]["last_accessed_at"], now)
        for mid, rel in relevance.items()
    }


def _reinforcement(access_count: int, last_accessed_at: str | datetime, now: datetime) -> float:
    """How reinforced a memory is, in [0, 1]: a saturating function of
    `access_count` decayed by the time since it was last recalled.
    """
    frequency = min(math.log1p(max(access_count, 0)) / math.log1p(ACCESS_SATURATION), 1.0)
    last_accessed = (
        last_accessed_at
        if isinstance(last_accessed_at, datetime)
        else datetime.fromisoformat(last_accessed_at)
    )
    age_days = max((now - last_accessed).total_seconds() / 86400.0, 0.0)
    return frequency * math.exp(-age_days / RECENCY_TAU_DAYS)


def _min_max_normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    if high == low:
        return dict.fromkeys(scores, 1.0)
    return {mid: (score - low) / (high - low) for mid, score in scores.items()}
