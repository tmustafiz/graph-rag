import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..models import Chunk, ConfigFile, ConfigProperty, ParsedDocument, Section, Source

# `application-<profile>.yml` / `bootstrap-<profile>.properties` → the profile.
_FILENAME_PROFILE = re.compile(r"^(?:application|bootstrap)-([A-Za-z0-9_-]+)$")
# `${some.key}` or `${some.key:default}` inside a value.
_PLACEHOLDER = re.compile(r"\$\{([^{}:]+)(?::([^{}]*))?\}")
# Boot 2.4+ multi-document separator inside a `.properties` file.
_PROPERTIES_DOC_SEPARATOR = re.compile(r"^#-{3,}\s*$")
_PROFILE_KEYS = ("spring.config.activate.on-profile", "spring.profiles")
_SECRET_MARKERS = ("password", "secret", "token", "credential")
_REDACTED = "***"  # noqa: S105 - placeholder, not a credential


class ConfigFileParser:
    """Parses Spring / Java application config — `application*` / `bootstrap*`
    (`.yml` / `.yaml` / `.properties`) and any `*.properties` / `*.yml` under a
    `resources` directory — into a `ConfigFile` plus a flattened
    `ConfigProperty` list, and a `Section` + `Chunk`s so plain `search` finds
    "where is the datasource URL configured".

    YAML nesting is flattened to dotted keys (list items get an `[index]`
    suffix); `.properties` is read line-wise (comments, `\\` continuations and
    `#---` multi-document separators handled). The active Spring profile comes
    from the `application-<profile>` filename or a
    `spring.config.activate.on-profile` key. `${a.b:default}` placeholders
    resolve, best-effort, to `(:ConfigProperty)-[:REFERENCES]->(:ConfigProperty)`
    within the same file. Secret-looking keys keep their real value on the node
    but are redacted in the searchable chunk text.

    Registered ahead of `YamlParser`; a name/path-matched `.yml` that is
    actually a Checkov custom policy is handed back to `YamlParser`.
    """

    _YAML_SUFFIXES = (".yml", ".yaml")

    @classmethod
    def can_handle(cls, path: Path) -> bool:
        suffix = path.suffix.lower()
        if suffix == ".properties":
            return True
        if suffix not in cls._YAML_SUFFIXES:
            return False
        if not cls._name_or_location_matches(path):
            return False
        return not cls._is_checkov_policy_file(path)

    def parse(self, path: Path) -> ParsedDocument:
        raw = path.read_bytes()
        source = Source(
            path=str(path),
            source_type="config",
            content_hash=hashlib.sha256(raw).hexdigest(),
            ingested_at=datetime.now(UTC),
        )
        text = raw.decode("utf-8", errors="replace")
        fmt = "properties" if path.suffix.lower() == ".properties" else "yaml"
        filename_profile = self._filename_profile(path)

        entries = (
            self._parse_properties(text, filename_profile)
            if fmt == "properties"
            else self._parse_yaml(text, filename_profile)
        )
        properties = self._resolve_references(source.path, entries)

        config_file = ConfigFile(path=source.path, format=fmt)
        sections, chunks = self._build_chunks(source.path, path.stem, properties)
        return ParsedDocument(
            source=source,
            sections=sections,
            chunks=chunks,
            config_files=[config_file],
            config_properties=properties,
        )

    # -- can_handle helpers --

    @staticmethod
    def _name_or_location_matches(path: Path) -> bool:
        stem = path.stem.lower()
        if stem.startswith("application") or stem.startswith("bootstrap"):
            return True
        return "resources" in {part.lower() for part in path.parts}

    @staticmethod
    def _is_checkov_policy_file(path: Path) -> bool:
        try:
            documents = yaml.safe_load_all(path.read_text(encoding="utf-8", errors="replace"))
            return any(ConfigFileParser._is_checkov_policy(document) for document in documents)
        except (OSError, yaml.YAMLError):
            return False

    @staticmethod
    def _is_checkov_policy(document: Any) -> bool:
        return (
            isinstance(document, dict)
            and isinstance(document.get("metadata"), dict)
            and "id" in document["metadata"]
            and "definition" in document
        )

    # -- profiles --

    @staticmethod
    def _filename_profile(path: Path) -> str | None:
        match = _FILENAME_PROFILE.match(path.stem)
        return match.group(1) if match else None

    @staticmethod
    def _document_profile(
        keyed_values: list[tuple[str, str, int]], fallback: str | None
    ) -> str | None:
        for key, value, _line in keyed_values:
            for profile_key in _PROFILE_KEYS:
                if key == profile_key or key.startswith(f"{profile_key}["):
                    return value or fallback
        return fallback

    # -- .properties --

    @classmethod
    def _parse_properties(
        cls, text: str, filename_profile: str | None
    ) -> list[tuple[str, str, str | None, int]]:
        entries: list[tuple[str, str, str | None, int]] = []
        for segment_lines in cls._split_properties_documents(text):
            keyed_values = cls._properties_key_values(segment_lines)
            profile = cls._document_profile(keyed_values, filename_profile)
            entries.extend((key, value, profile, line) for key, value, line in keyed_values)
        return entries

    @staticmethod
    def _split_properties_documents(text: str) -> list[list[tuple[int, str]]]:
        segments: list[list[tuple[int, str]]] = [[]]
        for index, line in enumerate(text.splitlines(), start=1):
            if _PROPERTIES_DOC_SEPARATOR.match(line):
                segments.append([])
            else:
                segments[-1].append((index, line))
        return [segment for segment in segments if segment]

    @staticmethod
    def _properties_key_values(lines: list[tuple[int, str]]) -> list[tuple[str, str, int]]:
        results: list[tuple[str, str, int]] = []
        pending: list[str] = []
        start_line = 0
        for line_number, line in lines:
            stripped = line.strip()
            if not pending and (not stripped or stripped[0] in "#!"):
                continue
            if not pending:
                start_line = line_number
            if line.rstrip().endswith("\\") and not line.rstrip().endswith("\\\\"):
                pending.append(line.rstrip()[:-1])
                continue
            pending.append(line)
            joined = "".join(part.strip() if index else part for index, part in enumerate(pending))
            pending = []
            parsed = ConfigFileParser._split_property_line(joined.strip())
            if parsed is not None:
                results.append((parsed[0], parsed[1], start_line))
        return results

    @staticmethod
    def _split_property_line(line: str) -> tuple[str, str] | None:
        separator_index = next(
            (
                index
                for index, char in enumerate(line)
                if char in "=:" and (index == 0 or line[index - 1] != "\\")
            ),
            None,
        )
        if separator_index is None:
            whitespace = re.search(r"\s", line)
            separator_index = whitespace.start() if whitespace else None
        if separator_index is None:
            return None
        key = line[:separator_index].strip().replace("\\:", ":").replace("\\=", "=")
        value = line[separator_index + 1 :].strip()
        if not key:
            return None
        return key, value

    # -- YAML --

    @classmethod
    def _parse_yaml(
        cls, text: str, filename_profile: str | None
    ) -> list[tuple[str, str, str | None, int]]:
        try:
            nodes = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
        except yaml.YAMLError:
            return []
        entries: list[tuple[str, str, str | None, int]] = []
        for node in nodes:
            if not isinstance(node, yaml.MappingNode):
                continue
            keyed_values: list[tuple[str, str, int]] = []
            cls._flatten_yaml_node(node, "", keyed_values)
            profile = cls._document_profile(keyed_values, filename_profile)
            entries.extend((key, value, profile, line) for key, value, line in keyed_values)
        return entries

    @classmethod
    def _flatten_yaml_node(
        cls, node: yaml.Node, prefix: str, out: list[tuple[str, str, int]]
    ) -> None:
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                key = str(getattr(key_node, "value", key_node))
                child_prefix = f"{prefix}.{key}" if prefix else key
                cls._flatten_yaml_node(value_node, child_prefix, out)
        elif isinstance(node, yaml.SequenceNode):
            for index, item_node in enumerate(node.value):
                cls._flatten_yaml_node(item_node, f"{prefix}[{index}]", out)
        else:
            line = node.start_mark.line + 1
            out.append((prefix, "" if node.value is None else str(node.value), line))

    # -- placeholder references --

    @staticmethod
    def _resolve_references(
        file_path: str, entries: list[tuple[str, str, str | None, int]]
    ) -> list[ConfigProperty]:
        properties = [
            ConfigProperty(
                file_path=file_path,
                key=key,
                value=value,
                profile=profile,
                origin_line=line,
            )
            for key, value, profile, line in entries
        ]
        by_key: dict[str, list[ConfigProperty]] = {}
        for prop in properties:
            by_key.setdefault(prop.key, []).append(prop)

        resolved: list[ConfigProperty] = []
        for prop in properties:
            target_ids: list[str] = []
            for referenced_key, _default in _PLACEHOLDER.findall(prop.value):
                target = ConfigFileParser._pick_reference_target(
                    by_key.get(referenced_key.strip(), []), prop
                )
                if target is not None and target.id != prop.id and target.id not in target_ids:
                    target_ids.append(target.id)
            resolved.append(
                prop.model_copy(update={"references": target_ids}) if target_ids else prop
            )
        return resolved

    @staticmethod
    def _pick_reference_target(
        candidates: list[ConfigProperty], source: ConfigProperty
    ) -> ConfigProperty | None:
        if not candidates:
            return None
        same_profile = [c for c in candidates if c.profile == source.profile]
        if same_profile:
            return same_profile[0]
        default_profile = [c for c in candidates if c.profile is None]
        if default_profile:
            return default_profile[0]
        return candidates[0]

    # -- searchable chunks --

    @classmethod
    def _build_chunks(
        cls, source_path: str, stem: str, properties: list[ConfigProperty]
    ) -> tuple[list[Section], list[Chunk]]:
        if not properties:
            return [], []
        section = Section(
            id=f"{source_path}::s0000",
            title=stem,
            level=1,
            breadcrumb=stem,
            order=0,
        )
        grouped: dict[str | None, list[ConfigProperty]] = {}
        for prop in properties:
            grouped.setdefault(prop.profile, []).append(prop)

        chunks: list[Chunk] = []
        for order, (profile, group) in enumerate(grouped.items()):
            header = f"{stem} ({'profile ' + profile if profile else 'default profile'})"
            lines = [header] + [f"{prop.key} = {cls._display_value(prop)}" for prop in group]
            chunks.append(cls._build_chunk("\n".join(lines), section.id, order))
        return [section], chunks

    @staticmethod
    def _display_value(prop: ConfigProperty) -> str:
        lowered = prop.key.lower()
        segments = lowered.replace("[", ".").replace("]", "").split(".")
        if "key" in segments or any(marker in lowered for marker in _SECRET_MARKERS):
            return _REDACTED
        return prop.value

    @staticmethod
    def _build_chunk(text: str, section_id: str, order: int) -> Chunk:
        return Chunk(
            id=f"{section_id}::c{order:04d}",
            section_id=section_id,
            order=order,
            text=text,
            token_count=len(text.split()),
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
