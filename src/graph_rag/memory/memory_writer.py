from datetime import UTC, datetime
from typing import LiteralString, cast
from uuid import uuid4

from neo4j import Driver, ManagedTransaction

from ..ingest.embedders import Embedder
from .agent_memory import AgentMemory

_MERGE_AGENT_MEMORY = """
MERGE (m:AgentMemory {id: $id})
SET m.content = $content, m.kind = $kind, m.embed_text = $embed_text, m.embedding = $embedding,
    m.created_at = $created_at, m.last_accessed_at = $last_accessed_at,
    m.access_count = $access_count, m.importance = $importance,
    m.archived_at = $archived_at, m.source_session_id = $source_session_id
"""

_MERGE_ABOUT = """
MATCH (m:AgentMemory {id: $memory_id})
MATCH (e:CodeEntity {qualified_name: $qualified_name})
MERGE (m)-[:ABOUT]->(e)
"""

_DELETE_AGENT_MEMORY = """
MATCH (m:AgentMemory {id: $memory_id})
DETACH DELETE m
"""


class MemoryWriter:
    """Upserts `AgentMemory` nodes (`remember`) and removes them (`forget`)."""

    def __init__(self, driver: Driver, embedder: Embedder) -> None:
        self._driver = driver
        self._embedder = embedder

    def remember(
        self,
        content: str,
        kind: str,
        about_qualified_name: str | None = None,
        importance: bool = False,
        source_session_id: str | None = None,
    ) -> AgentMemory:
        """Embeds and upserts an `AgentMemory`, linking `ABOUT` a `CodeEntity`
        when `about_qualified_name` resolves to one.
        """
        now = datetime.now(UTC)
        memory = AgentMemory(
            id=uuid4().hex,
            content=content,
            kind=kind,
            embed_text=content,
            embedding=self._embedder.embed([content])[0],
            created_at=now,
            last_accessed_at=now,
            importance=importance,
            source_session_id=source_session_id,
        )
        with self._driver.session() as session:
            session.execute_write(self._write_memory, memory, about_qualified_name)
        return memory

    def forget(self, memory_id: str) -> None:
        """Explicit, immediate deletion — for corrections that shouldn't wait
        for decay-based pruning.
        """
        with self._driver.session() as session:
            session.execute_write(self._delete_memory, memory_id)

    @staticmethod
    def _write_memory(
        tx: ManagedTransaction, memory: AgentMemory, about_qualified_name: str | None
    ) -> None:
        tx.run(cast(LiteralString, _MERGE_AGENT_MEMORY), **memory.model_dump(mode="json"))
        if about_qualified_name is not None:
            tx.run(
                cast(LiteralString, _MERGE_ABOUT),
                memory_id=memory.id,
                qualified_name=about_qualified_name,
            )

    @staticmethod
    def _delete_memory(tx: ManagedTransaction, memory_id: str) -> None:
        tx.run(cast(LiteralString, _DELETE_AGENT_MEMORY), memory_id=memory_id)
