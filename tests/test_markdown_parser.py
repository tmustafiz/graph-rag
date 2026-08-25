from pathlib import Path

from graph_rag.ingest.parsers.markdown_parser import MarkdownParser


def test_build_sections_assigns_hierarchy_and_breadcrumbs() -> None:
    lines = [
        "# Concepts",
        "## Selection rules",
        "## Transformation rules",
        "# Endpoints",
    ]
    headings = MarkdownParser._find_headings(lines)
    sections = MarkdownParser._build_sections(headings, "doc.md")

    by_title = {s.title: s for s in sections}
    assert by_title["Concepts"].parent_id is None
    assert by_title["Concepts"].breadcrumb == "Concepts"
    assert by_title["Selection rules"].parent_id == by_title["Concepts"].id
    assert by_title["Selection rules"].breadcrumb == "Concepts > Selection rules"
    assert by_title["Endpoints"].parent_id is None


def test_leaf_flags_mark_only_childless_entries() -> None:
    lines = ["# Concepts", "## Selection rules", "## Transformation rules", "# Endpoints"]
    headings = MarkdownParser._find_headings(lines)
    assert MarkdownParser._leaf_flags(headings) == [False, True, True, True]


def test_headings_inside_fenced_code_blocks_are_ignored() -> None:
    lines = ["# Real heading", "```", "# not a heading", "```", "## Also real"]
    headings = MarkdownParser._find_headings(lines)
    assert [title for _level, title, _line in headings] == ["Real heading", "Also real"]


def test_segment_body_keeps_fenced_code_block_atomic() -> None:
    lines = ["intro text", "```python", "def f():", "    pass", "```", "outro text"]
    segments = MarkdownParser._segment_body(lines)
    kinds = [kind for kind, _text in segments]
    assert kinds == ["prose", "code", "prose"]
    assert segments[1][1] == "```python\ndef f():\n    pass\n```"


def test_parse_end_to_end(tmp_path: Path) -> None:
    content = """---
title: Sample
---
# Getting started

Some intro prose here that is short.

## Install

Run this:

```bash
pip install graph-rag
```

# Reference

Second top-level section.
"""
    path = tmp_path / "doc.md"
    path.write_text(content)

    document = MarkdownParser().parse(path)

    assert document.source.source_type == "markdown"
    titles = [s.title for s in document.sections]
    assert titles == ["Getting started", "Install", "Reference"]

    install_section = next(s for s in document.sections if s.title == "Install")
    code_chunks = [c for c in document.chunks if c.section_id == install_section.id]
    assert any(c.text.strip().startswith("```bash") for c in code_chunks)

    # frontmatter must not leak into any section/chunk text
    assert not any("title: Sample" in c.text for c in document.chunks)


def test_parse_falls_back_to_single_section_when_no_headings(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("Just some prose, no headings at all.")

    document = MarkdownParser().parse(path)

    assert len(document.sections) == 1
    assert document.sections[0].title == "notes"
    assert len(document.chunks) == 1
    assert "Just some prose" in document.chunks[0].text
