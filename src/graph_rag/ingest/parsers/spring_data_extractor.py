import re
from typing import Any

from ..models import Annotation, CodeEntity, JpaEntity, SpringDataRepository

# Recognised Spring Data base interfaces (matched on simple name).
SPRING_DATA_BASES = {
    "Repository",
    "CrudRepository",
    "ListCrudRepository",
    "PagingAndSortingRepository",
    "ListPagingAndSortingRepository",
    "JpaRepository",
    "JpaSpecificationExecutor",
    "QuerydslPredicateExecutor",
    "ReactiveCrudRepository",
    "ReactiveSortingRepository",
    "RxJava3CrudRepository",
    "R2dbcRepository",
    "MongoRepository",
    "ReactiveMongoRepository",
    "CassandraRepository",
    "ReactiveCassandraRepository",
    "ElasticsearchRepository",
    "ReactiveElasticsearchRepository",
}
REACTIVE_BASES = {
    "ReactiveCrudRepository",
    "ReactiveSortingRepository",
    "RxJava3CrudRepository",
    "R2dbcRepository",
    "ReactiveMongoRepository",
    "ReactiveCassandraRepository",
    "ReactiveElasticsearchRepository",
}

_ENTITY_KINDS = {
    "Entity": "entity",
    "Embeddable": "embeddable",
    "MappedSuperclass": "mapped-superclass",
}
_ASSOCIATIONS = {
    "OneToMany": "one-to-many",
    "ManyToOne": "many-to-one",
    "ManyToMany": "many-to-many",
    "OneToOne": "one-to-one",
}
_ID_MARKERS = {"Id", "EmbeddedId"}

# Methods inherited from a CRUD base that a repo may redeclare verbatim.
_CRUD_METHODS = {
    "save",
    "saveAll",
    "saveAndFlush",
    "saveAllAndFlush",
    "flush",
    "findById",
    "existsById",
    "findAll",
    "findAllById",
    "count",
    "delete",
    "deleteById",
    "deleteAll",
    "deleteAllById",
    "deleteAllInBatch",
    "deleteAllByIdInBatch",
    "getOne",
    "getById",
    "getReferenceById",
}

_DERIVED_SUBJECT = re.compile(
    r"^(find|read|get|query|search|stream|count|exists|delete|remove)(?:\w*?)By(.+)$"
)
# Operator keywords Spring appends after a property path in a derived query.
_OPERATOR_SUFFIXES = (
    "IsNotNull",
    "IsNull",
    "NotNull",
    "IsNotEmpty",
    "IsEmpty",
    "NotEmpty",
    "LessThanEqual",
    "LessThan",
    "GreaterThanEqual",
    "GreaterThan",
    "IsBetween",
    "Between",
    "IsBefore",
    "Before",
    "IsAfter",
    "After",
    "NotLike",
    "IsLike",
    "Like",
    "IsNotContaining",
    "NotContaining",
    "IsContaining",
    "Containing",
    "Contains",
    "IsStartingWith",
    "StartingWith",
    "StartsWith",
    "IsEndingWith",
    "EndingWith",
    "EndsWith",
    "IsNotIn",
    "NotIn",
    "IsIn",
    "In",
    "IgnoreCase",
    "AllIgnoreCase",
    "IsTrue",
    "IsFalse",
    "True",
    "False",
    "IsNot",
    "Not",
    "Is",
    "Equals",
)
_GENERIC = re.compile(r"<\s*(.+)\s*>")
# PascalCase word boundary: `OrderId` -> `Order` | `Id`, `HTTPServer` ->
# `HTTP` | `Server`. Used to tokenise a derived-query subject so `And` / `Or`
# are only treated as connectors when they are a whole segment, not letters
# inside a property name (`OrderId`, `BrandName`, `OrgUnit`).
_PASCAL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_CONNECTORS = {"And", "Or"}


class SpringDataExtractor:
    """Derives `JpaEntity` + `SpringDataRepository` records from a parsed
    `.java` file's `CodeEntity` + `Annotation` lists.

    Pure: everything comes from the already-built entities / annotations, plus
    `repo_bindings` — the `JpaRepository<Order, Long>` generic type arguments,
    which `JavaParser` reads from the AST because `CodeEntity.extends_types`
    strips generics. Method names are classified best-effort (`@Query` →
    `jpql` / `native`, `@Modifying`, `@Procedure`, CRUD names → `inherited`,
    otherwise `derived` with a best-effort property-path parse that never
    raises).
    """

    @classmethod
    def extract(
        cls,
        entities: list[CodeEntity],
        annotations: list[Annotation],
        repo_bindings: dict[str, dict[str, Any]],
    ) -> tuple[list[JpaEntity], list[SpringDataRepository]]:
        annos_by_owner: dict[str, list[Annotation]] = {}
        for annotation in annotations:
            annos_by_owner.setdefault(annotation.owner_qualified_name, []).append(annotation)

        types = {
            entity.qualified_name: entity
            for entity in entities
            if entity.kind in ("class", "interface")
        }
        fields_by_parent: dict[str, list[CodeEntity]] = {}
        methods_by_parent: dict[str, list[CodeEntity]] = {}
        for entity in entities:
            if not entity.parent_qualified_name:
                continue
            if entity.kind == "field":
                fields_by_parent.setdefault(entity.parent_qualified_name, []).append(entity)
            elif entity.kind == "method":
                methods_by_parent.setdefault(entity.parent_qualified_name, []).append(entity)

        jpa_entities = [
            cls._build_entity(qn, type_entity, annos_by_owner, fields_by_parent.get(qn, []))
            for qn, type_entity in types.items()
            if cls._entity_kind(cls._type_annos(annos_by_owner, qn)) is not None
        ]
        repositories = [
            cls._build_repository(
                qn, type_entity, annos_by_owner, methods_by_parent.get(qn, []), repo_bindings
            )
            for qn, type_entity in types.items()
            if cls._is_repository(qn, cls._type_annos(annos_by_owner, qn), repo_bindings)
        ]
        return jpa_entities, [repo for repo in repositories if repo is not None]

    # -- JPA entities --

    @classmethod
    def _build_entity(
        cls,
        qualified_name: str,
        type_entity: CodeEntity,
        annos_by_owner: dict[str, list[Annotation]],
        fields: list[CodeEntity],
    ) -> JpaEntity:
        type_annos = cls._type_annos(annos_by_owner, qualified_name)
        kind = cls._entity_kind(type_annos) or "entity"
        table = cls._string_attr(type_annos, "Table", "name") or type_entity.name

        id_fields: list[str] = []
        assoc_fields: list[str] = []
        assoc_targets: list[str] = []
        assoc_kinds: list[str] = []
        assoc_mapped_by: list[str] = []
        for field in fields:
            field_annos = annos_by_owner.get(field.qualified_name, [])
            names = {annotation.name for annotation in field_annos}
            if names & _ID_MARKERS:
                id_fields.append(field.name)
            for annotation in field_annos:
                kind_name = _ASSOCIATIONS.get(annotation.name)
                if kind_name is None:
                    continue
                assoc_fields.append(field.name)
                assoc_targets.append(cls._element_type(field.signature, field.name))
                assoc_kinds.append(kind_name)
                assoc_mapped_by.append(str(annotation.attributes.get("mappedBy") or ""))

        return JpaEntity(
            qualified_name=qualified_name,
            simple_name=type_entity.name,
            kind=kind,
            table=table,
            id_fields=id_fields,
            association_fields=assoc_fields,
            association_targets=assoc_targets,
            association_kinds=assoc_kinds,
            association_mapped_by=assoc_mapped_by,
        )

    @staticmethod
    def _entity_kind(type_annos: list[Annotation]) -> str | None:
        for annotation in type_annos:
            if annotation.name in _ENTITY_KINDS:
                return _ENTITY_KINDS[annotation.name]
        return None

    @staticmethod
    def _element_type(signature: str | None, field_name: str) -> str:
        if not signature:
            return "?"
        text = signature.strip()
        if text.endswith(field_name):
            text = text[: -len(field_name)].strip()
        match = _GENERIC.search(text)
        if match:
            text = match.group(1).split(",")[-1].strip()
        else:
            text = text.split("<", 1)[0].strip()
        return text.rsplit(".", 1)[-1] if text else "?"

    # -- repositories --

    @classmethod
    def _is_repository(
        cls,
        qualified_name: str,
        type_annos: list[Annotation],
        repo_bindings: dict[str, dict[str, Any]],
    ) -> bool:
        if any(annotation.name == "NoRepositoryBean" for annotation in type_annos):
            return False
        if qualified_name in repo_bindings:
            return True
        return any(annotation.name == "RepositoryDefinition" for annotation in type_annos)

    @classmethod
    def _build_repository(
        cls,
        qualified_name: str,
        type_entity: CodeEntity,
        annos_by_owner: dict[str, list[Annotation]],
        methods: list[CodeEntity],
        repo_bindings: dict[str, dict[str, Any]],
    ) -> SpringDataRepository | None:
        type_annos = cls._type_annos(annos_by_owner, qualified_name)
        binding = repo_bindings.get(qualified_name)
        repo_def = next((a for a in type_annos if a.name == "RepositoryDefinition"), None)
        if binding is None and repo_def is None:
            return None

        entity_type = (binding or {}).get("entity_type")
        id_type = (binding or {}).get("id_type")
        if repo_def is not None:
            entity_type = entity_type or cls._class_attr(repo_def, "domainClass")
            id_type = id_type or cls._class_attr(repo_def, "idClass")

        method_qns: list[str] = []
        method_names: list[str] = []
        method_kinds: list[str] = []
        method_texts: list[str] = []
        method_properties: list[str] = []
        for method in methods:
            kind, text, properties = cls._classify_method(
                method.name, annos_by_owner.get(method.qualified_name, [])
            )
            method_qns.append(method.qualified_name)
            method_names.append(method.name)
            method_kinds.append(kind)
            method_texts.append(text)
            method_properties.append(",".join(properties))

        return SpringDataRepository(
            qualified_name=qualified_name,
            simple_name=type_entity.name,
            base=(binding or {}).get("base") or "RepositoryDefinition",
            entity_type=entity_type,
            id_type=id_type,
            reactive=bool((binding or {}).get("reactive")),
            method_qns=method_qns,
            method_names=method_names,
            method_query_kinds=method_kinds,
            method_query_texts=method_texts,
            method_properties=method_properties,
        )

    @classmethod
    def _classify_method(
        cls, name: str, method_annos: list[Annotation]
    ) -> tuple[str, str, list[str]]:
        names = {annotation.name for annotation in method_annos}
        query = next((a for a in method_annos if a.name == "Query"), None)
        query_text = str(query.attributes.get("value") or "") if query is not None else ""
        # `@Modifying` (bulk update/delete, usually with a `@Query`) is the more
        # specific "this writes" signal — it wins the kind but keeps the text.
        if "Modifying" in names:
            return "modifying", query_text, []
        if "Procedure" in names:
            procedure = next(a for a in method_annos if a.name == "Procedure")
            text = procedure.attributes.get("value") or procedure.attributes.get("procedureName")
            return "procedure", str(text or ""), []
        if query is not None:
            kind = "native" if cls._is_true(query.attributes.get("nativeQuery")) else "jpql"
            return kind, query_text, []
        if name in _CRUD_METHODS:
            return "inherited", "", []
        return "derived", "", cls._derived_properties(name)

    @staticmethod
    def _derived_properties(name: str) -> list[str]:
        try:
            match = _DERIVED_SUBJECT.match(name)
            if match is None:
                return []
            body = re.split(r"OrderBy", match.group(2))[0]
            segments = _PASCAL_BOUNDARY.split(body)
            groups: list[list[str]] = [[]]
            for segment in segments:
                if segment in _CONNECTORS:
                    groups.append([])
                else:
                    groups[-1].append(segment)
            properties: list[str] = []
            for group in groups:
                token = "".join(group)
                changed = True
                while changed:
                    changed = False
                    for suffix in _OPERATOR_SUFFIXES:
                        if token.endswith(suffix) and len(token) > len(suffix):
                            token = token[: -len(suffix)]
                            changed = True
                if token:
                    properties.append(token[:1].lower() + token[1:])
            return properties
        except Exception:  # noqa: BLE001 - derived-name parsing is best-effort, never fatal
            return []

    # -- annotation helpers --

    @staticmethod
    def _type_annos(
        annos_by_owner: dict[str, list[Annotation]], qualified_name: str
    ) -> list[Annotation]:
        return [
            annotation
            for annotation in annos_by_owner.get(qualified_name, [])
            if annotation.target == "type"
        ]

    @staticmethod
    def _string_attr(annos: list[Annotation], anno_name: str, attr: str) -> str | None:
        for annotation in annos:
            if annotation.name == anno_name:
                value = annotation.attributes.get(attr)
                if isinstance(value, str) and value:
                    return value
        return None

    @staticmethod
    def _class_attr(annotation: Annotation, attr: str) -> str | None:
        value = annotation.attributes.get(attr)
        if isinstance(value, str) and value:
            return value.removesuffix(".class")
        return None

    @staticmethod
    def _is_true(value: Any) -> bool:
        return value is True or (isinstance(value, str) and value.strip().lower() == "true")
