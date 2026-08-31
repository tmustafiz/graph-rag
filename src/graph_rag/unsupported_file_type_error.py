from pathlib import Path


class UnsupportedFileTypeError(Exception):
    """Raised when `grag-mcp ingest` is pointed at a file no registered parser can handle."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Unsupported file type: {path.suffix} (path: {path})")
