import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..models import Chunk, ParsedDocument, PolicyRule, Section, Source


class YamlParser:
    """Parses YAML into a `Source` plus either Checkov `PolicyRule`s or, for
    generic YAML, a single implicit `Section` chunked by top-level key.

    A document is treated as a Checkov custom policy when it has a
    `metadata.id` field (per the schema documented in
    `docs/IMPLEMENTATION_PLAN.md` Phase 6); everything else falls back to
    structural chunking so it still gets parsed and embedded.
    """

    @staticmethod
    def can_handle(path: Path) -> bool:
        return path.suffix.lower() in (".yaml", ".yml")

    def parse(self, path: Path) -> ParsedDocument:
        content = path.read_bytes()
        source = Source(
            path=str(path),
            source_type="yaml",
            content_hash=hashlib.sha256(content).hexdigest(),
            ingested_at=datetime.now(UTC),
        )

        documents = [
            document
            for document in yaml.safe_load_all(content.decode("utf-8"))
            if document is not None
        ]

        policy_rules: list[PolicyRule] = []
        generic_documents: list[dict] = []
        for document in documents:
            if self._is_checkov_policy(document):
                policy_rules.append(self._build_policy_rule(document, source.path))
            elif isinstance(document, dict):
                generic_documents.append(document)

        sections: list[Section] = []
        chunks: list[Chunk] = []
        if generic_documents:
            section = Section(
                id=f"{source.path}::s0000",
                title=path.stem,
                level=1,
                breadcrumb=path.stem,
                order=0,
            )
            sections.append(section)
            order = 0
            for document in generic_documents:
                for key, value in document.items():
                    text = yaml.safe_dump({key: value}, sort_keys=False).strip()
                    chunks.append(self._build_chunk(text, section.id, order))
                    order += 1

        return ParsedDocument(
            source=source, sections=sections, chunks=chunks, policy_rules=policy_rules
        )

    @staticmethod
    def _is_checkov_policy(document: Any) -> bool:
        return (
            isinstance(document, dict)
            and isinstance(document.get("metadata"), dict)
            and "id" in document["metadata"]
        )

    @staticmethod
    def _build_policy_rule(document: dict, file_path: str) -> PolicyRule:
        metadata = document["metadata"]
        scope = document.get("scope") if isinstance(document.get("scope"), dict) else {}
        policy_id = str(metadata["id"])
        name = metadata.get("name")
        category = metadata.get("category")
        severity = metadata.get("severity")
        guideline = metadata.get("guideline")
        provider = scope.get("provider")
        resource_types = YamlParser._collect_resource_types(document.get("definition"))

        return PolicyRule(
            id=policy_id,
            name=name,
            category=category,
            severity=severity,
            guideline=guideline,
            provider=provider,
            file_path=file_path,
            resource_types=resource_types,
            embed_text=YamlParser._embed_text(
                policy_id, name, category, provider, resource_types, guideline
            ),
        )

    @staticmethod
    def _collect_resource_types(node: Any) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for resource_type in YamlParser._walk_resource_types(node):
            if resource_type not in seen:
                seen.add(resource_type)
                ordered.append(resource_type)
        return ordered

    @staticmethod
    def _walk_resource_types(node: Any) -> list[str]:
        found: list[str] = []
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "resource_types" and isinstance(value, list):
                    found.extend(str(item) for item in value)
                else:
                    found.extend(YamlParser._walk_resource_types(value))
        elif isinstance(node, list):
            for item in node:
                found.extend(YamlParser._walk_resource_types(item))
        return found

    @staticmethod
    def _embed_text(
        policy_id: str,
        name: str | None,
        category: str | None,
        provider: str | None,
        resource_types: list[str],
        guideline: str | None,
    ) -> str:
        parts = [name or policy_id]
        if category:
            parts.append(f"Category: {category}")
        if provider:
            parts.append(f"Provider: {provider}")
        if resource_types:
            parts.append(f"Applies to: {', '.join(resource_types)}")
        if guideline:
            parts.append(guideline)
        return ". ".join(parts)

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
