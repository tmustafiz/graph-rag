from pathlib import Path

from graph_rag.ingest.parser_registry import ParserRegistry
from graph_rag.ingest.parsers import (
    GradleParser,
    JavaParser,
    JavaScriptParser,
    MarkdownParser,
    MavenParser,
    PdfParser,
    PythonParser,
    SqlParser,
    StylesheetParser,
    YamlParser,
)


def test_for_path_routes_by_extension() -> None:
    registry = ParserRegistry()
    assert isinstance(registry.for_path(Path("doc.pdf")), PdfParser)
    assert isinstance(registry.for_path(Path("doc.md")), MarkdownParser)
    assert isinstance(registry.for_path(Path("mod.py")), PythonParser)
    assert isinstance(registry.for_path(Path("Service.java")), JavaParser)
    assert isinstance(registry.for_path(Path("app.ts")), JavaScriptParser)
    assert isinstance(registry.for_path(Path("app.tsx")), JavaScriptParser)
    assert isinstance(registry.for_path(Path("app.mjs")), JavaScriptParser)
    assert isinstance(registry.for_path(Path("schema.sql")), SqlParser)
    assert isinstance(registry.for_path(Path("V1__init.SQL")), SqlParser)
    assert isinstance(registry.for_path(Path("order_pkg.pkb")), SqlParser)
    assert isinstance(registry.for_path(Path("load_data.prc")), SqlParser)
    assert isinstance(registry.for_path(Path("theme.css")), StylesheetParser)
    assert isinstance(registry.for_path(Path("theme.scss")), StylesheetParser)
    assert isinstance(registry.for_path(Path("theme.less")), StylesheetParser)
    assert isinstance(registry.for_path(Path("policy.yaml")), YamlParser)
    assert isinstance(registry.for_path(Path("policy.yml")), YamlParser)
    assert isinstance(registry.for_path(Path("service/pom.xml")), MavenParser)
    assert isinstance(registry.for_path(Path("app/build.gradle")), GradleParser)
    assert isinstance(registry.for_path(Path("app/build.gradle.kts")), GradleParser)
    assert isinstance(registry.for_path(Path("settings.gradle")), GradleParser)


def test_for_path_returns_none_for_unsupported_extension() -> None:
    registry = ParserRegistry()
    assert registry.for_path(Path("image.png")) is None


def test_custom_parser_list_is_used_instead_of_defaults() -> None:
    registry = ParserRegistry(parsers=[PythonParser()])
    assert registry.for_path(Path("doc.pdf")) is None
    assert isinstance(registry.for_path(Path("mod.py")), PythonParser)
