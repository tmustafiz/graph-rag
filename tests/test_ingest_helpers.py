"""#166 — the shared `dedupe` and XML-namespace helpers that replaced the
~8 `_dedupe` / `_unique` and 5 `_local` / 2 `_namespace` parser copies.
"""

from graph_rag.ingest.dedupe import dedupe
from graph_rag.ingest.parsers.xml_namespace import local_name, namespace


def test_dedupe_is_order_preserving_first_wins() -> None:
    assert dedupe(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_dedupe_drops_falsy_by_default() -> None:
    assert dedupe(["a", "", "b", "", "a"]) == ["a", "b"]


def test_dedupe_keeps_empty_when_asked() -> None:
    # `@GetMapping({"", "/list"})` maps the base path too — `_dedupe(paths)` in
    # `http_endpoint_extractor` and the `spring_xml_parser` config lists relied
    # on `""` surviving.
    assert dedupe(["", "/list", "", "/list"], keep_empty=True) == ["", "/list"]


def test_dedupe_accepts_a_generator() -> None:
    assert dedupe(str(n % 3) for n in range(7)) == ["0", "1", "2"]


def test_local_name_strips_the_namespace() -> None:
    assert local_name("{http://camel.apache.org/schema/spring}route") == "route"
    assert local_name("route") == "route"


def test_namespace_extracts_the_uri() -> None:
    assert namespace("{http://camel.apache.org/schema/spring}route") == (
        "http://camel.apache.org/schema/spring"
    )
    assert namespace("route") == ""
