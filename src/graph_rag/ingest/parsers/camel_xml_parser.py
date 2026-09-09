import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from ..models import ParsedDocument, Source
from .camel_xml_route_extractor import CamelXmlRouteExtractor

logger = logging.getLogger(__name__)

# Only these as the document *root* claim the file — not a `<route>` buried in a
# gateway descriptor / custom-schema config. An OSGi `<blueprint>` wrapper is the
# one exception: it's claimed when it *embeds* a `<camelContext>` (below).
_CAMEL_ROOT_TAGS = {"camelContext", "routes", "route", "routeTemplate"}
_CAMEL_NS_PREFIX = "http://camel.apache.org/schema/"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _namespace(tag: str) -> str:
    return tag[1 : tag.index("}")] if tag.startswith("{") else ""


def _is_camel_tag(tag: str) -> bool:
    """A bare (namespace-free) tag — hand-written snippet / fixture — or one in
    the Camel schema namespace.
    """
    namespace = _namespace(tag)
    return namespace == "" or namespace.startswith(_CAMEL_NS_PREFIX)


class CamelXmlParser:
    """Parses a Camel XML DSL file into `CamelRoute`s. Claims a
    `<camelContext>` / `<routes>` / `<routeTemplate>` / `<route>` document root,
    or a non-`<beans>` wrapper (an OSGi `<blueprint>`, …) that embeds a
    `<camelContext>`. A namespaced Camel element must be in the Camel namespace
    (`http://camel.apache.org/schema/...`); a bare (namespace-free) one is
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
        if _local(root.tag) in _CAMEL_ROOT_TAGS:
            return _is_camel_tag(root.tag)
        # A non-Camel wrapper that embeds a `<camelContext>` — an Apache Karaf /
        # ServiceMix / Fuse OSGi `<blueprint>`, a ServiceMix `<xbean>`, … The
        # route extractor scopes to the `<camelContext>` subtree. `<beans>` is
        # left out: SpringXmlParser claims those (and runs the extractor itself).
        if _local(root.tag) == "beans":
            return False
        return any(
            _local(element.tag) == "camelContext" and _is_camel_tag(element.tag)
            for element in root.iter()
        )

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
