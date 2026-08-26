from pathlib import Path

from graph_rag.ingest.parser_registry import ParserRegistry
from graph_rag.ingest.parsers import MarkdownParser, PdfParser, PythonParser, YamlParser


def test_for_path_routes_by_extension() -> None:
    registry = ParserRegistry()
    assert isinstance(registry.for_path(Path("doc.pdf")), PdfParser)
    assert isinstance(registry.for_path(Path("doc.md")), MarkdownParser)
    assert isinstance(registry.for_path(Path("mod.py")), PythonParser)
    assert isinstance(registry.for_path(Path("policy.yaml")), YamlParser)
    assert isinstance(registry.for_path(Path("policy.yml")), YamlParser)


def test_for_path_returns_none_for_unsupported_extension() -> None:
    registry = ParserRegistry()
    assert registry.for_path(Path("image.png")) is None


def test_custom_parser_list_is_used_instead_of_defaults() -> None:
    registry = ParserRegistry(parsers=[PythonParser()])
    assert registry.for_path(Path("doc.pdf")) is None
    assert isinstance(registry.for_path(Path("mod.py")), PythonParser)
