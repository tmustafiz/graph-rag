import json
import logging
import os
from typing import Any, LiteralString, NamedTuple, cast

from neo4j import Driver, ManagedTransaction

logger = logging.getLogger(__name__)

# Every `:Bean` the previous `SpringBeanResolver` pass built has already been
# wiped and rebuilt by the time this runs, so the only `defined_in = 'xml'`
# beans left are stale ones from an earlier run of *this* pass.
_CLEAR_XML_BEANS = "MATCH (b:Bean) WHERE b.defined_in = 'xml' DETACH DELETE b"
_CLEAR_IMPORTS_CONTEXT = "MATCH (:ConfigFile)-[r:IMPORTS_CONTEXT]->() DELETE r"

_XML_BEAN_DEFS = """
MATCH (:ConfigFile)-[:DECLARES_BEAN]->(b:SpringXmlBean)
RETURN b.id AS id, b.source_path AS source_path, b.bean_id AS bean_id,
       b.bean_name AS bean_name, b.class_name AS class_name, b.scope AS scope,
       b.primary AS primary, b.abstract AS abstract, b.aliases AS aliases,
       b.constructor_arg_refs AS constructor_arg_refs, b.property_names AS property_names,
       b.property_refs AS property_refs, b.value_placeholder_keys AS value_placeholder_keys
"""

_EXISTING_BEANS = "MATCH (b:Bean) RETURN b.id AS id, b.name AS name"

_CONFIG_FILES = """
MATCH (cf:ConfigFile)
RETURN cf.path AS path, cf.format AS format,
       cf.import_resources AS import_resources,
       cf.placeholder_locations AS placeholder_locations
"""

_CONFIG_PROPERTIES = "MATCH (cp:ConfigProperty) RETURN cp.id AS id, cp.key AS key"

_MERGE_XML_BEANS = """
UNWIND $rows AS row
MERGE (b:Bean {id: row.id})
SET b.name = row.name, b.stereotype = row.stereotype, b.scope = row.scope,
    b.primary = row.primary, b.abstract = row.abstract, b.bean_type = row.bean_type,
    b.source_path = row.source_path, b.defined_in = 'xml',
    b.unresolved_injections = row.unresolved_injections
"""

_MERGE_XML_STUBS = """
UNWIND $rows AS row
MERGE (b:Bean {id: row.id})
SET b.name = row.name, b.stereotype = 'XmlBeanStub', b.defined_in = 'xml', b.unresolved = true
"""

_MERGE_XML_IS_BEAN = """
UNWIND $rows AS row
MATCH (ce:CodeEntity {qualified_name: row.class_name})
MATCH (b:Bean {id: row.bean_id})
MERGE (ce)-[:IS_BEAN]->(b)
"""

_MERGE_XML_INJECTS = """
UNWIND $rows AS row
MATCH (s:Bean {id: row.from})
MATCH (t:Bean {id: row.to})
MERGE (s)-[r:INJECTS]->(t)
SET r.via = row.via, r.property = row.property
"""

_MERGE_XML_BINDS = """
UNWIND $rows AS row
MATCH (b:Bean {id: row.from})
MATCH (cp:ConfigProperty {id: row.to})
MERGE (b)-[:BINDS]->(cp)
"""

_MERGE_IMPORTS_CONTEXT = """
UNWIND $rows AS row
MATCH (a:ConfigFile {path: row.from})
MATCH (b:ConfigFile {path: row.to})
MERGE (a)-[r:IMPORTS_CONTEXT]->(b)
SET r.kind = row.kind
"""

_CLASSPATH_PREFIXES = ("classpath*:", "classpath:", "file:")


class _Assembled(NamedTuple):
    bean_rows: list[dict[str, Any]]
    stub_rows: list[dict[str, str]]
    is_bean_rows: list[dict[str, str]]
    injects: list[dict[str, Any]]
    binds: list[dict[str, str]]
    imports_context: list[dict[str, str]]


class SpringXmlResolver:
    """Third post-directory-ingest pass (after `ProjectModelResolver` and
    `SpringBeanResolver`). Projects the `:SpringXmlBean` intermediate nodes that
    `SpringXmlParser` wrote into the **same** `(:Bean)` graph the annotation
    beans live in, so XML-wired and annotation-wired beans are queried together.

    * Each `<bean>` becomes `(:Bean {defined_in:'xml', stereotype:'XmlBean',
      name, scope, primary, abstract, bean_type})`; when its `class` resolves to
      an ingested type, `(:CodeEntity)-[:IS_BEAN]->(:Bean)`.
    * `<constructor-arg ref>` / `<property name ref>` (and `p:` / `c:` shortcuts,
      `<list>` / `<set>` / `<map>` of refs, inner beans) resolve — by bean name
      or alias, against XML **and** annotation beans — to
      `(:Bean)-[:INJECTS {via:'xml-constructor'|'xml-property', property}]->(:Bean)`.
      An unknown ref becomes a stub `(:Bean {stereotype:'XmlBeanStub'})` keyed by
      the ref name; an ambiguous one is left on `Bean.unresolved_injections`.
    * `${key}` in a `<property value>` links `(:Bean)-[:BINDS]->(:ConfigProperty)`.
    * `<import resource>` and `<context:property-placeholder location>` become
      `(:ConfigFile)-[:IMPORTS_CONTEXT {kind:'import'|'property-placeholder'}]->(:ConfigFile)`
      when the referenced file was also ingested.

    Rebuilt from scratch each run (every `defined_in:'xml'` bean and every
    `IMPORTS_CONTEXT` edge is dropped first), so it is idempotent.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def resolve(self) -> dict[str, int]:
        with self._driver.session() as session:
            result = session.execute_write(self._rebuild)
        logger.info("spring xml bean graph resolved: %s", result)
        return result

    @classmethod
    def _rebuild(cls, tx: ManagedTransaction) -> dict[str, int]:
        tx.run(cast(LiteralString, _CLEAR_XML_BEANS))
        tx.run(cast(LiteralString, _CLEAR_IMPORTS_CONTEXT))
        assembled = cls._assemble(
            [dict(row) for row in tx.run(cast(LiteralString, _XML_BEAN_DEFS))],
            [dict(row) for row in tx.run(cast(LiteralString, _EXISTING_BEANS))],
            [dict(row) for row in tx.run(cast(LiteralString, _CONFIG_FILES))],
            [dict(row) for row in tx.run(cast(LiteralString, _CONFIG_PROPERTIES))],
        )
        if assembled.bean_rows:
            tx.run(cast(LiteralString, _MERGE_XML_BEANS), rows=assembled.bean_rows)
        if assembled.stub_rows:
            tx.run(cast(LiteralString, _MERGE_XML_STUBS), rows=assembled.stub_rows)
        if assembled.is_bean_rows:
            tx.run(cast(LiteralString, _MERGE_XML_IS_BEAN), rows=assembled.is_bean_rows)
        if assembled.injects:
            tx.run(cast(LiteralString, _MERGE_XML_INJECTS), rows=assembled.injects)
        if assembled.binds:
            tx.run(cast(LiteralString, _MERGE_XML_BINDS), rows=assembled.binds)
        if assembled.imports_context:
            tx.run(cast(LiteralString, _MERGE_IMPORTS_CONTEXT), rows=assembled.imports_context)
        return {
            "xml_beans": len(assembled.bean_rows),
            "xml_stubs": len(assembled.stub_rows),
            "xml_injects": len(assembled.injects),
            "xml_binds": len(assembled.binds),
            "imports_context": len(assembled.imports_context),
        }

    # -- assembly (pure — unit-tested without Neo4j) --

    @classmethod
    def _assemble(
        cls,
        xml_defs: list[dict[str, Any]],
        existing_beans: list[dict[str, Any]],
        config_files: list[dict[str, Any]],
        config_properties: list[dict[str, Any]],
    ) -> _Assembled:
        index: dict[str, set[str]] = {}
        id_to_name: dict[str, str] = {}

        def add(token: str | None, bean_gid: str) -> None:
            if token:
                index.setdefault(token, set()).add(bean_gid)

        for definition in xml_defs:
            add(definition["bean_id"], definition["id"])
            add(definition["bean_name"], definition["id"])
            for alias in definition.get("aliases") or []:
                add(alias, definition["id"])
            id_to_name[definition["id"]] = definition["bean_name"]
        for bean in existing_beans:
            add(bean["name"], bean["id"])
            id_to_name[bean["id"]] = bean["name"]

        config_ids_by_key: dict[str, list[str]] = {}
        for prop in config_properties:
            config_ids_by_key.setdefault(prop["key"], []).append(prop["id"])

        bean_rows: list[dict[str, Any]] = []
        stub_rows: dict[str, dict[str, str]] = {}
        is_bean_rows: list[dict[str, str]] = []
        injects: list[dict[str, Any]] = []
        binds: list[dict[str, str]] = []
        unresolved: dict[str, list[dict[str, str]]] = {}

        for definition in xml_defs:
            bean_gid = definition["id"]
            bean_rows.append(
                {
                    "id": bean_gid,
                    "name": definition["bean_name"],
                    "stereotype": "XmlBean",
                    "scope": definition.get("scope"),
                    "primary": bool(definition.get("primary")),
                    "abstract": bool(definition.get("abstract")),
                    "bean_type": definition.get("class_name"),
                    "source_path": definition["source_path"],
                }
            )
            if definition.get("class_name"):
                is_bean_rows.append({"class_name": definition["class_name"], "bean_id": bean_gid})

            for ref, via, prop in cls._wiring(definition):
                cls._wire(
                    bean_gid, ref, via, prop, index, id_to_name, stub_rows, injects, unresolved
                )

            for key in definition.get("value_placeholder_keys") or []:
                for config_id in config_ids_by_key.get(key, []):
                    binds.append({"from": bean_gid, "to": config_id})

        for row in bean_rows:
            row["unresolved_injections"] = json.dumps(unresolved.get(row["id"], []))

        return _Assembled(
            bean_rows,
            list(stub_rows.values()),
            is_bean_rows,
            injects,
            binds,
            cls._imports_context(config_files),
        )

    @staticmethod
    def _wiring(definition: dict[str, Any]) -> list[tuple[str, str, str | None]]:
        wiring: list[tuple[str, str, str | None]] = [
            (ref, "xml-constructor", None) for ref in definition.get("constructor_arg_refs") or []
        ]
        names = definition.get("property_names") or []
        refs = definition.get("property_refs") or []
        wiring.extend(
            (ref, "xml-property", names[index] if index < len(names) else None)
            for index, ref in enumerate(refs)
        )
        return wiring

    @staticmethod
    def _wire(
        source_gid: str,
        ref: str,
        via: str,
        prop: str | None,
        index: dict[str, set[str]],
        id_to_name: dict[str, str],
        stub_rows: dict[str, dict[str, str]],
        injects: list[dict[str, Any]],
        unresolved: dict[str, list[dict[str, str]]],
    ) -> None:
        candidates = set(index.get(ref, set()))
        candidates.discard(source_gid)
        if len(candidates) == 1:
            injects.append(
                {"from": source_gid, "to": next(iter(candidates)), "via": via, "property": prop}
            )
            return
        if not candidates:
            stub_id = f"xml-stub::{ref}"
            stub_rows.setdefault(stub_id, {"id": stub_id, "name": ref})
            injects.append({"from": source_gid, "to": stub_id, "via": via, "property": prop})
            return
        names = sorted(id_to_name.get(candidate, candidate) for candidate in candidates)
        unresolved.setdefault(source_gid, []).append(
            {"ref": ref, "via": via, "reason": "ambiguous: " + ", ".join(names)}
        )

    # -- <import resource> / <context:property-placeholder> --

    @classmethod
    def _imports_context(cls, config_files: list[dict[str, Any]]) -> list[dict[str, str]]:
        xml_paths = [cf["path"] for cf in config_files if cf.get("format") == "spring-xml"]
        property_paths = [
            cf["path"] for cf in config_files if cf.get("format") in ("properties", "yaml")
        ]
        pairs: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for config_file in config_files:
            if config_file.get("format") != "spring-xml":
                continue
            importer = config_file["path"]
            wanted = [
                (config_file.get("import_resources") or [], xml_paths, "import"),
                (
                    config_file.get("placeholder_locations") or [],
                    property_paths,
                    "property-placeholder",
                ),
            ]
            for raw_values, candidates, kind in wanted:
                for raw in raw_values:
                    target = cls._match_path(raw, importer, candidates)
                    if target is None or target == importer:
                        continue
                    key = (importer, target, kind)
                    if key not in seen:
                        seen.add(key)
                        pairs.append({"from": importer, "to": target, "kind": kind})
        return pairs

    @staticmethod
    def _match_path(raw: str, importer: str, candidates: list[str]) -> str | None:
        cleaned = raw.strip()
        for prefix in _CLASSPATH_PREFIXES:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :]
        cleaned = cleaned.lstrip("/")
        if not cleaned or "${" in cleaned:
            return None
        cleaned = cleaned.replace("\\", "/")
        resolved = os.path.normpath(os.path.join(os.path.dirname(importer), cleaned))
        for candidate in candidates:
            if os.path.normpath(candidate) == resolved:
                return candidate
        for candidate in candidates:
            if os.path.normpath(candidate).replace(os.sep, "/").endswith("/" + cleaned):
                return candidate
        basename = os.path.basename(cleaned)
        for candidate in candidates:
            if os.path.basename(candidate) == basename:
                return candidate
        return None
