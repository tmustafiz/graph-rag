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
]

# Full-text indexes for keyword-side of hybrid (vector + keyword) retrieval.
FULLTEXT_INDEXES: list[str] = [
    "CREATE FULLTEXT INDEX chunk_text_fulltext IF NOT EXISTS "
    "FOR (n:Chunk) ON EACH [n.text]",
    "CREATE FULLTEXT INDEX section_title_fulltext IF NOT EXISTS "
    "FOR (n:Section) ON EACH [n.title]",
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


def apply_schema(driver: Driver) -> list[str]:
    """Create (or verify) all constraints and indexes. Idempotent."""
    statements = [*CONSTRAINTS, *FULLTEXT_INDEXES, vector_index_statement()]
    with driver.session() as session:
        for statement in statements:
            # Statements are fixed, internally-authored DDL (never user
            # input), so this cast is safe.
            session.run(cast(LiteralString, statement))
    return statements
