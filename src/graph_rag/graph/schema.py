from typing import LiteralString, cast

from neo4j import Driver

from graph_rag.settings import settings

# Uniqueness constraints — one per node type that ingestion upserts on.
# See docs/IMPLEMENTATION_PLAN.md Phase 1 for the full node/relationship taxonomy.
CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT source_path IF NOT EXISTS "
    "FOR (n:Source) REQUIRE n.path IS UNIQUE",
    "CREATE CONSTRAINT section_id IF NOT EXISTS "
    "FOR (n:Section) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS "
    "FOR (n:Chunk) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT code_entity_qualified_name IF NOT EXISTS "
    "FOR (n:CodeEntity) REQUIRE n.qualified_name IS UNIQUE",
    "CREATE CONSTRAINT policy_rule_id IF NOT EXISTS "
    "FOR (n:PolicyRule) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT concept_name IF NOT EXISTS "
    "FOR (n:Concept) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT agent_memory_id IF NOT EXISTS "
    "FOR (n:AgentMemory) REQUIRE n.id IS UNIQUE",
]

# Full-text indexes for keyword-side of hybrid (vector + keyword) retrieval.
FULLTEXT_INDEXES: list[str] = [
    "CREATE FULLTEXT INDEX chunk_text_fulltext IF NOT EXISTS "
    "FOR (n:Chunk) ON EACH [n.text]",
    "CREATE FULLTEXT INDEX section_title_fulltext IF NOT EXISTS "
    "FOR (n:Section) ON EACH [n.title]",
    "CREATE FULLTEXT INDEX code_entity_text_fulltext IF NOT EXISTS "
    "FOR (n:CodeEntity) ON EACH [n.name, n.qualified_name, n.docstring]",
    "CREATE FULLTEXT INDEX policy_rule_text_fulltext IF NOT EXISTS "
    "FOR (n:PolicyRule) ON EACH [n.id, n.name, n.category, n.guideline]",
    "CREATE FULLTEXT INDEX agent_memory_content_fulltext IF NOT EXISTS "
    "FOR (n:AgentMemory) ON EACH [n.content]",
]

# Range index so the pruner's scan over recency stays cheap as memory grows.
RANGE_INDEXES: list[str] = [
    "CREATE RANGE INDEX agent_memory_last_accessed IF NOT EXISTS "
    "FOR (n:AgentMemory) ON (n.last_accessed_at)",
]


def vector_index_statement(
    dimensions: int = settings.embedding_dimensions,
    similarity_function: str = settings.embedding_similarity_function,
) -> str:
    return (
        "CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS "
        "FOR (n:Chunk) ON (n.embedding) "
        "OPTIONS {indexConfig: {"
        f"`vector.dimensions`: {dimensions}, "
        f"`vector.similarity_function`: '{similarity_function}'"
        "}}"
    )


def code_entity_vector_index_statement(
    dimensions: int = settings.embedding_dimensions,
    similarity_function: str = settings.embedding_similarity_function,
) -> str:
    return (
        "CREATE VECTOR INDEX code_entity_embedding IF NOT EXISTS "
        "FOR (n:CodeEntity) ON (n.embedding) "
        "OPTIONS {indexConfig: {"
        f"`vector.dimensions`: {dimensions}, "
        f"`vector.similarity_function`: '{similarity_function}'"
        "}}"
    )


def policy_rule_vector_index_statement(
    dimensions: int = settings.embedding_dimensions,
    similarity_function: str = settings.embedding_similarity_function,
) -> str:
    return (
        "CREATE VECTOR INDEX policy_rule_embedding IF NOT EXISTS "
        "FOR (n:PolicyRule) ON (n.embedding) "
        "OPTIONS {indexConfig: {"
        f"`vector.dimensions`: {dimensions}, "
        f"`vector.similarity_function`: '{similarity_function}'"
        "}}"
    )


def agent_memory_vector_index_statement(
    dimensions: int = settings.embedding_dimensions,
    similarity_function: str = settings.embedding_similarity_function,
) -> str:
    return (
        "CREATE VECTOR INDEX agent_memory_embedding IF NOT EXISTS "
        "FOR (n:AgentMemory) ON (n.embedding) "
        "OPTIONS {indexConfig: {"
        f"`vector.dimensions`: {dimensions}, "
        f"`vector.similarity_function`: '{similarity_function}'"
        "}}"
    )


def apply_schema(driver: Driver) -> list[str]:
    """Create (or verify) all constraints and indexes. Idempotent."""
    statements = [
        *CONSTRAINTS,
        *FULLTEXT_INDEXES,
        *RANGE_INDEXES,
        vector_index_statement(),
        code_entity_vector_index_statement(),
        policy_rule_vector_index_statement(),
        agent_memory_vector_index_statement(),
    ]
    with driver.session() as session:
        for statement in statements:
            # Statements are fixed, internally-authored DDL (never user
            # input), so this cast is safe.
            session.run(cast(LiteralString, statement))
    return statements
