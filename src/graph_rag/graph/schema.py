from typing import LiteralString, cast

from neo4j import Driver

from graph_rag.settings import settings

# Uniqueness constraints — one per node type that ingestion upserts on.
# See docs/ARCHITECTURE.md for the full node/relationship taxonomy.
CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT source_path IF NOT EXISTS FOR (n:Source) REQUIRE n.path IS UNIQUE",
    "CREATE CONSTRAINT section_id IF NOT EXISTS FOR (n:Section) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT code_entity_qualified_name IF NOT EXISTS "
    "FOR (n:CodeEntity) REQUIRE n.qualified_name IS UNIQUE",
    "CREATE CONSTRAINT policy_rule_id IF NOT EXISTS FOR (n:PolicyRule) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT concept_name IF NOT EXISTS FOR (n:Concept) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT agent_memory_id IF NOT EXISTS FOR (n:AgentMemory) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT db_table_qualified_name IF NOT EXISTS "
    "FOR (n:DbTable) REQUIRE n.qualified_name IS UNIQUE",
    "CREATE CONSTRAINT db_column_qualified_name IF NOT EXISTS "
    "FOR (n:DbColumn) REQUIRE n.qualified_name IS UNIQUE",
    "CREATE CONSTRAINT db_view_qualified_name IF NOT EXISTS "
    "FOR (n:DbView) REQUIRE n.qualified_name IS UNIQUE",
    "CREATE CONSTRAINT db_index_qualified_name IF NOT EXISTS "
    "FOR (n:DbIndex) REQUIRE n.qualified_name IS UNIQUE",
    "CREATE CONSTRAINT annotation_id IF NOT EXISTS FOR (n:Annotation) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT config_file_path IF NOT EXISTS FOR (n:ConfigFile) REQUIRE n.path IS UNIQUE",
    "CREATE CONSTRAINT config_property_id IF NOT EXISTS "
    "FOR (n:ConfigProperty) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT module_path IF NOT EXISTS FOR (n:Module) REQUIRE n.path IS UNIQUE",
    "CREATE CONSTRAINT external_artifact_gav IF NOT EXISTS "
    "FOR (n:ExternalArtifact) REQUIRE n.gav IS UNIQUE",
    "CREATE CONSTRAINT bean_id IF NOT EXISTS FOR (n:Bean) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT http_endpoint_id IF NOT EXISTS FOR (n:HttpEndpoint) REQUIRE n.id IS UNIQUE",
]

# Full-text indexes for keyword-side of hybrid (vector + keyword) retrieval.
FULLTEXT_INDEXES: list[str] = [
    "CREATE FULLTEXT INDEX chunk_text_fulltext IF NOT EXISTS FOR (n:Chunk) ON EACH [n.text]",
    "CREATE FULLTEXT INDEX section_title_fulltext IF NOT EXISTS FOR (n:Section) ON EACH [n.title]",
    "CREATE FULLTEXT INDEX code_entity_text_fulltext IF NOT EXISTS "
    "FOR (n:CodeEntity) ON EACH [n.name, n.qualified_name, n.docstring]",
    "CREATE FULLTEXT INDEX policy_rule_text_fulltext IF NOT EXISTS "
    "FOR (n:PolicyRule) ON EACH [n.id, n.name, n.category, n.guideline]",
    "CREATE FULLTEXT INDEX agent_memory_content_fulltext IF NOT EXISTS "
    "FOR (n:AgentMemory) ON EACH [n.content]",
    "CREATE FULLTEXT INDEX db_object_text_fulltext IF NOT EXISTS "
    "FOR (n:DbTable|DbView) ON EACH [n.name, n.qualified_name, n.embed_text]",
    "CREATE FULLTEXT INDEX annotation_name_fulltext IF NOT EXISTS "
    "FOR (n:Annotation) ON EACH [n.name, n.fqn]",
    "CREATE FULLTEXT INDEX config_property_fulltext IF NOT EXISTS "
    "FOR (n:ConfigProperty) ON EACH [n.key, n.value]",
    "CREATE FULLTEXT INDEX module_fulltext IF NOT EXISTS "
    "FOR (n:Module) ON EACH [n.artifact, n.group]",
    "CREATE FULLTEXT INDEX bean_fulltext IF NOT EXISTS "
    "FOR (n:Bean) ON EACH [n.name, n.stereotype, n.bean_type]",
    "CREATE FULLTEXT INDEX http_endpoint_fulltext IF NOT EXISTS "
    "FOR (n:HttpEndpoint) ON EACH [n.path, n.embed_text]",
]

# Range indexes for cheap ordering scans (pruner's recency sweep, centrality ranking).
RANGE_INDEXES: list[str] = [
    "CREATE RANGE INDEX agent_memory_last_accessed IF NOT EXISTS "
    "FOR (n:AgentMemory) ON (n.last_accessed_at)",
    "CREATE RANGE INDEX code_entity_pagerank IF NOT EXISTS FOR (n:CodeEntity) ON (n.pagerank)",
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


def _db_object_vector_index_statement(
    label: str,
    index_name: str,
    dimensions: int,
    similarity_function: str,
) -> str:
    return (
        f"CREATE VECTOR INDEX {index_name} IF NOT EXISTS "
        f"FOR (n:{label}) ON (n.embedding) "
        "OPTIONS {indexConfig: {"
        f"`vector.dimensions`: {dimensions}, "
        f"`vector.similarity_function`: '{similarity_function}'"
        "}}"
    )


def db_table_vector_index_statement(
    dimensions: int = settings.embedding_dimensions,
    similarity_function: str = settings.embedding_similarity_function,
) -> str:
    return _db_object_vector_index_statement(
        "DbTable", "db_table_embedding", dimensions, similarity_function
    )


def db_view_vector_index_statement(
    dimensions: int = settings.embedding_dimensions,
    similarity_function: str = settings.embedding_similarity_function,
) -> str:
    return _db_object_vector_index_statement(
        "DbView", "db_view_embedding", dimensions, similarity_function
    )


def http_endpoint_vector_index_statement(
    dimensions: int = settings.embedding_dimensions,
    similarity_function: str = settings.embedding_similarity_function,
) -> str:
    return (
        "CREATE VECTOR INDEX http_endpoint_embedding IF NOT EXISTS "
        "FOR (n:HttpEndpoint) ON (n.embedding) "
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
        db_table_vector_index_statement(),
        db_view_vector_index_statement(),
        http_endpoint_vector_index_statement(),
    ]
    with driver.session() as session:
        for statement in statements:
            # Statements are fixed, internally-authored DDL (never user
            # input), so this cast is safe.
            session.run(cast(LiteralString, statement))
    return statements
