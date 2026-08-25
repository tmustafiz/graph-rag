from graph_rag.ingest.pdf_parser import PdfParser

# [level, title, start_page]
SAMPLE_TOC = [
    [1, "Concepts", 1],
    [2, "Selection rules", 2],
    [2, "Transformation rules", 5],
    [1, "Endpoints", 8],
]


def test_build_sections_assigns_hierarchy_and_breadcrumbs() -> None:
    sections = PdfParser._build_sections(SAMPLE_TOC, "doc.pdf", page_count=10)

    by_title = {s.title: s for s in sections}
    assert by_title["Concepts"].parent_id is None
    assert by_title["Concepts"].breadcrumb == "Concepts"
    assert by_title["Selection rules"].parent_id == by_title["Concepts"].id
    assert by_title["Selection rules"].breadcrumb == "Concepts > Selection rules"
    assert by_title["Endpoints"].parent_id is None


def test_build_sections_computes_page_ranges() -> None:
    sections = PdfParser._build_sections(SAMPLE_TOC, "doc.pdf", page_count=10)
    by_title = {s.title: s for s in sections}

    assert by_title["Concepts"].start_page == 1
    assert by_title["Concepts"].end_page == 1  # ends right before "Selection rules" (page 2)
    assert by_title["Selection rules"].start_page == 2
    assert by_title["Selection rules"].end_page == 4
    assert by_title["Endpoints"].start_page == 8
    assert by_title["Endpoints"].end_page == 10  # last entry runs to page_count


def test_leaf_flags_mark_only_childless_entries() -> None:
    flags = PdfParser._leaf_flags(SAMPLE_TOC)
    assert flags == [False, True, True, True]


def test_section_ids_are_stable_and_ordered() -> None:
    sections = PdfParser._build_sections(SAMPLE_TOC, "doc.pdf", page_count=10)
    assert [s.id for s in sections] == [
        "doc.pdf::s0000",
        "doc.pdf::s0001",
        "doc.pdf::s0002",
        "doc.pdf::s0003",
    ]
    assert [s.order for s in sections] == [0, 1, 2, 3]
