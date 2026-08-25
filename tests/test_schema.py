from graph_rag.graph.schema import (
    CONSTRAINTS,
    FULLTEXT_INDEXES,
    code_entity_vector_index_statement,
    policy_rule_vector_index_statement,
    vector_index_statement,
)


def test_vector_index_statement_embeds_dimensions_and_similarity() -> None:
    statement = vector_index_statement(dimensions=384, similarity_function="cosine")
    assert "chunk_embedding" in statement
    assert "`vector.dimensions`: 384" in statement
    assert "`vector.similarity_function`: 'cosine'" in statement


def test_code_entity_vector_index_statement_embeds_dimensions_and_similarity() -> None:
    statement = code_entity_vector_index_statement(dimensions=384, similarity_function="cosine")
    assert "code_entity_embedding" in statement
    assert "`vector.dimensions`: 384" in statement
    assert "`vector.similarity_function`: 'cosine'" in statement


def test_constraints_cover_every_node_type() -> None:
    node_labels = {"Source", "Section", "Chunk", "CodeEntity", "PolicyRule", "Concept"}
    covered = {label for label in node_labels if any(f"FOR (n:{label})" in c for c in CONSTRAINTS)}
    assert covered == node_labels


def test_fulltext_indexes_defined_for_chunk_and_section_text() -> None:
    assert any("Chunk) ON EACH [n.text]" in ix for ix in FULLTEXT_INDEXES)
    assert any("Section) ON EACH [n.title]" in ix for ix in FULLTEXT_INDEXES)


def test_fulltext_index_defined_for_code_entity() -> None:
    assert any("CodeEntity) ON EACH" in ix and "n.name" in ix for ix in FULLTEXT_INDEXES)


def test_policy_rule_vector_index_statement_embeds_dimensions_and_similarity() -> None:
    statement = policy_rule_vector_index_statement(dimensions=384, similarity_function="cosine")
    assert "policy_rule_embedding" in statement
    assert "`vector.dimensions`: 384" in statement
    assert "`vector.similarity_function`: 'cosine'" in statement


def test_fulltext_index_defined_for_policy_rule() -> None:
    assert any("PolicyRule) ON EACH" in ix and "n.id" in ix for ix in FULLTEXT_INDEXES)
