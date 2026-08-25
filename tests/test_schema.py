from graph_rag.graph.schema import CONSTRAINTS, FULLTEXT_INDEXES, vector_index_statement


def test_vector_index_statement_embeds_dimensions_and_similarity() -> None:
    statement = vector_index_statement(dimensions=384, similarity_function="cosine")
    assert "chunk_embedding" in statement
    assert "`vector.dimensions`: 384" in statement
    assert "`vector.similarity_function`: 'cosine'" in statement


def test_constraints_cover_every_node_type() -> None:
    node_labels = {"Source", "Section", "Chunk", "CodeEntity", "PolicyRule", "Concept"}
    covered = {label for label in node_labels if any(f"FOR (n:{label})" in c for c in CONSTRAINTS)}
    assert covered == node_labels


def test_fulltext_indexes_defined_for_chunk_and_section_text() -> None:
    assert any("Chunk) ON EACH [n.text]" in ix for ix in FULLTEXT_INDEXES)
    assert any("Section) ON EACH [n.title]" in ix for ix in FULLTEXT_INDEXES)
