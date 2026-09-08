import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ..models import ParsedDocument, Source
from .camel_yaml_route_extractor import CamelYamlRouteExtractor

logger = logging.getLogger(__name__)


def _has_route_shape(data: object) -> bool:
    entries = data if isinstance(data, list) else [data]
    for entry in entries:
        if isinstance(entry, dict) and (
            (isinstance(entry.get("route"), dict) and "from" in entry["route"]) or "from" in entry
        ):
            return True
    return False


class CamelYamlParser:
    """Parses a Camel YAML DSL file — a top-level list of `- route:` / `- from:`
    entries (or a single such mapping) — into `CamelRoute`s.

    `can_handle` is deliberately narrow: the YAML must parse to a list/mapping
    whose entries carry a `route.from` or a top-level `from`, so ordinary
    `application.yml` / Checkov policy YAML is left to the other parsers.
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
