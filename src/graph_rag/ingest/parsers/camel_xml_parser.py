import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from ..models import ParsedDocument, Source
from .camel_xml_route_extractor import CamelXmlRouteExtractor

logger = logging.getLogger(__name__)

# Only these as the document *root* claim the file — not a `<route>` buried in a
# gateway descriptor / OSGi blueprint / custom-schema config.
_CAMEL_ROOT_TAGS = {"camelContext", "routes", "route", "routeTemplate"}
_CAMEL_NS_PREFIX = "http://camel.apache.org/schema/"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _namespace(tag: str) -> str:
    return tag[1 : tag.index("}")] if tag.startswith("{") else ""


class CamelXmlParser:
    """Parses a standalone Camel XML DSL file — a `<camelContext>` / `<routes>` /
    `<routeTemplate>` / `<route>` document root — into `CamelRoute`s. A
    namespaced root must be in the Camel namespace
    (`http://camel.apache.org/schema/...`); a bare (namespace-free) root is
    accepted for hand-written snippets / test fixtures.

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
        if _local(root.tag) not in _CAMEL_ROOT_TAGS:
            return False
        namespace = _namespace(root.tag)
        return namespace == "" or namespace.startswith(_CAMEL_NS_PREFIX)

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
