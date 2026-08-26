from pathlib import Path
from typing import Protocol

from .models import ParsedDocument


class Parser(Protocol):
    """Contract every parser plugin implements: extension sniffing + parsing."""

    def can_handle(self, path: Path) -> bool: ...

    def parse(self, path: Path) -> ParsedDocument: ...
