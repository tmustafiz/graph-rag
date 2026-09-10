import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ..models import ParsedDocument, Source
from .camel_yaml_route_extractor import CamelYamlRouteExtractor

logger = logging.getLogger(__name__)

# `from: "jms:orders"` (a URI with a scheme), not `from: no-reply@example.com`.
_URI_SCHEME_RE = re.compile(r"[a-zA-Z][\w.+-]*:")


def _from_looks_like_camel(value: object) -> bool:
    if isinstance(value, dict):
        value = value.get("uri")
    return isinstance(value, str) and _URI_SCHEME_RE.match(value) is not None


def _has_route_shape(data: object) -> bool:
    # The Camel YAML DSL is a top-level *list* of `- route:` / `- from:` entries;
    # a lone `from:` mapping is ordinary config, not a route.
    if not isinstance(data, list) or not data:
        return False
    for entry in data:
        if not isinstance(entry, dict):
            continue
        route = entry.get("route")
        if isinstance(route, dict) and _from_looks_like_camel(route.get("from")):
            return True
        if "from" in entry and _from_looks_like_camel(entry.get("from")):
            return True
    return False


class CamelYamlParser:
    """Parses a Camel YAML DSL file — a top-level list of `- route:` / `- from:`
    entries (or a single such mapping) — into `CamelRoute`s.

    `can_handle` is deliberately narrow: the YAML must parse to a top-level list
    whose entries carry a `route.from` / top-level `from` that looks like a Camel
    URI (`scheme:...`), so ordinary `application.yml` / a `notification.yml` with
    `from: no-reply@example.com` / Checkov policy YAML is left to the other
    parsers.
    """

    @staticmethod
    def can_handle(path: Path) -> bool:
        if path.suffix.lower() not in (".yaml", ".yml"):
            return False
        try:
            data = yaml.safe_load(path.read_bytes())
        except (yaml.YAMLError, OSError):
            return False
        return _has_route_shape(data)

    def parse(self, path: Path) -> ParsedDocument:
        raw = path.read_bytes()
        source = Source(
            path=str(path),
            source_type="camel-yaml",
            content_hash=hashlib.sha256(raw).hexdigest(),
            ingested_at=datetime.now(UTC),
        )
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            logger.warning("could not parse %s as Camel YAML: %s", path, exc)
            return ParsedDocument(source=source)
        return ParsedDocument(
            source=source,
            camel_routes=CamelYamlRouteExtractor.extract(data, str(path)),
        )
