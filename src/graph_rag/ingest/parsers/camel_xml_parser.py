import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from ..models import ParsedDocument, Source
from .camel_xml_route_extractor import CamelXmlRouteExtractor

logger = logging.getLogger(__name__)

_CAMEL_ROOTS = {"camelContext", "routes", "route", "routeTemplate"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


class CamelXmlParser:
    """Parses a standalone Camel XML DSL file (`<camelContext>` / `<routes>` /
    `<route>` root, or a `<blueprint>` wrapping one) into `CamelRoute`s.

    A Spring `<beans>` file that *embeds* a `<camelContext>` is claimed by
    `SpringXmlParser` (for its beans) — that parser calls
    `CamelXmlRouteExtractor` too, so its routes are not lost.
    """

    @staticmethod
    def can_handle(path: Path) -> bool:
        if path.suffix.lower() != ".xml" or path.name == "pom.xml":
            return False
        try:
            root = ElementTree.fromstring(  # noqa: S314 - local project config, not untrusted
                path.read_bytes()
            )
        except (ElementTree.ParseError, OSError):
            return False
        if _local(root.tag) == "beans":
            return False
        if _local(root.tag) in _CAMEL_ROOTS:
            return True
        return any(_local(element.tag) in _CAMEL_ROOTS for element in root.iter())

    def parse(self, path: Path) -> ParsedDocument:
        raw = path.read_bytes()
        source = Source(
            path=str(path),
            source_type="camel-xml",
            content_hash=hashlib.sha256(raw).hexdigest(),
            ingested_at=datetime.now(UTC),
        )
        try:
            root = ElementTree.fromstring(raw)  # noqa: S314 - local project config, not untrusted
        except ElementTree.ParseError as exc:
            logger.warning("could not parse %s as Camel XML: %s", path, exc)
            return ParsedDocument(source=source)
        return ParsedDocument(
            source=source,
            camel_routes=CamelXmlRouteExtractor.extract(root, str(path)),
        )
