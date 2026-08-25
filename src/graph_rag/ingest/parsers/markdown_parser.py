import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from ..chunker import Chunker
from ..models import Chunk, ParsedDocument, Section, Source

_FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---[ \t]*\r?\n?", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


class MarkdownParser:
    """Parses Markdown into a `Source` + `Section` tree + `Chunk`s.

    Sections come from ATX headings (`#`..`######`); YAML frontmatter is
    stripped before parsing. Fenced code blocks are never split mid-block —
    each becomes its own atomic `Chunk` — while surrounding prose still goes
    through the word-bounded `Chunker`.
    """

    def __init__(self, chunker: Chunker | None = None) -> None:
        self._chunker = chunker or Chunker()

    def parse(self, path: Path) -> ParsedDocument:
        content = path.read_bytes()
        source = Source(
            path=str(path),
            source_type="markdown",
            content_hash=hashlib.sha256(content).hexdigest(),
            ingested_at=datetime.now(UTC),
        )

        text = _FRONTMATTER_RE.sub("", content.decode("utf-8"), count=1)
        lines = text.splitlines()
        headings = self._find_headings(lines) or [(1, path.stem, -1)]
        sections = self._build_sections(headings, source.path)

        chunks: list[Chunk] = []
        order = 0
        for index, (section, is_leaf) in enumerate(
            zip(sections, self._leaf_flags(headings), strict=True)
        ):
            if not is_leaf:
                continue
            body_start = headings[index][2] + 1
            body_end = headings[index + 1][2] if index + 1 < len(headings) else len(lines)
            for kind, segment_text in self._segment_body(lines[body_start:body_end]):
                if not segment_text.strip():
                    continue
                if kind == "code":
                    chunks.append(self._build_atomic_chunk(segment_text, section.id, order))
                    order += 1
                else:
                    segment_chunks = self._chunker.chunk(
                        segment_text, section.id, order, None, None
                    )
                    chunks.extend(segment_chunks)
                    order += len(segment_chunks)

        return ParsedDocument(source=source, sections=sections, chunks=chunks)

    @staticmethod
    def _find_headings(lines: list[str]) -> list[tuple[int, str, int]]:
        headings: list[tuple[int, str, int]] = []
        fence_char: str | None = None
        fence_len = 0
        for line_index, line in enumerate(lines):
            fence_match = _FENCE_RE.match(line.strip())
            if fence_match:
                char, length = fence_match.group(1)[0], len(fence_match.group(1))
                if fence_char is None:
                    fence_char, fence_len = char, length
                elif char == fence_char and length >= fence_len:
                    fence_char = None
                continue
            if fence_char is not None:
                continue
            heading_match = _HEADING_RE.match(line)
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                headings.append((level, title, line_index))
        return headings

    @staticmethod
    def _leaf_flags(headings: list[tuple[int, str, int]]) -> list[bool]:
        flags = []
        for index, (level, _title, _line) in enumerate(headings):
            next_level = headings[index + 1][0] if index + 1 < len(headings) else 0
            flags.append(next_level <= level)
        return flags

    @staticmethod
    def _build_sections(headings: list[tuple[int, str, int]], source_path: str) -> list[Section]:
        sections: list[Section] = []
        stack: list[Section] = []
        for index, (level, title, _line) in enumerate(headings):
            while stack and stack[-1].level >= level:
                stack.pop()
            parent = stack[-1] if stack else None
            section = Section(
                id=f"{source_path}::s{index:04d}",
                title=title,
                level=level,
                breadcrumb=f"{parent.breadcrumb} > {title}" if parent else title,
                order=index,
                parent_id=parent.id if parent else None,
            )
            sections.append(section)
            stack.append(section)
        return sections

    @staticmethod
    def _segment_body(lines: list[str]) -> list[tuple[str, str]]:
        raw_segments: list[tuple[str, list[str]]] = []
        fence_char: str | None = None
        fence_len = 0
        for line in lines:
            fence_match = _FENCE_RE.match(line.strip())
            kind = "code" if fence_char is not None or fence_match else "prose"
            if not raw_segments or raw_segments[-1][0] != kind:
                raw_segments.append((kind, []))
            raw_segments[-1][1].append(line)
            if fence_match:
                char, length = fence_match.group(1)[0], len(fence_match.group(1))
                if fence_char is None:
                    fence_char, fence_len = char, length
                elif char == fence_char and length >= fence_len:
                    fence_char = None
        return [(kind, "\n".join(seg_lines)) for kind, seg_lines in raw_segments]

    @staticmethod
    def _build_atomic_chunk(text: str, section_id: str, order: int) -> Chunk:
        return Chunk(
            id=f"{section_id}::c{order:04d}",
            section_id=section_id,
            order=order,
            text=text,
            token_count=len(text.split()),
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
