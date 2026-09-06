import builtins
import logging
from pathlib import Path

import pytest

from graph_rag.ingest.parsers.stylesheet_parser import StylesheetParser


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body)
    return path


def _chunk_texts(document) -> list[str]:
    return [chunk.text for chunk in document.chunks]


def test_can_handle_matches_stylesheet_extensions() -> None:
    parser = StylesheetParser()
    for name in ("a.css", "b.scss", "c.sass", "d.less", "E.CSS"):
        assert parser.can_handle(Path(name))
    assert not parser.can_handle(Path("script.js"))


def test_plain_css_rules_become_one_chunk_each(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "site.css",
        ".btn { color: #fff; background: #333; }\n.btn:hover, .btn:focus { opacity: 0.9; }\n",
    )

    document = StylesheetParser().parse(path)

    assert document.source.source_type == "css"
    texts = _chunk_texts(document)
    assert ".btn { color: #fff; background: #333 }" in texts
    assert ".btn:hover, .btn:focus { opacity: 0.9 }" in texts


def test_media_block_becomes_its_own_section(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "site.css",
        ".btn { width: auto; }\n@media (max-width: 480px) {\n  .btn { width: 100%; }\n}\n",
    )

    document = StylesheetParser().parse(path)

    section_titles = {section.title for section in document.sections}
    assert "site.css" in section_titles
    assert "@media (max-width: 480px)" in section_titles

    media_section = next(s for s in document.sections if s.level == 2)
    media_chunks = [c.text for c in document.chunks if c.section_id == media_section.id]
    assert media_chunks == [".btn { width: 100% }"]


def test_scss_nesting_is_flattened_into_selector_paths(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "card.scss",
        ".card {\n  color: #111;\n  .title { font-weight: bold; }\n  &:hover { color: #000; }\n}\n",
    )

    document = StylesheetParser().parse(path)
    texts = _chunk_texts(document)

    assert ".card { color: #111 }" in texts
    assert ".card .title { font-weight: bold }" in texts
    assert ".card:hover { color: #000 }" in texts


def test_custom_properties_and_scss_variables_get_named_chunks(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "tokens.scss",
        "$accent: #3366ff;\n"
        "$pad: 8px;\n"
        ":root { --accent: #3366ff; }\n"
        "@mixin shadow($level: 1) { box-shadow: 0 $level 4px #0003; }\n",
    )

    document = StylesheetParser().parse(path)
    texts = _chunk_texts(document)

    assert "$accent: #3366ff;" in texts
    assert "$pad: 8px;" in texts
    assert any(t.startswith("--accent: #3366ff;") and "(in :root)" in t for t in texts)
    assert "@mixin shadow($level: 1)" in texts


def test_import_use_and_forward_resolve_to_source_import_paths(tmp_path: Path) -> None:
    (tmp_path / "_tokens.scss").write_text("$x: 1;\n")
    (tmp_path / "reset.css").write_text("* { margin: 0; }\n")
    path = _write(
        tmp_path,
        "app.scss",
        '@use "sass:math";\n'
        '@forward "tokens";\n'
        '@import "reset";\n'
        '@import "https://cdn.example.com/x.css";\n'
        ".x { color: red; }\n",
    )

    document = StylesheetParser().parse(path)

    assert str(tmp_path / "_tokens.scss") in document.source_imports
    assert str(tmp_path / "reset.css") in document.source_imports
    # Sass built-ins and remote URLs are not file imports.
    assert not any("sass:math" in target for target in document.source_imports)
    assert not any(target.startswith("https://") for target in document.source_imports)


def test_graph_writer_builds_source_imports_pairs(tmp_path: Path) -> None:
    from graph_rag.graph.graph_writer import GraphWriter

    (tmp_path / "reset.css").write_text("* { margin: 0; }\n")
    path = _write(tmp_path, "app.css", '@import "reset.css";\n.x { color: red; }\n')
    document = StylesheetParser().parse(path)

    pairs = GraphWriter._source_import_pairs(document)
    assert pairs == [{"from": str(path), "to": str(tmp_path / "reset.css")}]


def test_malformed_stylesheet_yields_partial_result_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(
        tmp_path,
        "broken.scss",
        ".ok { color: green; }\n.bad { color: ; ; { } garbage\n",
    )

    with caplog.at_level(logging.WARNING):
        document = StylesheetParser().parse(path)

    assert any(".ok { color: green }" == chunk.text for chunk in document.chunks)
    assert any("syntax errors" in record.message for record in caplog.records)


def test_parse_without_tree_sitter_raises_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, "site.css", ".a { color: red; }\n")
    real_import = builtins.__import__

    def _no_tree_sitter(name: str, *args, **kwargs):
        if name == "tree_sitter_language_pack" or name.startswith("tree_sitter_language_pack."):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_tree_sitter)

    with pytest.raises(RuntimeError, match=r"'css' extra"):
        StylesheetParser().parse(path)
