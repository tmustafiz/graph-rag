"""SCIP index ingestion — `ScipReader` (hand-rolled protobuf), `ScipSymbolParser`
(symbol string → qualified_name), and `ScipIngestor._build_documents` (pure —
no embedder / Neo4j).

The fixture `tests/fixtures/tiny_java.scip` is a hand-encoded index for a toy
two-file Java project; regenerate it with `tests/fixtures/build_tiny_scip.py`.
"""

from pathlib import Path

from graph_rag.ingest.models import CodeEntity
from graph_rag.ingest.scip import ScipReader, ScipSymbolParser
from graph_rag.scip_ingestor import ScipIngestor

_FIXTURE = Path(__file__).parent / "fixtures" / "tiny_java.scip"


def _documents():
    return ScipReader.read(_FIXTURE.read_bytes())


def test_reader_decodes_documents_symbols_and_occurrences() -> None:
    documents = {document.relative_path: document for document in _documents()}

    assert set(documents) == {
        "com/acme/OrderService.java",
        "com/acme/OrderRepository.java",
    }
    service = documents["com/acme/OrderService.java"]
    assert service.language == "java"
    assert [symbol.display_name for symbol in service.symbols] == ["OrderService", "submit"]
    call = next(occ for occ in service.occurrences if not occ.is_definition)
    assert call.enclosing_range == [4, 16, 7, 5]


def test_reader_tolerates_garbage_input() -> None:
    assert ScipReader.read(b"") == []
    assert ScipReader.read(b"\xff\xff\xff not protobuf") == []


def test_symbol_string_maps_to_a_readable_qualified_name() -> None:
    prefix = "scip-java maven com.acme 1.0"
    assert ScipSymbolParser.parse(f"{prefix} com/acme/OrderService#") == (
        "com.acme.OrderService",
        "type",
        "OrderService",
    )
    assert ScipSymbolParser.parse(f"{prefix} com/acme/OrderService#submit().") == (
        "com.acme.OrderService.submit",
        "method",
        "submit",
    )
    assert ScipSymbolParser.parse("local 4") is None


def test_build_documents_derives_calls_imports_implements_and_provenance() -> None:
    parsed = {
        document.source.path: document
        for document in ScipIngestor._build_documents(_documents(), None)
    }

    service = parsed["com/acme/OrderService.java"]
    submit = _by_qn(service.code_entities)["com.acme.OrderService.submit"]
    assert submit.kind == "method"
    assert submit.calls == ["com.acme.JpaOrderRepository.save"]  # from enclosing_range
    assert submit.imports == ["com.acme.OrderRepository"]  # is_reference relationship
    assert submit.docstring == "Submits an order."
    assert all(entity.resolution == "scip" for entity in service.code_entities)

    repo = parsed["com/acme/OrderRepository.java"]
    jpa = _by_qn(repo.code_entities)["com.acme.JpaOrderRepository"]
    assert jpa.implements_types == ["com.acme.OrderRepository"]  # is_implementation


def test_root_option_resolves_relative_paths_to_the_static_source_key() -> None:
    parsed = ScipIngestor._build_documents(_documents(), Path("/repo"))
    paths = {document.source.path for document in parsed}

    # matches what a static ingest run from /repo would key the Source on, so
    # GraphWriter's per-Source reconcile replaces the static entities (SCIP wins)
    assert "/repo/com/acme/OrderService.java" in paths
    # static default is "static"; SCIP entities are tagged for provenance
    assert CodeEntity(qualified_name="x", name="x", kind="method", embed_text="x").resolution == (
        "static"
    )


def _by_qn(entities: list) -> dict:
    return {entity.qualified_name: entity for entity in entities}
