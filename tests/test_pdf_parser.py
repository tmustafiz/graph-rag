import builtins
from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest

from graph_rag.ingest.parsers.pdf_parser import PdfParser

_PAGE_WIDTH, _PAGE_HEIGHT = 612.0, 792.0


def _make_pdf(
    path: Path,
    pages: list[list[tuple[float, str]]],
    toc: list[list],
    header: str | None = None,
) -> None:
    """`pages` is a list (one per page) of ``(y, text)`` lines. `toc` entries
    are ``[level, title, page_1indexed, y]``. `header` is drawn near the top of
    every page as a running header.
    """
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
        if header:
            page.insert_text((72, 24), header, fontsize=8)
        for y, text in lines:
            page.insert_text((72, y), text, fontsize=11)
    doc.set_toc(
        [
            [level, title, page, {"kind": 1, "to": pymupdf.Point(72, y)}]
            for level, title, page, y in toc
        ]
    )
    doc.save(path)
    doc.close()


@pytest.fixture
def two_headings_one_page(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "shared_page.pdf"
    _make_pdf(
        path,
        pages=[
            [
                (100, "Alpha Section"),
                (140, "Body text that belongs only to Alpha."),
                (400, "Bravo Section"),
                (440, "Body text that belongs only to Bravo."),
            ],
            [
                (100, "Charlie Section"),
                (140, "Body text that belongs only to Charlie, on its own page."),
            ],
        ],
        toc=[
            [1, "Alpha Section", 1, 90.0],
            [1, "Bravo Section", 1, 390.0],
            [1, "Charlie Section", 2, 90.0],
        ],
    )
    yield path


def test_headings_sharing_a_page_do_not_produce_duplicate_chunks(
    two_headings_one_page: Path,
) -> None:
    document = PdfParser().parse(two_headings_one_page)

    texts = [chunk.text for chunk in document.chunks]
    assert len(texts) == len(set(texts)), "no chunk text should be repeated"

    by_section: dict[str, str] = {}
    for chunk in document.chunks:
        by_section.setdefault(chunk.section_id.split("::")[-1], "")
        by_section[chunk.section_id.split("::")[-1]] += chunk.text

    assert "only to Alpha" in by_section["s0000"]
    assert "only to Bravo" not in by_section["s0000"]
    assert "only to Bravo" in by_section["s0001"]
    assert "only to Charlie" in by_section["s0002"]
    assert "only to Alpha" not in by_section["s0002"]


def test_parent_section_preamble_is_not_dropped(tmp_path: Path) -> None:
    path = tmp_path / "preamble.pdf"
    _make_pdf(
        path,
        pages=[
            [
                (100, "Parent Section"),
                (140, "Preamble that sits under Parent before any child heading."),
                (400, "Child Section"),
                (440, "Child body."),
            ]
        ],
        toc=[
            [1, "Parent Section", 1, 90.0],
            [2, "Child Section", 1, 390.0],
        ],
    )

    document = PdfParser().parse(path)
    joined = {
        section.title: "".join(
            chunk.text for chunk in document.chunks if chunk.section_id == section.id
        )
        for section in document.sections
    }

    assert "Preamble that sits under Parent" in joined["Parent Section"]
    assert "Child body" in joined["Child Section"]
    assert "Child body" not in joined["Parent Section"]


def test_running_header_is_stripped(tmp_path: Path) -> None:
    path = tmp_path / "with_header.pdf"
    _make_pdf(
        path,
        pages=[[(120, f"Heading {n}"), (160, f"Distinct body number {n}.")] for n in range(8)],
        toc=[[1, f"Heading {n}", n + 1, 110.0] for n in range(8)],
        header="ACME Corp Confidential User Guide",
    )

    document = PdfParser().parse(path)

    assert document.chunks
    assert all("ACME Corp Confidential" not in chunk.text for chunk in document.chunks)
    assert any("Distinct body number 3" in chunk.text for chunk in document.chunks)


def test_pdf_without_an_outline_yields_one_whole_document_section(tmp_path: Path) -> None:
    path = tmp_path / "no_toc.pdf"
    _make_pdf(
        path,
        pages=[
            [(100, "Some content on the first page.")],
            [(100, "More content on the second page.")],
        ],
        toc=[],
    )

    document = PdfParser().parse(path)

    assert len(document.sections) == 1
    assert document.sections[0].title == "no_toc"
    body = " ".join(chunk.text for chunk in document.chunks)
    assert "first page" in body
    assert "second page" in body


def test_body_spanning_multiple_pages_is_captured_once(tmp_path: Path) -> None:
    path = tmp_path / "multipage.pdf"
    _make_pdf(
        path,
        pages=[
            [(100, "Long Section"), (140, "Start of the long section.")],
            [(140, "Middle of the long section.")],
            [(140, "End of the long section."), (400, "Next Section"), (440, "Next body.")],
        ],
        toc=[
            [1, "Long Section", 1, 90.0],
            [1, "Next Section", 3, 390.0],
        ],
    )

    document = PdfParser().parse(path)
    long_section = next(s for s in document.sections if s.title == "Long Section")
    long_text = " ".join(
        chunk.text for chunk in document.chunks if chunk.section_id == long_section.id
    )

    for marker in ("Start of the long", "Middle of the long", "End of the long"):
        assert long_text.count(marker) == 1
    assert "Next body" not in long_text
    assert long_section.start_page == 1
    assert long_section.end_page == 3


def test_build_sections_assigns_hierarchy_and_breadcrumbs() -> None:
    # [level, title, page, dest]
    toc = [
        [1, "Concepts", 1, {}],
        [2, "Selection rules", 2, {}],
        [2, "Transformation rules", 5, {}],
        [1, "Endpoints", 8, {}],
    ]
    points = [(1, 0.0), (2, 0.0), (5, 0.0), (8, 0.0)]

    sections = PdfParser._build_sections(toc, points, "doc.pdf", page_count=10)

    by_title = {s.title: s for s in sections}
    assert by_title["Concepts"].parent_id is None
    assert by_title["Concepts"].breadcrumb == "Concepts"
    assert by_title["Selection rules"].parent_id == by_title["Concepts"].id
    assert by_title["Selection rules"].breadcrumb == "Concepts > Selection rules"
    assert by_title["Endpoints"].parent_id is None
    assert [s.id for s in sections] == [f"doc.pdf::s000{n}" for n in range(4)]
    assert [s.order for s in sections] == [0, 1, 2, 3]


def test_parse_without_pymupdf_raises_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `pdf` extra is optional, so importing the parser must not require
    pymupdf — only calling `parse()` on a PDF does, and then with a message
    that names the extra.
    """
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object):  # noqa: ANN202
        if name == "pymupdf":
            raise ModuleNotFoundError("No module named 'pymupdf'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match=r"'pdf' extra"):
        PdfParser().parse(Path("whatever.pdf"))
