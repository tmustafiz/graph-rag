import json
import logging
import re
from typing import Any, LiteralString, NamedTuple, cast

from neo4j import Driver, ManagedTransaction

logger = logging.getLogger(__name__)

# Simple names of the built-in Spring stereotypes (matched on `Annotation.name`
# or the tail of `Annotation.fqn`).
_STEREOTYPES = {
    "Component",
    "Service",
    "Repository",
    "Controller",
    "RestController",
    "Configuration",
    "SpringBootApplication",
    "ConfigurationProperties",
}
_INJECT_MARKERS = {"Autowired", "Inject", "Resource"}
# Java modifier keywords that can precede a return type in a `@Bean` method
# signature — stripped so `bean_type` is the type, not `"Bean public DataSource"`.
_MODIFIERS = {
    "public",
    "private",
    "protected",
    "static",
    "final",
    "abstract",
    "synchronized",
    "native",
    "default",
    "transient",
    "volatile",
}
_VALUE_PLACEHOLDER = re.compile(r"\$\{([^:}]+)(?::[^}]*)?\}")
_GENERIC = re.compile(r"([\w.]+)\s*<\s*(.+)\s*>$")
_COLLECTION_TYPES = {"List", "Set", "Collection", "Iterable"}
_PROVIDER_TYPES = {"ObjectProvider", "Provider"}

_CLEAR = "MATCH (b:Bean) DETACH DELETE b"

_TYPE_ANNOTATIONS = """
MATCH (owner:CodeEntity)-[:ANNOTATED_WITH]->(a:Annotation {target: 'type'})
RETURN owner.qualified_name AS qn, owner.name AS name, owner.kind AS kind,
       collect({name: a.name, fqn: a.fqn, attributes: a.attributes}) AS annos
"""

_MEMBER_ANNOTATIONS = """
MATCH (m:CodeEntity)-[:ANNOTATED_WITH]->(a:Annotation)
WHERE a.target IN ['method', 'constructor', 'field']
OPTIONAL MATCH (parent:CodeEntity)-[:CONTAINS]->(m)
RETURN m.qualified_name AS qn, m.name AS name, a.target AS target,
       m.signature AS signature, parent.qualified_name AS parent_qn,
       collect({name: a.name, fqn: a.fqn, attributes: a.attributes}) AS annos
"""

_CONSTRUCTORS = """
MATCH (t:CodeEntity)-[:CONTAINS]->(c:CodeEntity {kind: 'constructor'})
RETURN t.qualified_name AS type_qn, collect(c.qualified_name) AS ctor_qns
"""

_HIERARCHY = """
MATCH (sub:CodeEntity)-[:EXTENDS|IMPLEMENTS]->(super:CodeEntity)
RETURN sub.qualified_name AS sub, super.qualified_name AS super
"""

_CONFIG_PROPERTIES = "MATCH (cp:ConfigProperty) RETURN cp.id AS id, cp.key AS key"

_MERGE_BEANS = """
UNWIND $rows AS row
MERGE (b:Bean {id: row.id})
SET b.name = row.name, b.stereotype = row.stereotype, b.scope = row.scope,
    b.primary = row.primary, b.bean_type = row.bean_type,
    b.unresolved_injections = row.unresolved_injections
WITH b, row
MATCH (c:CodeEntity {qualified_name: row.code_qn})
MERGE (c)-[:IS_BEAN]->(b)
"""

_MERGE_INJECTS = """
UNWIND $rows AS row
MATCH (s:Bean {id: row.from})
MATCH (t:Bean {id: row.to})
MERGE (s)-[r:INJECTS]->(t)
SET r.via = row.via, r.qualifier = row.qualifier, r.multiplicity = row.multiplicity
"""

_MERGE_PRODUCES = """
UNWIND $rows AS row
MATCH (config:Bean {id: row.from})
MATCH (produced:Bean {id: row.to})
MERGE (config)-[:PRODUCES]->(produced)
"""

_MERGE_BINDS = """
UNWIND $rows AS row
MATCH (b:Bean {id: row.from})
MATCH (cp:ConfigProperty {id: row.to})
MERGE (b)-[:BINDS]->(cp)
"""


class _Assembled(NamedTuple):
    bean_rows: list[dict[str, Any]]
    produces: list[dict[str, str]]
    injects: list[dict[str, Any]]
    binds: list[dict[str, str]]


class SpringBeanResolver:
    """After a directory ingest, derives the Spring bean graph from the
    `Annotation` / `CodeEntity` / `EXTENDS`-`IMPLEMENTS` / `ConfigProperty`
    layers already in Neo4j.

    * Stereotyped classes (`@Component` / `@Service` / … / one level of custom
      meta-annotated stereotype) and `@Bean` factory methods become
      `(:Bean {id, name, stereotype, scope, primary, bean_type})`, linked
      `(:CodeEntity)-[:IS_BEAN]->(:Bean)`; a `@Configuration` bean
      `-[:PRODUCES]->` each of its `@Bean` methods.
    * Constructor parameters (incl. the Lombok `@RequiredArgsConstructor`
      synthetic constructor), `@Autowired` / `@Inject` / `@Resource` fields and
      setters resolve to a target `Bean` **by type** — the declared type or,
      for `List<X>` / `Optional<X>` / `ObjectProvider<X>`, the element type,
      matched against each bean's own type and its supertypes — then narrowed
      by `@Qualifier` / `@Named`. A unique match becomes an
      `(:Bean)-[:INJECTS {via, qualifier, multiplicity}]->(:Bean)` edge; zero
      or several are recorded on `Bean.unresolved_injections` (JSON) with a
      reason, never guessed.
    * `@Value("${key:default}")` and `@ConfigurationProperties(prefix=…)` add
      `(:Bean)-[:BINDS]->(:ConfigProperty)` edges.

    Rebuilt from scratch each run (every `:Bean` is deleted first), so it is
    idempotent and never leaves a stale bean behind.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def resolve(self) -> dict[str, int]:
        with self._driver.session() as session:
            result = session.execute_write(self._rebuild)
        logger.info("spring bean graph resolved: %s", result)
        return result

    @classmethod
    def _rebuild(cls, tx: ManagedTransaction) -> dict[str, int]:
        tx.run(cast(LiteralString, _CLEAR))
        assembled = cls._assemble(
            [dict(row) for row in tx.run(cast(LiteralString, _TYPE_ANNOTATIONS))],
            [dict(row) for row in tx.run(cast(LiteralString, _MEMBER_ANNOTATIONS))],
            [dict(row) for row in tx.run(cast(LiteralString, _CONSTRUCTORS))],
            [dict(row) for row in tx.run(cast(LiteralString, _HIERARCHY))],
            [dict(row) for row in tx.run(cast(LiteralString, _CONFIG_PROPERTIES))],
        )
        if assembled.bean_rows:
            tx.run(cast(LiteralString, _MERGE_BEANS), rows=assembled.bean_rows)
        if assembled.produces:
            tx.run(cast(LiteralString, _MERGE_PRODUCES), rows=assembled.produces)
        if assembled.injects:
            tx.run(cast(LiteralString, _MERGE_INJECTS), rows=assembled.injects)
        if assembled.binds:
            tx.run(cast(LiteralString, _MERGE_BINDS), rows=assembled.binds)
        return {
            "beans": len(assembled.bean_rows),
            "injects": len(assembled.injects),
            "produces": len(assembled.produces),
            "binds": len(assembled.binds),
        }

    # -- assembly (pure — unit-tested without Neo4j) --

    @classmethod
    def _assemble(
        cls,
        type_rows: list[dict[str, Any]],
        member_rows: list[dict[str, Any]],
        ctor_rows: list[dict[str, Any]],
        hierarchy_rows: list[dict[str, Any]],
        config_rows: list[dict[str, Any]],
    ) -> _Assembled:
        parents: dict[str, list[str]] = {}
        for row in hierarchy_rows:
            parents.setdefault(row["sub"], []).append(row["super"])
        constructors = {row["type_qn"]: row["ctor_qns"] for row in ctor_rows}
        config_keys = [(row["id"], row["key"]) for row in config_rows]
        custom = cls._custom_stereotypes(type_rows)

        beans: dict[str, dict[str, Any]] = {}
        produces: list[dict[str, str]] = []
        for row in type_rows:
            stereotype = cls._match_stereotype(row["annos"], custom)
            if stereotype is not None:
                beans[row["qn"]] = {
                    "id": row["qn"],
                    "code_qn": row["qn"],
                    "bean_type": row["qn"],
                    "name": cls._explicit_name(row["annos"], stereotype)
                    or cls._decapitalize(row["name"]),
                    "stereotype": stereotype,
                    "scope": cls._named_attr(row["annos"], "Scope"),
                    "primary": cls._has_anno(row["annos"], "Primary"),
                }
        for row in member_rows:
            if row["target"] != "method" or not cls._has_anno(row["annos"], "Bean"):
                continue
            if row["parent_qn"] not in beans:
                continue
            beans[row["qn"]] = {
                "id": row["qn"],
                "code_qn": row["qn"],
                "bean_type": cls._return_type(row["signature"], row["name"]),
                "name": cls._named_attr(row["annos"], "Bean") or row["name"],
                "stereotype": "Bean",
                "scope": cls._named_attr(row["annos"], "Scope"),
                "primary": cls._has_anno(row["annos"], "Primary"),
            }
            produces.append({"from": row["parent_qn"], "to": row["qn"]})

        type_index = cls._type_index(beans, parents)
        injects: list[dict[str, Any]] = []
        binds: list[dict[str, str]] = []
        unresolved: dict[str, list[dict[str, str]]] = {}

        autowired_ctors = {
            row["qn"]
            for row in member_rows
            if row["target"] == "constructor" and cls._has_anno(row["annos"], "Autowired")
        }
        for bean_id, bean in beans.items():
            if bean["stereotype"] == "Bean":
                continue
            for param_type in cls._constructor_params(
                constructors.get(bean["code_qn"], []), autowired_ctors
            ):
                cls._resolve_injection(
                    bean_id, param_type, "constructor", None, type_index, beans, injects, unresolved
                )

        for row in member_rows:
            owner = row["parent_qn"]
            if owner not in beans:
                continue
            if row["target"] == "field":
                if cls._has_any(row["annos"], _INJECT_MARKERS):
                    cls._resolve_injection(
                        owner,
                        cls._field_type(row["signature"], row["name"]),
                        "field",
                        cls._qualifier(row["annos"]),
                        type_index,
                        beans,
                        injects,
                        unresolved,
                    )
                value_key = cls._value_key(cls._named_attr(row["annos"], "Value"))
                if value_key is not None:
                    binds.extend(
                        {"from": owner, "to": cp_id}
                        for cp_id, key in config_keys
                        if key == value_key
                    )
            elif (
                row["target"] == "method"
                and str(row["name"]).startswith("set")
                and cls._has_anno(row["annos"], "Autowired")
            ):
                for param_type in cls._parameter_types(row["qn"]):
                    cls._resolve_injection(
                        owner,
                        param_type,
                        "setter",
                        cls._qualifier(row["annos"]),
                        type_index,
                        beans,
                        injects,
                        unresolved,
                    )

        for row in type_rows:
            if row["qn"] not in beans:
                continue
            prefix = cls._named_attr(row["annos"], "ConfigurationProperties", "prefix", "value")
            if prefix:
                binds.extend(
                    {"from": row["qn"], "to": cp_id}
                    for cp_id, key in config_keys
                    if key == prefix or key.startswith(f"{prefix}.")
                )

        bean_rows = [
            {**bean, "unresolved_injections": json.dumps(unresolved.get(bean_id, []))}
            for bean_id, bean in beans.items()
        ]
        return _Assembled(bean_rows, produces, injects, binds)

    @classmethod
    def _resolve_injection(
        cls,
        source_bean_id: str,
        declared_type: str,
        via: str,
        qualifier: str | None,
        type_index: dict[str, set[str]],
        beans: dict[str, dict[str, Any]],
        injects: list[dict[str, Any]],
        unresolved: dict[str, list[dict[str, str]]],
    ) -> None:
        multiplicity, element = cls._multiplicity(declared_type)
        candidates = set(type_index.get(element, set()))
        candidates |= set(type_index.get(cls._simple_name(element), set()))
        candidates.discard(source_bean_id)
        if qualifier:
            candidates = {b for b in candidates if beans[b]["name"] == qualifier}
        if len(candidates) == 1:
            injects.append(
                {
                    "from": source_bean_id,
                    "to": next(iter(candidates)),
                    "via": via,
                    "qualifier": qualifier,
                    "multiplicity": multiplicity,
                }
            )
            return
        reason = (
            "no matching bean"
            if not candidates
            else "ambiguous: " + ", ".join(sorted(beans[b]["name"] for b in candidates))
        )
        unresolved.setdefault(source_bean_id, []).append(
            {"type": element, "via": via, "reason": reason}
        )

    # -- pure helpers --

    @staticmethod
    def _decapitalize(name: str) -> str:
        if len(name) >= 2 and name[1].isupper():  # `URLShortener` → stays as-is
            return name
        return name[:1].lower() + name[1:]

    @staticmethod
    def _simple_name(qualified_name: str) -> str:
        tail = qualified_name.rsplit(".", 1)[-1].rsplit("#", 1)[-1]
        return tail.split("<", 1)[0].strip()

    @staticmethod
    def _parameter_types(qualified_name: str) -> list[str]:
        start = qualified_name.find("(")
        end = qualified_name.rfind(")")
        if start == -1 or end <= start + 1:
            return []
        parts: list[str] = []
        depth = 0
        current = ""
        for char in qualified_name[start + 1 : end]:
            if char == "<":
                depth += 1
            elif char == ">":
                depth -= 1
            if char == "," and depth == 0:
                parts.append(current.strip())
                current = ""
            else:
                current += char
        if current.strip():
            parts.append(current.strip())
        return parts

    @classmethod
    def _multiplicity(cls, declared_type: str) -> tuple[str, str]:
        declared_type = declared_type.strip()
        if declared_type.endswith("[]"):
            return "collection", declared_type[:-2].strip()
        match = _GENERIC.match(declared_type)
        if match is None:
            return "single", declared_type
        container = cls._simple_name(match.group(1))
        element = match.group(2).split(",")[-1].strip()  # Map<K,V> → V
        if container in _COLLECTION_TYPES:
            return "collection", element
        if container in _PROVIDER_TYPES:
            return "provider", element
        if container == "Optional":
            return "optional", element
        return "single", declared_type

    @staticmethod
    def _value_key(raw: str | None) -> str | None:
        if not raw:
            return None
        match = _VALUE_PLACEHOLDER.search(raw)
        return match.group(1).strip() if match else None

    @staticmethod
    def _attribute(annotation: dict[str, Any], *names: str) -> Any:
        raw = annotation.get("attributes")
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return next((parsed[name] for name in names if name in parsed), None)

    @classmethod
    def _custom_stereotypes(cls, type_rows: list[dict[str, Any]]) -> set[str]:
        stereotypes: set[str] = set()
        for row in type_rows:
            if row["kind"] == "annotation" and cls._match_stereotype(row["annos"], set()):
                stereotypes.add(row["qn"])
                stereotypes.add(cls._simple_name(row["qn"]))
        return stereotypes

    @staticmethod
    def _match_stereotype(annos: list[dict[str, Any]], custom: set[str]) -> str | None:
        for anno in annos:
            name = anno.get("name") or ""
            fqn = anno.get("fqn") or ""
            if name in _STEREOTYPES or fqn.rsplit(".", 1)[-1] in _STEREOTYPES:
                return name
            if name in custom or fqn in custom:
                return name
        return None

    @classmethod
    def _explicit_name(cls, annos: list[dict[str, Any]], stereotype: str) -> str | None:
        for anno in annos:
            if (anno.get("name") or "") == stereotype:
                value = cls._attribute(anno, "value", "name")
                if isinstance(value, str) and value:
                    return value
        return None

    @classmethod
    def _named_attr(
        cls, annos: list[dict[str, Any]], anno_name: str, *attr_names: str
    ) -> str | None:
        wanted = attr_names or ("value",)
        for anno in annos:
            if (anno.get("name") or "") == anno_name:
                value = cls._attribute(anno, *wanted)
                if isinstance(value, str) and value:
                    return value
        return None

    @classmethod
    def _qualifier(cls, annos: list[dict[str, Any]]) -> str | None:
        return cls._named_attr(annos, "Qualifier") or cls._named_attr(annos, "Named")

    @staticmethod
    def _has_anno(annos: list[dict[str, Any]], anno_name: str) -> bool:
        return any((anno.get("name") or "") == anno_name for anno in annos)

    @staticmethod
    def _has_any(annos: list[dict[str, Any]], names: set[str]) -> bool:
        return any((anno.get("name") or "") in names for anno in annos)

    @staticmethod
    def _field_type(signature: str | None, field_name: str) -> str:
        if not signature:
            return "?"
        text = signature.strip()
        if text.endswith(field_name):
            text = text[: -len(field_name)].strip()
        return text or "?"

    @staticmethod
    def _return_type(signature: str | None, method_name: str) -> str:
        if not signature:
            return "?"
        # The type token directly before `<method_name>(` — robust to leading
        # `@Bean(...)` / modifiers that a naive `split("(")` would trip on. The
        # `[\w.$<>, ]` char class also swallows any `public` / `static` between
        # the annotation and the type, so drop modifier tokens and keep the
        # last real token (#115).
        match = re.search(rf"([\w.$<>, ]+?)\s+{re.escape(method_name)}\s*\(", signature)
        if match is None:
            return "?"
        tokens = [token for token in match.group(1).split() if token not in _MODIFIERS]
        # a bare leading annotation name (`@` is a regex delimiter, so only the
        # one adjacent to the type leaks in) sits before the real type
        if len(tokens) >= 2:
            tokens = tokens[1:]
        return " ".join(tokens) if tokens else "?"

    @classmethod
    def _constructor_params(cls, ctor_qns: list[str], autowired: set[str]) -> list[str]:
        chosen = next((qn for qn in ctor_qns if qn in autowired), None)
        if chosen is None and len(ctor_qns) == 1:
            chosen = ctor_qns[0]
        return cls._parameter_types(chosen) if chosen else []

    @classmethod
    def _type_index(
        cls, beans: dict[str, dict[str, Any]], parents: dict[str, list[str]]
    ) -> dict[str, set[str]]:
        index: dict[str, set[str]] = {}

        def add(token: str, bean_id: str) -> None:
            if token:
                index.setdefault(token, set()).add(bean_id)

        for bean_id, bean in beans.items():
            own = bean["bean_type"]
            add(own, bean_id)
            add(cls._simple_name(own), bean_id)
            seen: set[str] = set()
            queue = list(parents.get(own, []))
            while queue:
                supertype = queue.pop()
                if supertype in seen:
                    continue
                seen.add(supertype)
                add(supertype, bean_id)
                add(cls._simple_name(supertype), bean_id)
                queue.extend(parents.get(supertype, []))
        return index
