import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from xml.etree import ElementTree

from ..dedupe import dedupe
from ..models import Chunk, ConfigFile, ParsedDocument, Section, Source, SpringXmlBean
from .camel_xml_route_extractor import CamelXmlRouteExtractor
from .xml_namespace import local_name as _local
from .xml_namespace import namespace as _namespace

logger = logging.getLogger(__name__)

_BEANS_NS = "http://www.springframework.org/schema/beans"
_P_NS = "http://www.springframework.org/schema/p"
_C_NS = "http://www.springframework.org/schema/c"

# Well-known Spring namespace URIs → the conventional short prefix, used only to
# label `ConfigFile.namespace_elements` readably.
_NS_SHORT = {
    "http://www.springframework.org/schema/context": "context",
    "http://www.springframework.org/schema/aop": "aop",
    "http://www.springframework.org/schema/tx": "tx",
    "http://www.springframework.org/schema/util": "util",
    "http://www.springframework.org/schema/jee": "jee",
    "http://www.springframework.org/schema/lang": "lang",
    "http://www.springframework.org/schema/mvc": "mvc",
    "http://www.springframework.org/schema/task": "task",
    _P_NS: "p",
    _C_NS: "c",
}

# `${some.key}` or `${some.key:default}` inside a `value=` attribute.
_PLACEHOLDER = re.compile(r"\$\{([^{}:]+)(?::[^{}]*)?\}")


def _split_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [token.strip() for token in re.split(r"[,;\s]+", raw) if token.strip()]


def _placeholders(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [match.group(1).strip() for match in _PLACEHOLDER.finditer(raw)]


@dataclass
class _ScanState:
    """Accumulators threaded through the (possibly nested) `<beans>` walk."""

    source_path: str
    counter: "count[int]"
    beans: list[SpringXmlBean] = field(default_factory=list)
    scan_packages: list[str] = field(default_factory=list)
    placeholder_locations: list[str] = field(default_factory=list)
    import_resources: list[str] = field(default_factory=list)
    namespace_elements: list[str] = field(default_factory=list)
    alias_map: dict[str, list[str]] = field(default_factory=dict)


class SpringXmlParser:
    """Parses a Spring XML `<beans>` context (`applicationContext.xml`,
    `*-context.xml`, `WEB-INF/*-servlet.xml`, …) into a `ConfigFile` plus one
    `SpringXmlBean` per `<bean>` definition.

    Extracts `<bean id|name|class|scope|parent|factory-bean|factory-method|
    primary|abstract|lazy-init>`, `<constructor-arg ref>` / `<property name ref>`
    wiring (including `<ref bean>`, inner `<bean>`s, `<list>` / `<set>` / `<map>`
    of refs, and the `p:` / `c:` shortcut namespaces), `<alias>`, `<import
    resource>`, `<context:component-scan base-package>` and
    `<context:property-placeholder location>`. `${key}` placeholders in `value=`
    attributes are captured for best-effort `ConfigProperty` linking. Nested
    `<beans profile="...">` blocks are walked recursively, with the `profile`
    recorded on each bean they contain.

    The raw defs are projected into the shared `(:Bean {defined_in:'xml'})`
    graph by the post-ingest `SpringXmlResolver` pass; `<import resource>` and
    `<context:property-placeholder>` become `(:ConfigFile)-[:IMPORTS_CONTEXT
    {kind}]->(:ConfigFile)` there. Registered ahead of `ConfigFileParser`;
    `can_handle` matches only files whose root element is `<beans>`.
    """

    @staticmethod
    def can_handle(path: Path) -> bool:
        if path.suffix.lower() != ".xml" or path.name == "pom.xml":
            return False
        try:
            # Spring context files are small; a full parse just to read the root
            # tag is cheap and keeps no file handle open.
            root = ElementTree.fromstring(  # noqa: S314 - local project config, not untrusted
                path.read_bytes()
            )
        except (ElementTree.ParseError, OSError):
            return False
        return _local(root.tag) == "beans"

    def parse(self, path: Path) -> ParsedDocument:
        raw = path.read_bytes()
        source = Source(
            path=str(path),
            source_type="spring-xml",
            content_hash=hashlib.sha256(raw).hexdigest(),
            ingested_at=datetime.now(UTC),
        )
        try:
            root = ElementTree.fromstring(raw)  # noqa: S314 - local project config, not untrusted
        except ElementTree.ParseError as exc:
            logger.warning("could not parse %s as Spring XML: %s", path, exc)
            return ParsedDocument(source=source)

        state = _ScanState(source_path=source.path, counter=count(1))
        self._scan_container(root, None, state)

        beans = state.beans
        scan_packages = state.scan_packages
        placeholder_locations = state.placeholder_locations
        import_resources = state.import_resources
        namespace_elements = state.namespace_elements
        alias_map = state.alias_map

        for bean in beans:
            for alias in alias_map.get(bean.bean_name, []):
                if alias not in bean.aliases:
                    bean.aliases.append(alias)

        config_file = ConfigFile(
            path=source.path,
            format="spring-xml",
            scan_packages=dedupe(scan_packages, keep_empty=True),
            placeholder_locations=dedupe(placeholder_locations, keep_empty=True),
            import_resources=dedupe(import_resources, keep_empty=True),
            namespace_elements=dedupe(namespace_elements, keep_empty=True),
        )
        sections, chunks = self._build_chunks(source.path, path.stem, beans)
        return ParsedDocument(
            source=source,
            sections=sections,
            chunks=chunks,
            config_files=[config_file],
            spring_xml_beans=beans,
            # a `<beans>` file may also embed a `<camelContext>` with routes —
            # only run the route extractor when one is actually present, so a
            # plain `<beans>` never gets spurious Route / CamelStep nodes.
            camel_routes=(
                CamelXmlRouteExtractor.extract(root, source.path)
                if any(_local(element.tag) == "camelContext" for element in root.iter())
                else []
            ),
        )

    # -- <beans> container walk (recurses into nested <beans profile="...">) --

    @classmethod
    def _scan_container(
        cls, container: ElementTree.Element, profile: str | None, state: _ScanState
    ) -> None:
        for element in container:
            local = _local(element.tag)
            namespace = _namespace(element.tag)
            if namespace in ("", _BEANS_NS):
                if local == "bean":
                    cls._handle_bean(
                        element, state.source_path, state.counter, state.beans, profile
                    )
                elif local == "beans":
                    cls._scan_container(element, element.get("profile") or profile, state)
                elif local == "alias":
                    target, alias = element.get("name"), element.get("alias")
                    if target and alias:
                        state.alias_map.setdefault(target, []).append(alias)
                elif local == "import" and element.get("resource"):
                    state.import_resources.append(element.get("resource", ""))
                continue

            short = _NS_SHORT.get(namespace, namespace.rsplit("/", 1)[-1])
            state.namespace_elements.append(f"{short}:{local}")
            if local == "component-scan":
                state.scan_packages.extend(_split_list(element.get("base-package")))
            elif local == "property-placeholder":
                state.placeholder_locations.extend(_split_list(element.get("location")))
                state.placeholder_locations.extend(_split_list(element.get("locations")))

    # -- <bean> --

    @classmethod
    def _handle_bean(
        cls,
        element: ElementTree.Element,
        source_path: str,
        counter: "count[int]",
        out: list[SpringXmlBean],
        profile: str | None = None,
    ) -> str:
        class_name = element.get("class")
        name_tokens = _split_list(element.get("name"))
        explicit_id = element.get("id")
        if explicit_id:
            bean_id, aliases = explicit_id, list(name_tokens)
        elif name_tokens:
            bean_id, aliases = name_tokens[0], name_tokens[1:]
        else:
            simple = class_name.rsplit(".", 1)[-1] if class_name else "bean"
            bean_id, aliases = f"{simple}#{next(counter)}", []

        constructor_arg_refs: list[str] = []
        property_names: list[str] = []
        property_refs: list[str] = []
        value_placeholder_keys: list[str] = []

        for child in element:
            local = _local(child.tag)
            if local == "constructor-arg":
                constructor_arg_refs.extend(cls._wiring_refs(child, source_path, counter, out))
                value_placeholder_keys.extend(_placeholders(child.get("value")))
            elif local == "property":
                prop_name = child.get("name") or ""
                for ref in cls._wiring_refs(child, source_path, counter, out):
                    property_names.append(prop_name)
                    property_refs.append(ref)
                value_placeholder_keys.extend(_placeholders(child.get("value")))

        for attr_key, attr_value in element.attrib.items():
            attr_ns, attr_local = _namespace(attr_key), _local(attr_key)
            if attr_ns == _P_NS and attr_local.endswith("-ref"):
                property_names.append(attr_local[:-4])
                property_refs.append(attr_value)
            elif attr_ns == _C_NS and attr_local.endswith("-ref"):
                constructor_arg_refs.append(attr_value)
            elif attr_ns in (_P_NS, _C_NS):
                value_placeholder_keys.extend(_placeholders(attr_value))

        out.append(
            SpringXmlBean(
                source_path=source_path,
                bean_id=bean_id,
                bean_name=bean_id,
                class_name=class_name,
                profile=profile,
                scope=element.get("scope"),
                parent=element.get("parent"),
                factory_bean=element.get("factory-bean"),
                factory_method=element.get("factory-method"),
                primary=element.get("primary") == "true",
                abstract=element.get("abstract") == "true",
                lazy_init=element.get("lazy-init") == "true",
                aliases=aliases,
                depends_on=_split_list(element.get("depends-on")),
                constructor_arg_refs=constructor_arg_refs,
                property_names=property_names,
                property_refs=property_refs,
                value_placeholder_keys=dedupe(value_placeholder_keys, keep_empty=True),
            )
        )
        return bean_id

    @classmethod
    def _wiring_refs(
        cls,
        holder: ElementTree.Element,
        source_path: str,
        counter: "count[int]",
        out: list[SpringXmlBean],
    ) -> list[str]:
        """Every bean this `<constructor-arg>` / `<property>` points at — its own
        `ref=` attr, a nested `<ref>` / `<idref>` / inner `<bean>`, or the
        elements of a nested `<list>` / `<set>` / `<array>` / `<map>`.
        """
        refs: list[str] = [holder.get("ref") or ""]
        for child in holder:
            local = _local(child.tag)
            if local in ("ref", "idref"):
                refs.append(child.get("bean") or child.get("local") or child.get("parent") or "")
            elif local == "bean":
                refs.append(cls._handle_bean(child, source_path, counter, out))
            elif local in ("list", "set", "array"):
                refs.extend(cls._collection_refs(child, source_path, counter, out))
            elif local == "map":
                for entry in child:
                    if _local(entry.tag) != "entry":
                        continue
                    refs.append(entry.get("value-ref") or "")
                    refs.extend(cls._collection_refs(entry, source_path, counter, out))
        return [ref for ref in refs if ref]

    @classmethod
    def _collection_refs(
        cls,
        container: ElementTree.Element,
        source_path: str,
        counter: "count[int]",
        out: list[SpringXmlBean],
    ) -> list[str]:
        refs: list[str] = []
        for item in container:
            local = _local(item.tag)
            if local in ("ref", "idref"):
                refs.append(item.get("bean") or item.get("local") or "")
            elif local == "bean":
                refs.append(cls._handle_bean(item, source_path, counter, out))
        return [ref for ref in refs if ref]

    # -- searchable chunk --

    @staticmethod
    def _build_chunks(
        source_path: str, stem: str, beans: list[SpringXmlBean]
    ) -> tuple[list[Section], list[Chunk]]:
        if not beans:
            return [], []
        section = Section(id=f"{source_path}::s0000", title=stem, level=1, breadcrumb=stem, order=0)
        lines = [f"Spring XML context: {stem}"]
        for bean in beans:
            wired = ", ".join(bean.constructor_arg_refs + bean.property_refs)
            lines.append(
                f"{bean.bean_id} -> {bean.class_name or '(no class)'}"
                + (f" wires {wired}" if wired else "")
            )
        text = "\n".join(lines)
        chunk = Chunk(
            id=f"{section.id}::c0000",
            section_id=section.id,
            order=0,
            text=text,
            token_count=len(text.split()),
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        return [section], [chunk]
