from pathlib import Path

from .parser import Parser
from .parsers import MarkdownParser, PdfParser, PythonParser, YamlParser


class ParserRegistry:
    """Looks up which registered `Parser` (if any) can handle a given file.

    Adding support for a new file type is: write a parser with
    `can_handle`/`parse`, add an instance here — no other code changes.
    """

    def __init__(self, parsers: list[Parser] | None = None) -> None:
        self._parsers: list[Parser] = parsers or [
            PdfParser(),
            MarkdownParser(),
            PythonParser(),
            YamlParser(),
        ]

    def for_path(self, path: Path) -> Parser | None:
        for parser in self._parsers:
            if parser.can_handle(path):
                return parser
        return None
