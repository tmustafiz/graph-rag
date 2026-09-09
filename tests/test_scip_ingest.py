"""SCIP index ingestion — `ScipReader` (hand-rolled protobuf), `ScipSymbolParser`
(symbol string → qualified_name), and `ScipIngestor._build_documents` (pure —
no embedder / Neo4j).

The fixture `tests/fixtures/tiny_java.scip` is a hand-encoded index for a toy
two-file Java project; regenerate it with `tests/fixtures/build_tiny_scip.py`.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from graph_rag.ingest.models import CodeEntity, ParsedDocument, Source
from graph_rag.ingest.scip import (
    ScipDocument,
    ScipOccurrence,
    ScipReader,
    ScipSymbol,
    ScipSymbolParser,
)
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


# --- v0.7.0 code-review regressions --------------------------------------------


def test_overloaded_method_descriptors_keep_the_method_name_and_stay_distinct() -> None:
    """#153 — scip-java disambiguates overloads with a token inside the parens."""
    prefix = "scip-java maven com.acme 1.0"
    plain = ScipSymbolParser.parse(f"{prefix} com/acme/OrderService#submit().")
    plus_one = ScipSymbolParser.parse(f"{prefix} com/acme/OrderService#submit(+1).")
    typed = ScipSymbolParser.parse(f"{prefix} com/acme/OrderService#submit(String).")

    assert plain == ("com.acme.OrderService.submit", "method", "submit")
    assert plus_one[1] == "method" and typed[1] == "method"
    # the class node must not be overwritten by a name-less method row
    names = {plain[0], plus_one[0], typed[0]}
    assert len(names) == 3
    assert all(qn != "com.acme.OrderService" for qn in names)


def _doc(symbols: list[ScipSymbol], occurrences: list[ScipOccurrence], **kw) -> ScipDocument:
    return ScipDocument(
        relative_path="com/acme/OrderService.java",
        symbols=symbols,
        occurrences=occurrences,
        **kw,
    )


def _sym(symbol: str, kind: int = 0) -> ScipSymbol:
    return ScipSymbol(symbol=f"scip-java maven com.acme 1.0 {symbol}", kind=kind)


def _occ(
    symbol: str, rng: list[int], *, defn: bool, enclosing: list[int] | None = None
) -> ScipOccurrence:
    return ScipOccurrence(
        symbol=f"scip-java maven com.acme 1.0 {symbol}",
        symbol_roles=1 if defn else 0,
        range=rng,
        enclosing_range=enclosing or [],
    )


def test_calls_attributed_across_an_annotation_line_above_the_signature() -> None:
    """#154 — enclosing_range starts at the @Override line, the def identifier
    starts on the `public` line; match by containment, not start-line equality."""
    symbols = [
        _sym("com/acme/OrderService#", kind=6),
        _sym("com/acme/OrderService#submit().", kind=38),
    ]
    occurrences = [
        _occ("com/acme/OrderService#", [0, 6, 0, 18], defn=True),
        _occ("com/acme/OrderService#submit().", [4, 22, 4, 28], defn=True),
        # @Override on line 2, body to line 7 — a call to an external save()
        _occ(
            "com/acme/JpaOrderRepository#save().",
            [5, 8, 5, 12],
            defn=False,
            enclosing=[2, 2, 7, 3],
        ),
    ]
    parsed = ScipIngestor._build_documents([_doc(symbols, occurrences)], None)[0]
    submit = _by_qn(parsed.code_entities)["com.acme.OrderService.submit"]
    assert submit.calls == ["com.acme.JpaOrderRepository.save"]


def test_two_definitions_on_one_line_do_not_shadow_each_other() -> None:
    """#154 — def occurrences keyed by (line, column), not line alone."""
    symbols = [
        _sym("com/acme/Box#width.", kind=17),
        _sym("com/acme/Box#compute().", kind=38),
    ]
    occurrences = [
        _occ("com/acme/Box#width.", [10, 6, 10, 11], defn=True),
        _occ("com/acme/Box#compute().", [10, 25, 10, 32], defn=True),
        _occ(
            "com/acme/JpaOrderRepository#save().",
            [11, 4, 11, 8],
            defn=False,
            enclosing=[10, 20, 12, 3],
        ),
    ]
    parsed = ScipIngestor._build_documents([_doc(symbols, occurrences)], None)[0]
    compute = _by_qn(parsed.code_entities)["com.acme.Box.compute"]
    assert compute.calls == ["com.acme.JpaOrderRepository.save"]


@pytest.mark.parametrize(
    ("doc_language", "scheme", "expected"),
    [
        ("java", "scip-java", "java"),
        ("", "semanticdb", "java"),
        ("", "scip-typescript", "typescript"),
        ("kotlin", "scip-java", "kotlin"),
    ],
)
def test_scip_entity_language_comes_from_the_document_then_the_scheme(
    doc_language: str, scheme: str, expected: str
) -> None:
    """#165.3 — never a blanket `language="scip"`."""
    symbol = ScipSymbol(symbol=f"{scheme} maven com.acme 1.0 com/acme/OrderService#", kind=6)
    occ = ScipOccurrence(symbol=symbol.symbol, symbol_roles=1, range=[0, 6, 0, 18])
    doc = ScipDocument(
        relative_path="com/acme/OrderService.java",
        language=doc_language,
        symbols=[symbol],
        occurrences=[occ],
    )
    parsed = ScipIngestor._build_documents([doc], None)[0]
    assert parsed.code_entities[0].language == expected


@pytest.mark.parametrize(
    "truncated",
    [
        b"\x12\x80",  # tag for field 2 (LEN), then a varint that never terminates
        b"\x12\x80\x01",  # size varint = 128, but no payload follows
        _FIXTURE.read_bytes()[:1],  # a real index chopped mid-length-prefix
    ],
)
def test_reader_raises_on_a_truncated_index(truncated: bytes) -> None:
    """#165.4 — a `.scip` cut mid-write must not decode to a partial document."""
    with pytest.raises(ValueError):
        ScipReader.read(truncated)


class _NamingSession:
    """Records the reconcile/writer callables `write()` schedules, without
    running any Cypher."""

    def __init__(self, names: list[str]) -> None:
        self._names = names

    def __enter__(self) -> "_NamingSession":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def execute_write(self, fn, *_args):  # noqa: ANN001, ANN002, ANN201
        self._names.append(fn.__name__)


class _NamingDriver:
    def __init__(self) -> None:
        self.names: list[str] = []

    def session(self) -> _NamingSession:
        return _NamingSession(self.names)


def test_reconcile_frameworks_false_skips_the_framework_reconciles() -> None:
    """#151 — `--scip` (partial document) must not DETACH DELETE the framework
    graph a prior static ingest attached to the same path."""
    from graph_rag.graph.graph_writer import GraphWriter

    driver = _NamingDriver()
    document = ParsedDocument(
        source=Source(
            path="com/acme/OrderService.java",
            source_type="java",
            content_hash="h",
            ingested_at=datetime.now(UTC),
        ),
        code_entities=[
            CodeEntity(
                qualified_name="com.acme.OrderService",
                name="OrderService",
                kind="class",
                embed_text="x",
            )
        ],
    )
    GraphWriter(driver).write(document, reconcile_frameworks=False)  # type: ignore[arg-type]

    assert "_reconcile_code_entities" in driver.names
    for skipped in (
        "_reconcile_annotations",
        "_reconcile_http_endpoints",
        "_reconcile_sql_statements",
        "_reconcile_camel_routes",
        "_reconcile_message_flow",
        "_reconcile_modules",
        "_refresh_entity_behaviors",
    ):
        assert skipped not in driver.names

    driver_full = _NamingDriver()
    GraphWriter(driver_full).write(document)  # type: ignore[arg-type]
    assert "_reconcile_http_endpoints" in driver_full.names
