import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ..chunker import Chunker
from ..models import Chunk, ParsedDocument, Section, Source

if TYPE_CHECKING:
    import pymupdf


class PdfParser:
    """Parses a PDF into a `Source` + `Section` tree + `Chunk`s, using the
    document's embedded TOC/outline for heading hierarchy.
    """

    def __init__(self, chunker: Chunker | None = None) -> None:
        self._chunker = chunker or Chunker()

    @staticmethod
    def can_handle(path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def parse(self, path: Path) -> ParsedDocument:
        try:
            import pymupdf
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Parsing PDFs needs the optional 'pdf' extra. Install it with "
                "`pip install 'graph-rag[pdf]'` (or `uv sync --extra pdf`)."
            ) from exc

        content = path.read_bytes()
        source = Source(
            path=str(path),
            source_type="pdf",
            content_hash=hashlib.sha256(content).hexdigest(),
            ingested_at=datetime.now(UTC),
        )

        with pymupdf.open(path) as doc:
            toc = doc.get_toc(simple=True)  # [[level, title, start_page(1-indexed)], ...]
            sections = self._build_sections(toc, source.path, doc.page_count)

            chunks: list[Chunk] = []
            order = 0
            for section, is_leaf in zip(sections, self._leaf_flags(toc), strict=True):
                if not is_leaf or section.start_page is None or section.end_page is None:
                    continue
                text = self._extract_text(doc, section.start_page, section.end_page)
                section_chunks = self._chunker.chunk(
                    text, section.id, order, section.start_page, section.end_page
                )
                chunks.extend(section_chunks)
                order += len(section_chunks)

        return ParsedDocument(source=source, sections=sections, chunks=chunks)

    @staticmethod
    def _leaf_flags(toc: list[list]) -> list[bool]:
        flags = []
        for index, (level, _title, _page) in enumerate(toc):
            next_level = toc[index + 1][0] if index + 1 < len(toc) else 0
            flags.append(next_level <= level)
        return flags

    @staticmethod
    def _build_sections(toc: list[list], source_path: str, page_count: int) -> list[Section]:
        sections: list[Section] = []
        stack: list[Section] = []
        for index, (level, title, start_page) in enumerate(toc):
            while stack and stack[-1].level >= level:
                stack.pop()
            parent = stack[-1] if stack else None
            end_page = toc[index + 1][2] - 1 if index + 1 < len(toc) else page_count
            section = Section(
                id=f"{source_path}::s{index:04d}",
                title=title,
                level=level,
                breadcrumb=f"{parent.breadcrumb} > {title}" if parent else title,
                order=index,
                parent_id=parent.id if parent else None,
                start_page=start_page,
                end_page=max(end_page, start_page),
            )
            sections.append(section)
            stack.append(section)
        return sections

    @staticmethod
    def _extract_text(doc: "pymupdf.Document", start_page: int, end_page: int) -> str:
        # start_page/end_page are 1-indexed (from the TOC); pymupdf pages are 0-indexed.
        # get_text("text") always returns str; the stub's overloads are keyed dynamically
        # and can't narrow on the literal, hence the cast.
        pages = [
            cast(str, doc[page_number].get_text("text"))
            for page_number in range(start_page - 1, end_page)
        ]
        return "\n".join(pages)
