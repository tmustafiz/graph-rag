import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from ..models import ExternalArtifact, Module, ModuleDependency, ParsedDocument, Source

logger = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")
_DEFAULT_MAIN_SOURCE = "src/main/java"
_DEFAULT_TEST_SOURCE = "src/test/java"
_GENERATED_SOURCE_DIRS = ("target/generated-sources", "target/generated-test-sources")


class MavenParser:
    """Parses a `pom.xml` into one `Module` plus its declared dependencies.

    Reads `groupId` / `artifactId` / `version` (inheriting from `<parent>` when
    absent), `<properties>` (used to interpolate `${...}` in dependency
    versions), the reactor `<modules>` list (aggregator → child `reactor`
    edges), `<dependencies>` (GAV + `scope`), and `<build><sourceDirectory>`.
    Source roots are the (possibly overridden) main dir, `src/test/java`, and
    any `target/generated-sources*` directory that exists on disk.

    Version resolution is build-free and best-effort: an unresolved `${...}`
    property is left verbatim. A malformed POM logs a warning and yields a
    `Source` with no `Module`.
    """

    @staticmethod
    def can_handle(path: Path) -> bool:
        return path.name == "pom.xml"

    def parse(self, path: Path) -> ParsedDocument:
        content = path.read_bytes()
        source = Source(
            path=str(path),
            source_type="maven",
            content_hash=hashlib.sha256(content).hexdigest(),
            ingested_at=datetime.now(UTC),
        )
        try:
            root = ElementTree.fromstring(content)  # noqa: S314 - local build file, not untrusted
        except ElementTree.ParseError as exc:
            logger.warning("could not parse %s as XML: %s", path, exc)
            return ParsedDocument(source=source)

        module_dir = path.parent.resolve()
        parent = self._child(root, "parent")
        group = self._text(root, "groupId") or self._text(parent, "groupId")
        artifact = self._text(root, "artifactId") or module_dir.name
        version = self._text(root, "version") or self._text(parent, "version")

        properties = self._properties(root, group, artifact, version)
        module = Module(
            path=str(module_dir),
            artifact=artifact,
            group=group,
            version=version,
            build_tool="maven",
            packages=[group] if group else [],
            source_roots=self._source_roots(root, module_dir),
        )

        externals: dict[str, ExternalArtifact] = {}
        dependencies: list[ModuleDependency] = []
        for node in self._iter(root, "dependencies", "dependency"):
            self._add_dependency(node, module.path, properties, externals, dependencies)
        for child_name in self._reactor_modules(root):
            child_dir = (module_dir / child_name).resolve()
            dependencies.append(
                ModuleDependency(
                    module_path=module.path, target_path=str(child_dir), scope="reactor"
                )
            )

        return ParsedDocument(
            source=source,
            modules=[module],
            external_artifacts=list(externals.values()),
            module_dependencies=dependencies,
        )

    # -- dependencies --

    @classmethod
    def _add_dependency(
        cls,
        node: ElementTree.Element,
        module_path: str,
        properties: dict[str, str],
        externals: dict[str, ExternalArtifact],
        dependencies: list[ModuleDependency],
    ) -> None:
        group = cls._interpolate(cls._text(node, "groupId"), properties)
        artifact = cls._interpolate(cls._text(node, "artifactId"), properties)
        if not group or not artifact:
            return
        version = cls._interpolate(cls._text(node, "version"), properties)
        scope = cls._text(node, "scope") or "compile"
        gav = f"{group}:{artifact}"
        externals.setdefault(
            gav, ExternalArtifact(gav=gav, group=group, artifact=artifact, version=version)
        )
        dependencies.append(ModuleDependency(module_path=module_path, target_gav=gav, scope=scope))

    @classmethod
    def _reactor_modules(cls, root: ElementTree.Element) -> list[str]:
        return [
            node.text.strip()
            for node in cls._iter(root, "modules", "module")
            if node.text and node.text.strip()
        ]

    # -- properties / interpolation --

    @classmethod
    def _properties(
        cls,
        root: ElementTree.Element,
        group: str | None,
        artifact: str | None,
        version: str | None,
    ) -> dict[str, str]:
        properties: dict[str, str] = {}
        container = cls._child(root, "properties")
        if container is not None:
            for node in container:
                if node.text and node.text.strip():
                    properties[cls._local(node.tag)] = node.text.strip()
        for key, value in (
            ("project.groupId", group),
            ("project.artifactId", artifact),
            ("project.version", version),
            ("pom.version", version),
        ):
            if value:
                properties[key] = value
        return properties

    @classmethod
    def _interpolate(cls, value: str | None, properties: dict[str, str]) -> str | None:
        if not value:
            return value
        return _PLACEHOLDER.sub(lambda match: properties.get(match.group(1), match.group(0)), value)

    # -- source roots --

    @classmethod
    def _source_roots(cls, root: ElementTree.Element, module_dir: Path) -> list[str]:
        build = cls._child(root, "build")
        main = (build is not None and cls._text(build, "sourceDirectory")) or _DEFAULT_MAIN_SOURCE
        roots = [module_dir / main, module_dir / _DEFAULT_TEST_SOURCE]
        roots.extend(
            module_dir / generated
            for generated in _GENERATED_SOURCE_DIRS
            if (module_dir / generated).is_dir()
        )
        ordered: list[str] = []
        for candidate in roots:
            resolved = str(candidate.resolve())
            if resolved not in ordered:
                ordered.append(resolved)
        return ordered

    # -- XML helpers (namespace-agnostic by local name) --

    @staticmethod
    def _local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    @classmethod
    def _child(cls, parent: ElementTree.Element | None, name: str) -> ElementTree.Element | None:
        if parent is None:
            return None
        return next((c for c in parent if cls._local(c.tag) == name), None)

    @classmethod
    def _text(cls, parent: ElementTree.Element | None, name: str) -> str | None:
        node = cls._child(parent, name)
        return node.text.strip() if node is not None and node.text and node.text.strip() else None

    @classmethod
    def _iter(
        cls, root: ElementTree.Element, container: str, item: str
    ) -> list[ElementTree.Element]:
        parent = cls._child(root, container)
        if parent is None:
            return []
        return [c for c in parent if cls._local(c.tag) == item]
