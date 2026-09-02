import hashlib
import re
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..chunker import Chunker
from ..models import Chunk, ParsedDocument, Section, Source

if TYPE_CHECKING:
    import pymupdf

_WHITESPACE_RE = re.compile(r"\s+")
_TRAILING_NUMBER_RE = re.compile(r"[\s·|]*\d+\s*$")

# A block whose top/bottom is within this many points of the page edge is a
# running header/footer candidate.
_CHROME_BAND_POINTS = 60.0
# ...and it is treated as chrome once its (page-number-stripped) text recurs
# on at least this fraction of pages.
_CHROME_MIN_PAGE_RATIO = 0.25
# Slack when comparing a block's y-coordinate against an outline destination's
# y — destinations tend to point a few points above the heading's text.
_Y_SLACK_POINTS = 4.0


def _normalize(text: str) -> str:
    """NFKC-normalize (so ``ﬁ`` becomes ``fi`` etc.) and collapse every run of
    whitespace to a single space. Heading matching and the chunk text both go
    through this, so the full-text index and the embeddings never see PDF
    typographic noise.
    """
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def _without_trailing_number(text: str) -> str:
    return _TRAILING_NUMBER_RE.sub("", text).strip()


class PdfParser:
    """Parses a PDF into a `Source` + `Section` tree + `Chunk`s.

    Section bodies are cut at the ``(page, y)`` coordinates of the outline
    (TOC) destinations rather than at page boundaries, so when several
    headings share a page each one gets only its own slice of text — no
    duplicated chunks — and a parent heading keeps whatever preamble sits
    above its first child. Recurring running headers/footers are dropped, and
    a PDF with no outline still yields one whole-document section.
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
                "`pip install 'grag-mcp[pdf]'` (or `uv sync --extra pdf`)."
            ) from exc

        content = path.read_bytes()
        source = Source(
            path=str(path),
            source_type="pdf",
            content_hash=hashlib.sha256(content).hexdigest(),
            ingested_at=datetime.now(UTC),
        )

        with pymupdf.open(path) as doc:
            page_count = doc.page_count
            page_blocks = self._page_blocks(doc)
            toc = doc.get_toc(simple=False)  # [[level, title, page, dest], ...]

            if not toc:
                sections = [
                    Section(
                        id=f"{source.path}::s0000",
                        title=path.stem,
                        level=1,
                        breadcrumb=path.stem,
                        order=0,
                        start_page=1 if page_count else None,
                        end_page=page_count or None,
                    )
                ]
                body = self._span_text(page_blocks, (1, float("-inf")), (page_count + 1, 0.0), None)
                chunks = self._chunker.chunk(body[0], sections[0].id, 0, body[1], body[2])
                return ParsedDocument(source=source, sections=sections, chunks=chunks)

            points = self._heading_points(toc, page_blocks, page_count)
            sections = self._build_sections(toc, points, source.path, page_count)

            chunks: list[Chunk] = []
            order = 0
            for index, section in enumerate(sections):
                start_point = points[index]
                end_point = points[index + 1] if index + 1 < len(points) else (page_count + 1, 0.0)
                text, first_page, last_page = self._span_text(
                    page_blocks, start_point, end_point, section.title
                )
                if not text:
                    continue
                section.start_page = first_page
                section.end_page = last_page
                section_chunks = self._chunker.chunk(text, section.id, order, first_page, last_page)
                chunks.extend(section_chunks)
                order += len(section_chunks)

        return ParsedDocument(source=source, sections=sections, chunks=chunks)

    @staticmethod
    def _build_sections(
        toc: list[list],
        points: list[tuple[int, float]],
        source_path: str,
        page_count: int,
    ) -> list[Section]:
        sections: list[Section] = []
        stack: list[Section] = []
        for index, entry in enumerate(toc):
            level, title = entry[0], entry[1]
            while stack and stack[-1].level >= level:
                stack.pop()
            parent = stack[-1] if stack else None
            next_page = points[index + 1][0] if index + 1 < len(points) else page_count + 1
            start_page = min(points[index][0], page_count) or None
            end_page = max(points[index][0], min(next_page - 1, page_count)) or None
            section = Section(
                id=f"{source_path}::s{index:04d}",
                title=title,
                level=level,
                breadcrumb=f"{parent.breadcrumb} > {title}" if parent else title,
                order=index,
                parent_id=parent.id if parent else None,
                start_page=start_page,
                end_page=end_page,
            )
            sections.append(section)
            stack.append(section)
        return sections

    @staticmethod
    def _heading_points(
        toc: list[list],
        page_blocks: list[list[tuple[float, float, str]]],
        page_count: int,
    ) -> list[tuple[int, float]]:
        """One ``(page, y)`` per TOC entry, in strictly non-decreasing document
        order. Uses the outline destination's ``to`` point; if that's missing,
        locates the heading text on its page; failing both, falls back to the
        page top (and the monotonic clamp then collapses it into its
        predecessor, so the section simply contributes nothing rather than
        duplicating a page).
        """
        points: list[tuple[int, float]] = []
        previous = (1, float("-inf"))
        for entry in toc:
            title, raw_page = entry[1], entry[2]
            dest = entry[3] if len(entry) > 3 and isinstance(entry[3], dict) else {}
            page_no = raw_page if 1 <= raw_page <= page_count else previous[0]
            page_no = max(1, min(page_no, max(page_count, 1)))

            destination = dest.get("to")
            if destination is not None:
                y = float(getattr(destination, "y", 0.0))
            else:
                y = PdfParser._locate_title_y(page_blocks, page_no, title)

            current = (page_no, y)
            if current < previous:
                current = previous
            points.append(current)
            previous = current
        return points

    @staticmethod
    def _locate_title_y(
        page_blocks: list[list[tuple[float, float, str]]], page_no: int, title: str
    ) -> float:
        if not 1 <= page_no <= len(page_blocks):
            return 0.0
        norm_title = _normalize(title)
        for y0, _y1, block_text in page_blocks[page_no - 1]:
            if norm_title and (norm_title in block_text or block_text in norm_title):
                return y0
        return 0.0

    def _page_blocks(self, doc: "pymupdf.Document") -> list[list[tuple[float, float, str]]]:
        """Normalized, y-sorted text blocks per page, with recurring running
        headers/footers removed.
        """
        raw: list[list[tuple[float, float, str]]] = []
        page_heights: list[float] = []
        for page in doc:
            page_heights.append(float(page.rect.height))
            blocks: list[tuple[float, float, str]] = []
            for item in page.get_text("blocks"):
                _x0, y0, _x1, y1, block_text = item[0], item[1], item[2], item[3], item[4]
                normalized = _normalize(block_text)
                if normalized:
                    blocks.append((float(y0), float(y1), normalized))
            blocks.sort(key=lambda block: block[0])
            raw.append(blocks)

        chrome = self._detect_chrome(raw, page_heights)
        if not chrome:
            return raw
        return [
            [
                block
                for position, block in enumerate(page)
                if not self._is_chrome(block, position, len(page), page_heights[page_index], chrome)
            ]
            for page_index, page in enumerate(raw)
        ]

    @staticmethod
    def _detect_chrome(
        pages: list[list[tuple[float, float, str]]], page_heights: list[float]
    ) -> set[str]:
        counter: Counter[str] = Counter()
        for page_index, page in enumerate(pages):
            if not page:
                continue
            height = page_heights[page_index]
            for position in (0, len(page) - 1):
                y0, y1, text = page[position]
                near_top = y0 <= _CHROME_BAND_POINTS
                near_bottom = y1 >= height - _CHROME_BAND_POINTS
                if near_top or near_bottom:
                    counter[_without_trailing_number(text)] += 1
        threshold = max(3, int(len(pages) * _CHROME_MIN_PAGE_RATIO))
        return {key for key, count in counter.items() if key and count >= threshold}

    @staticmethod
    def _is_chrome(
        block: tuple[float, float, str],
        position: int,
        page_len: int,
        page_height: float,
        chrome: set[str],
    ) -> bool:
        if position not in (0, page_len - 1):
            return False
        y0, y1, text = block
        if not (y0 <= _CHROME_BAND_POINTS or y1 >= page_height - _CHROME_BAND_POINTS):
            return False
        return _without_trailing_number(text) in chrome

    @staticmethod
    def _span_text(
        page_blocks: list[list[tuple[float, float, str]]],
        start_point: tuple[int, float],
        end_point: tuple[int, float],
        title: str | None,
    ) -> tuple[str, int | None, int | None]:
        """Text between two outline points, exclusive of the heading block
        itself. Returns ``(text, first_page, last_page)`` where the pages are
        the ones that actually contributed text (``(\"\", None, None)`` if none
        did).
        """
        start_page, start_y = start_point
        end_page, end_y = end_point
        norm_title = _normalize(title) if title else ""

        parts: list[str] = []
        pages_used: list[int] = []
        last_page = min(end_page, len(page_blocks))
        for page_no in range(max(start_page, 1), last_page + 1):
            lower = start_y if page_no == start_page else float("-inf")
            upper = end_y if page_no == end_page else float("inf")
            page_parts = [
                block_text
                for y0, _y1, block_text in page_blocks[page_no - 1]
                if y0 >= lower - _Y_SLACK_POINTS
                and y0 < upper - _Y_SLACK_POINTS
                and not (
                    page_no == start_page
                    and norm_title
                    and (block_text == norm_title or block_text.startswith(norm_title))
                )
            ]
            if page_parts:
                parts.append(" ".join(page_parts))
                pages_used.append(page_no)

        if not pages_used:
            return "", None, None
        return " ".join(parts), pages_used[0], pages_used[-1]
