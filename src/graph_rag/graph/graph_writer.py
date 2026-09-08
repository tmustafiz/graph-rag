from typing import LiteralString, cast

from neo4j import Driver, ManagedTransaction

from graph_rag.ingest.models import ParsedDocument

_BATCH_SIZE = 500

_MERGE_SOURCE = """
MERGE (s:Source {path: $path})
SET s.type = $type, s.content_hash = $content_hash,
    s.ingested_at = $ingested_at, s.version = $version
"""

_MERGE_SOURCE_IMPORTS = """
UNWIND $pairs AS pair
MATCH (importer:Source {path: pair.from})
MERGE (imported:Source {path: pair.to})
MERGE (importer)-[:IMPORTS]->(imported)
"""

_MERGE_SECTIONS = """
UNWIND $sections AS row
MERGE (sec:Section {id: row.id})
SET sec.title = row.title, sec.level = row.level, sec.breadcrumb = row.breadcrumb,
    sec.order = row.order, sec.start_page = row.start_page, sec.end_page = row.end_page
WITH sec, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:HAS_SECTION]->(sec)
WITH sec, row
FOREACH (_ IN CASE WHEN row.parent_id IS NOT NULL THEN [1] ELSE [] END |
    MERGE (parent:Section {id: row.parent_id})
    MERGE (parent)-[:PARENT_OF]->(sec)
)
"""

_MERGE_CHUNKS = """
UNWIND $chunks AS row
MERGE (c:Chunk {id: row.id})
SET c.text = row.text, c.token_count = row.token_count, c.content_hash = row.content_hash,
    c.start_page = row.start_page, c.end_page = row.end_page, c.embedding = row.embedding
WITH c, row
MATCH (sec:Section {id: row.section_id})
MERGE (sec)-[:HAS_CHUNK]->(c)
"""

_MERGE_NEXT = """
UNWIND $pairs AS pair
MATCH (a:Chunk {id: pair.from}), (b:Chunk {id: pair.to})
MERGE (a)-[:NEXT]->(b)
"""

_MERGE_CODE_ENTITIES = """
UNWIND $entities AS row
MERGE (e:CodeEntity {qualified_name: row.qualified_name})
SET e.name = row.name, e.kind = row.kind, e.language = row.language,
    e.embed_text = row.embed_text,
    e.file_path = row.file_path, e.start_line = row.start_line, e.end_line = row.end_line,
    e.signature = row.signature, e.docstring = row.docstring, e.embedding = row.embedding,
    e.synthetic = row.synthetic, e.origin = row.origin
WITH e, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(e)
WITH e, row
FOREACH (_ IN CASE WHEN row.parent_qualified_name IS NOT NULL THEN [1] ELSE [] END |
    MERGE (parent:CodeEntity {qualified_name: row.parent_qualified_name})
    MERGE (parent)-[:CONTAINS]->(e)
)
"""

_MERGE_ANNOTATIONS = """
UNWIND $rows AS row
MATCH (owner:CodeEntity {qualified_name: row.owner_qualified_name})
MERGE (a:Annotation {id: row.id})
SET a.owner_qualified_name = row.owner_qualified_name, a.target = row.target,
    a.fqn = row.fqn, a.name = row.name, a.attributes = row.attributes_json, a.line = row.line
MERGE (owner)-[:ANNOTATED_WITH]->(a)
"""

_MERGE_HTTP_ENDPOINTS = """
UNWIND $rows AS row
MERGE (h:HttpEndpoint {id: row.id})
SET h.http_method = row.http_method, h.path = row.path, h.framework = row.framework,
    h.produces = row.produces, h.consumes = row.consumes, h.params = row.params,
    h.bindings = row.bindings_json, h.embed_text = row.embed_text, h.embedding = row.embedding,
    h.handler_qualified_name = row.handler_qualified_name
WITH h, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(h)
WITH h, row
MATCH (handler:CodeEntity {qualified_name: row.handler_qualified_name})
MERGE (h)-[:HANDLED_BY]->(handler)
"""

_MERGE_CALLS = """
UNWIND $pairs AS pair
MATCH (caller:CodeEntity {qualified_name: pair.from})
MERGE (callee:CodeEntity {qualified_name: pair.to})
MERGE (caller)-[:CALLS]->(callee)
"""

_MERGE_IMPORTS = """
UNWIND $pairs AS pair
MATCH (importer:CodeEntity {qualified_name: pair.from})
MERGE (imported:CodeEntity {qualified_name: pair.to})
MERGE (importer)-[:IMPORTS]->(imported)
"""

_MERGE_RENDERS = """
UNWIND $pairs AS pair
MATCH (parent:CodeEntity {qualified_name: pair.from})
MERGE (child:CodeEntity {qualified_name: pair.to})
MERGE (parent)-[:RENDERS]->(child)
"""

_MERGE_EXTENDS = """
UNWIND $pairs AS pair
MATCH (sub:CodeEntity {qualified_name: pair.from})
MERGE (super:CodeEntity {qualified_name: pair.to})
MERGE (sub)-[:EXTENDS]->(super)
"""

_MERGE_IMPLEMENTS = """
UNWIND $pairs AS pair
MATCH (impl:CodeEntity {qualified_name: pair.from})
MERGE (iface:CodeEntity {qualified_name: pair.to})
MERGE (impl)-[:IMPLEMENTS]->(iface)
"""

_MERGE_READS = """
UNWIND $pairs AS pair
MATCH (routine:CodeEntity {qualified_name: pair.from})
MERGE (t:DbTable {qualified_name: pair.to})
MERGE (routine)-[:READS]->(t)
"""

_MERGE_WRITES = """
UNWIND $pairs AS pair
MATCH (routine:CodeEntity {qualified_name: pair.from})
MERGE (t:DbTable {qualified_name: pair.to})
MERGE (routine)-[:WRITES]->(t)
"""

_MERGE_TRIGGER_ON = """
UNWIND $pairs AS pair
MATCH (trigger:CodeEntity {qualified_name: pair.from})
MERGE (t:DbTable {qualified_name: pair.to})
MERGE (trigger)-[:ON]->(t)
"""

_MERGE_DB_TABLES = """
UNWIND $rows AS row
MERGE (t:DbTable {qualified_name: row.qualified_name})
SET t.name = row.name, t.schema_name = row.schema_name, t.file_path = row.file_path,
    t.embed_text = row.embed_text, t.embedding = row.embedding
WITH t, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(t)
"""

_MERGE_DB_COLUMNS = """
UNWIND $rows AS row
MERGE (col:DbColumn {qualified_name: row.qualified_name})
SET col.name = row.name, col.table_qualified_name = row.table_qualified_name,
    col.data_type = row.data_type, col.nullable = row.nullable,
    col.default = row.default, col.primary_key = row.primary_key
WITH col, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(col)
WITH col, row
MATCH (t:DbTable {qualified_name: row.table_qualified_name})
MERGE (t)-[:HAS_COLUMN]->(col)
"""

_MERGE_DB_VIEWS = """
UNWIND $rows AS row
MERGE (v:DbView {qualified_name: row.qualified_name})
SET v.name = row.name, v.schema_name = row.schema_name, v.materialized = row.materialized,
    v.file_path = row.file_path, v.embed_text = row.embed_text, v.embedding = row.embedding
WITH v, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(v)
"""

_MERGE_DB_INDEXES = """
UNWIND $rows AS row
MERGE (ix:DbIndex {qualified_name: row.qualified_name})
SET ix.name = row.name, ix.table_qualified_name = row.table_qualified_name,
    ix.columns = row.columns, ix.unique = row.unique
WITH ix, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(ix)
WITH ix, row
MATCH (t:DbTable {qualified_name: row.table_qualified_name})
MERGE (t)-[:HAS_INDEX]->(ix)
"""

_MERGE_COLUMN_REFERENCES = """
UNWIND $pairs AS pair
MATCH (col:DbColumn {qualified_name: pair.from})
MERGE (target:DbColumn {qualified_name: pair.to})
MERGE (col)-[:REFERENCES]->(target)
"""

_MERGE_TABLE_REFERENCES = """
UNWIND $pairs AS pair
MATCH (t:DbTable {qualified_name: pair.from})
MERGE (target:DbTable {qualified_name: pair.to})
MERGE (t)-[:REFERENCES]->(target)
"""

_MERGE_VIEW_DEPENDS_ON = """
UNWIND $pairs AS pair
MATCH (v:DbView {qualified_name: pair.from})
MERGE (target:DbTable {qualified_name: pair.to})
MERGE (v)-[:DEPENDS_ON]->(target)
"""

_MERGE_POLICY_RULES = """
UNWIND $rules AS row
MERGE (p:PolicyRule {id: row.id})
SET p.name = row.name, p.category = row.category, p.severity = row.severity,
    p.guideline = row.guideline, p.provider = row.provider, p.file_path = row.file_path,
    p.embed_text = row.embed_text, p.embedding = row.embedding
WITH p, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(p)
"""

_MERGE_APPLIES_TO = """
UNWIND $pairs AS pair
MATCH (p:PolicyRule {id: pair.from})
MERGE (c:Concept {name: pair.to})
SET c.type = "resource_type"
MERGE (p)-[:APPLIES_TO]->(c)
"""

_MERGE_CONFIG_FILES = """
UNWIND $rows AS row
MERGE (cf:ConfigFile {path: row.path})
SET cf.format = row.format, cf.scan_packages = row.scan_packages,
    cf.placeholder_locations = row.placeholder_locations,
    cf.import_resources = row.import_resources,
    cf.namespace_elements = row.namespace_elements
WITH cf
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(cf)
"""

_MERGE_SPRING_XML_BEANS = """
UNWIND $rows AS row
MERGE (b:SpringXmlBean {id: row.id})
SET b.source_path = row.source_path, b.bean_id = row.bean_id, b.bean_name = row.bean_name,
    b.class_name = row.class_name, b.profile = row.profile,
    b.scope = row.scope, b.parent = row.parent,
    b.factory_bean = row.factory_bean, b.factory_method = row.factory_method,
    b.primary = row.primary, b.abstract = row.abstract, b.lazy_init = row.lazy_init,
    b.aliases = row.aliases, b.depends_on = row.depends_on,
    b.constructor_arg_refs = row.constructor_arg_refs,
    b.property_names = row.property_names, b.property_refs = row.property_refs,
    b.value_placeholder_keys = row.value_placeholder_keys
WITH b, row
MATCH (cf:ConfigFile {path: row.source_path})
MERGE (cf)-[:DECLARES_BEAN]->(b)
"""

_MERGE_JPA_ENTITY_DEFS = """
UNWIND $rows AS row
MERGE (d:JpaEntityDef {qualified_name: row.qualified_name})
SET d.simple_name = row.simple_name, d.kind = row.kind, d.table = row.table,
    d.id_fields = row.id_fields, d.association_fields = row.association_fields,
    d.association_targets = row.association_targets, d.association_kinds = row.association_kinds,
    d.association_mapped_by = row.association_mapped_by
WITH d
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(d)
"""

_MERGE_SPRING_DATA_REPO_DEFS = """
UNWIND $rows AS row
MERGE (d:SpringDataRepoDef {qualified_name: row.qualified_name})
SET d.simple_name = row.simple_name, d.base = row.base, d.entity_type = row.entity_type,
    d.id_type = row.id_type, d.reactive = row.reactive, d.method_qns = row.method_qns,
    d.method_names = row.method_names, d.method_query_kinds = row.method_query_kinds,
    d.method_query_texts = row.method_query_texts, d.method_properties = row.method_properties
WITH d
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(d)
"""

_MERGE_CONFIG_PROPERTIES = """
UNWIND $rows AS row
MERGE (cp:ConfigProperty {id: row.id})
SET cp.file_path = row.file_path, cp.key = row.key, cp.value = row.value,
    cp.profile = row.profile, cp.origin_line = row.origin_line
WITH cp, row
MATCH (cf:ConfigFile {path: row.file_path})
MERGE (cf)-[:HAS_PROPERTY]->(cp)
"""

_MERGE_CONFIG_PROPERTY_REFERENCES = """
UNWIND $pairs AS pair
MATCH (cp:ConfigProperty {id: pair.from})
MATCH (target:ConfigProperty {id: pair.to})
MERGE (cp)-[:REFERENCES]->(target)
"""

# A Gradle root dir emits a Module row from both `build.gradle` (with
# group/version/packages) and `settings.gradle` (without) on the same path.
# coalesce / non-empty guards keep the second MERGE from nulling coordinates
# the first one populated (#119).
_MERGE_MODULES = """
UNWIND $rows AS row
MERGE (m:Module {path: row.path})
SET m.artifact = row.artifact,
    m.group = coalesce(row.group, m.group),
    m.version = coalesce(row.version, m.version),
    m.build_tool = coalesce(row.build_tool, m.build_tool),
    m.packages = CASE
        WHEN row.packages IS NOT NULL AND size(row.packages) > 0 THEN row.packages
        ELSE coalesce(m.packages, row.packages) END,
    m.source_roots = CASE
        WHEN row.source_roots IS NOT NULL AND size(row.source_roots) > 0 THEN row.source_roots
        ELSE coalesce(m.source_roots, row.source_roots) END
WITH m
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(m)
"""

_MERGE_EXTERNAL_ARTIFACTS = """
UNWIND $rows AS row
MERGE (e:ExternalArtifact {gav: row.gav})
SET e.group = row.group, e.artifact = row.artifact, e.version = row.version
"""

_MERGE_MODULE_DEPENDS_ON = """
UNWIND $pairs AS pair
MATCH (m:Module {path: pair.from})
MERGE (t:Module {path: pair.to})
MERGE (m)-[d:DEPENDS_ON]->(t)
SET d.scope = pair.scope
"""

_MERGE_MODULE_DEPENDS_ON_EXTERNAL = """
UNWIND $pairs AS pair
MATCH (m:Module {path: pair.from})
MERGE (e:ExternalArtifact {gav: pair.gav})
MERGE (m)-[d:DEPENDS_ON_EXTERNAL]->(e)
SET d.gav = pair.gav, d.scope = pair.scope
"""

_GET_SOURCE_CONTENT_HASH = """
MATCH (s:Source {path: $path})
RETURN s.content_hash AS content_hash
"""

# Reconciliation deletes stale children a Source no longer produces on
# re-parse (e.g. a deleted function, a removed heading) — run after every
# write so an updated Source never leaves orphaned graph state behind.
# Chunks are reconciled before Sections so a stale Section is never left
# holding chunks that were already removed by its own query.
_RECONCILE_CHUNKS = """
MATCH (:Source {path: $source_path})-[:HAS_SECTION]->(:Section)-[:HAS_CHUNK]->(c:Chunk)
WHERE NOT c.id IN $keep_ids
DETACH DELETE c
"""

_RECONCILE_SECTIONS = """
MATCH (:Source {path: $source_path})-[:HAS_SECTION]->(sec:Section)
WHERE NOT sec.id IN $keep_ids
DETACH DELETE sec
"""

# Deleting the entity also deletes its `Annotation` nodes: `DETACH DELETE e`
# alone drops only the `ANNOTATED_WITH` edge, orphaning the far node, which
# `_RECONCILE_ANNOTATIONS` (reachability-based) can then never see (#121).
_RECONCILE_CODE_ENTITIES = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(e:CodeEntity)
WHERE NOT e.qualified_name IN $keep_ids
OPTIONAL MATCH (e)-[:ANNOTATED_WITH]->(a:Annotation)
DETACH DELETE e, a
"""

# Annotations reachable from a CodeEntity this Source defines but no longer
# emitted (an `@Deprecated` removed, a field un-annotated); plus a sweep of any
# fully-orphaned `Annotation` (no owner edge) — self-heals leaks from earlier
# runs before the code-entity reconcile started deleting them.
_RECONCILE_ANNOTATIONS = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(:CodeEntity)-[:ANNOTATED_WITH]->(a:Annotation)
WHERE NOT a.id IN $keep_ids
DETACH DELETE a
"""

_SWEEP_ORPHAN_ANNOTATIONS = """
MATCH (a:Annotation)
WHERE NOT ()-[:ANNOTATED_WITH]->(a)
DELETE a
"""

_RECONCILE_HTTP_ENDPOINTS = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(h:HttpEndpoint)
WHERE NOT h.id IN $keep_ids
DETACH DELETE h
"""

_RECONCILE_POLICY_RULES = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(p:PolicyRule)
WHERE NOT p.id IN $keep_ids
DETACH DELETE p
"""

# A re-parsed build file that no longer declares a module drops the stale
# `Module` (its `DEPENDS_ON` edges go with the DETACH); shared
# `ExternalArtifact` nodes are left for the resolver / left harmless.
_RECONCILE_MODULES = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(m:Module)
WHERE NOT m.path IN $keep_ids
DETACH DELETE m
"""

# Config properties then their file — a re-parsed `application.yml` that drops a
# key (or a whole profile document) leaves no orphan `ConfigProperty` behind.
_RECONCILE_CONFIG_PROPERTIES = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(:ConfigFile)-[:HAS_PROPERTY]->(cp:ConfigProperty)
WHERE NOT cp.id IN $keep_ids
DETACH DELETE cp
"""

_RECONCILE_CONFIG_FILES = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(cf:ConfigFile)
WHERE NOT cf.path IN $keep_ids
DETACH DELETE cf
"""

# A re-parsed Spring XML context that drops a `<bean>` leaves no orphan
# `SpringXmlBean` behind; run before the config-file reconcile.
_RECONCILE_SPRING_XML_BEANS = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(:ConfigFile)-[:DECLARES_BEAN]->(b:SpringXmlBean)
WHERE NOT b.id IN $keep_ids
DETACH DELETE b
"""

# A re-parsed `.java` file that stops being a JPA entity / Spring Data
# repository drops its stale def node (the `SpringDataResolver` pass then
# re-derives the `:Repository` / `:JpaEntity` marks and edges).
_RECONCILE_JPA_ENTITY_DEFS = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(d:JpaEntityDef)
WHERE NOT d.qualified_name IN $keep_ids
DETACH DELETE d
"""

_RECONCILE_SPRING_DATA_REPO_DEFS = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(d:SpringDataRepoDef)
WHERE NOT d.qualified_name IN $keep_ids
DETACH DELETE d
"""

# One reconcile per `:Db*` label — a re-parsed migration file that no longer
# produces a table / column / view / index leaves no orphan behind.
_RECONCILE_DB_TABLES = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(n:DbTable)
WHERE NOT n.qualified_name IN $keep_ids
DETACH DELETE n
"""

_RECONCILE_DB_COLUMNS = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(n:DbColumn)
WHERE NOT n.qualified_name IN $keep_ids
DETACH DELETE n
"""

_RECONCILE_DB_VIEWS = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(n:DbView)
WHERE NOT n.qualified_name IN $keep_ids
DETACH DELETE n
"""

_RECONCILE_DB_INDEXES = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(n:DbIndex)
WHERE NOT n.qualified_name IN $keep_ids
DETACH DELETE n
"""


class GraphWriter:
    """Idempotently upserts a `ParsedDocument` into Neo4j."""

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def write(self, document: ParsedDocument) -> None:
        with self._driver.session() as session:
            session.execute_write(self._write_source, document)
            for batch in self._batched(self._source_import_pairs(document)):
                session.execute_write(self._write_source_imports, batch)
            for batch in self._batched([s.model_dump(mode="json") for s in document.sections]):
                session.execute_write(self._write_sections, document.source.path, batch)
            for batch in self._batched([c.model_dump(mode="json") for c in document.chunks]):
                session.execute_write(self._write_chunks, batch)
            for batch in self._batched(self._chunk_pairs(document)):
                session.execute_write(self._write_next, batch)
            for batch in self._batched([e.model_dump(mode="json") for e in document.code_entities]):
                session.execute_write(self._write_code_entities, document.source.path, batch)
            for batch in self._batched(self._annotation_rows(document)):
                session.execute_write(self._write_annotations, batch)
            for batch in self._batched(
                [e.model_dump(mode="json") for e in document.http_endpoints]
            ):
                session.execute_write(self._write_http_endpoints, document.source.path, batch)
            for batch in self._batched(self._call_pairs(document)):
                session.execute_write(self._write_calls, batch)
            for batch in self._batched(self._import_pairs(document)):
                session.execute_write(self._write_imports, batch)
            for batch in self._batched(self._render_pairs(document)):
                session.execute_write(self._write_renders, batch)
            for batch in self._batched(self._extends_pairs(document)):
                session.execute_write(self._write_extends, batch)
            for batch in self._batched(self._implements_pairs(document)):
                session.execute_write(self._write_implements, batch)
            for batch in self._batched([t.model_dump(mode="json") for t in document.db_tables]):
                session.execute_write(self._write_db_tables, document.source.path, batch)
            for batch in self._batched([c.model_dump(mode="json") for c in document.db_columns]):
                session.execute_write(self._write_db_columns, document.source.path, batch)
            for batch in self._batched([v.model_dump(mode="json") for v in document.db_views]):
                session.execute_write(self._write_db_views, document.source.path, batch)
            for batch in self._batched([i.model_dump(mode="json") for i in document.db_indexes]):
                session.execute_write(self._write_db_indexes, document.source.path, batch)
            for batch in self._batched(self._column_reference_pairs(document)):
                session.execute_write(self._write_column_references, batch)
            for batch in self._batched(self._table_reference_pairs(document)):
                session.execute_write(self._write_table_references, batch)
            for batch in self._batched(self._view_depends_on_pairs(document)):
                session.execute_write(self._write_view_depends_on, batch)
            for batch in self._batched(self._reads_pairs(document)):
                session.execute_write(self._write_reads, batch)
            for batch in self._batched(self._writes_pairs(document)):
                session.execute_write(self._write_writes, batch)
            for batch in self._batched(self._trigger_on_pairs(document)):
                session.execute_write(self._write_trigger_on, batch)
            for batch in self._batched([r.model_dump(mode="json") for r in document.policy_rules]):
                session.execute_write(self._write_policy_rules, document.source.path, batch)
            for batch in self._batched(self._applies_to_pairs(document)):
                session.execute_write(self._write_applies_to, batch)
            for batch in self._batched([f.model_dump(mode="json") for f in document.config_files]):
                session.execute_write(self._write_config_files, document.source.path, batch)
            for batch in self._batched(self._config_property_rows(document)):
                session.execute_write(self._write_config_properties, batch)
            for batch in self._batched(self._config_property_reference_pairs(document)):
                session.execute_write(self._write_config_property_references, batch)
            for batch in self._batched(
                [b.model_dump(mode="json") for b in document.spring_xml_beans]
            ):
                session.execute_write(self._write_spring_xml_beans, document.source.path, batch)
            for batch in self._batched([e.model_dump(mode="json") for e in document.jpa_entities]):
                session.execute_write(self._write_jpa_entity_defs, document.source.path, batch)
            for batch in self._batched(
                [r.model_dump(mode="json") for r in document.spring_data_repositories]
            ):
                session.execute_write(
                    self._write_spring_data_repo_defs, document.source.path, batch
                )
            for batch in self._batched([m.model_dump(mode="json") for m in document.modules]):
                session.execute_write(self._write_modules, document.source.path, batch)
            for batch in self._batched(
                [a.model_dump(mode="json") for a in document.external_artifacts]
            ):
                session.execute_write(self._write_external_artifacts, batch)
            for batch in self._batched(self._module_depends_on_pairs(document)):
                session.execute_write(self._write_module_depends_on, batch)
            for batch in self._batched(self._module_depends_on_external_pairs(document)):
                session.execute_write(self._write_module_depends_on_external, batch)
            session.execute_write(
                self._reconcile_chunks,
                document.source.path,
                [c.id for c in document.chunks],
            )
            session.execute_write(
                self._reconcile_sections,
                document.source.path,
                [s.id for s in document.sections],
            )
            session.execute_write(
                self._reconcile_code_entities,
                document.source.path,
                [e.qualified_name for e in document.code_entities],
            )
            session.execute_write(
                self._reconcile_annotations,
                document.source.path,
                [a.id for a in document.annotations],
            )
            session.execute_write(
                self._reconcile_http_endpoints,
                document.source.path,
                [e.id for e in document.http_endpoints],
            )
            session.execute_write(
                self._reconcile_policy_rules,
                document.source.path,
                [r.id for r in document.policy_rules],
            )
            session.execute_write(
                self._reconcile_config_properties,
                document.source.path,
                [p.id for p in document.config_properties],
            )
            session.execute_write(
                self._reconcile_spring_xml_beans,
                document.source.path,
                [b.id for b in document.spring_xml_beans],
            )
            session.execute_write(
                self._reconcile_jpa_entity_defs,
                document.source.path,
                [e.qualified_name for e in document.jpa_entities],
            )
            session.execute_write(
                self._reconcile_spring_data_repo_defs,
                document.source.path,
                [r.qualified_name for r in document.spring_data_repositories],
            )
            session.execute_write(
                self._reconcile_config_files,
                document.source.path,
                [f.path for f in document.config_files],
            )
            session.execute_write(
                self._reconcile_modules,
                document.source.path,
                [m.path for m in document.modules],
            )
            session.execute_write(
                self._reconcile_db_tables,
                document.source.path,
                [t.qualified_name for t in document.db_tables],
            )
            session.execute_write(
                self._reconcile_db_columns,
                document.source.path,
                [c.qualified_name for c in document.db_columns],
            )
            session.execute_write(
                self._reconcile_db_views,
                document.source.path,
                [v.qualified_name for v in document.db_views],
            )
            session.execute_write(
                self._reconcile_db_indexes,
                document.source.path,
                [i.qualified_name for i in document.db_indexes],
            )

    def get_source_content_hash(self, path: str) -> str | None:
        """The `content_hash` currently stored for a `Source`, or `None` if unseen."""
        with self._driver.session() as session:
            record = session.run(cast(LiteralString, _GET_SOURCE_CONTENT_HASH), path=path).single()
            return record["content_hash"] if record else None

    @staticmethod
    def _write_source(tx: ManagedTransaction, document: ParsedDocument) -> None:
        tx.run(
            cast(LiteralString, _MERGE_SOURCE),
            path=document.source.path,
            type=document.source.source_type,
            content_hash=document.source.content_hash,
            ingested_at=document.source.ingested_at.isoformat(),
            version=document.source.version,
        )

    @staticmethod
    def _write_source_imports(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_SOURCE_IMPORTS), pairs=pairs)

    @staticmethod
    def _write_sections(tx: ManagedTransaction, source_path: str, sections: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_SECTIONS), sections=sections, source_path=source_path)

    @staticmethod
    def _write_chunks(tx: ManagedTransaction, chunks: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_CHUNKS), chunks=chunks)

    @staticmethod
    def _write_next(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_NEXT), pairs=pairs)

    @staticmethod
    def _write_code_entities(
        tx: ManagedTransaction, source_path: str, entities: list[dict]
    ) -> None:
        tx.run(
            cast(LiteralString, _MERGE_CODE_ENTITIES), entities=entities, source_path=source_path
        )

    @staticmethod
    def _write_annotations(tx: ManagedTransaction, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_ANNOTATIONS), rows=rows)

    @staticmethod
    def _write_http_endpoints(tx: ManagedTransaction, source_path: str, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_HTTP_ENDPOINTS), rows=rows, source_path=source_path)

    @staticmethod
    def _write_calls(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_CALLS), pairs=pairs)

    @staticmethod
    def _write_imports(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_IMPORTS), pairs=pairs)

    @staticmethod
    def _write_renders(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_RENDERS), pairs=pairs)

    @staticmethod
    def _write_extends(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_EXTENDS), pairs=pairs)

    @staticmethod
    def _write_implements(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_IMPLEMENTS), pairs=pairs)

    @staticmethod
    def _write_reads(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_READS), pairs=pairs)

    @staticmethod
    def _write_writes(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_WRITES), pairs=pairs)

    @staticmethod
    def _write_trigger_on(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_TRIGGER_ON), pairs=pairs)

    @staticmethod
    def _write_db_tables(tx: ManagedTransaction, source_path: str, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_DB_TABLES), rows=rows, source_path=source_path)

    @staticmethod
    def _write_db_columns(tx: ManagedTransaction, source_path: str, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_DB_COLUMNS), rows=rows, source_path=source_path)

    @staticmethod
    def _write_db_views(tx: ManagedTransaction, source_path: str, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_DB_VIEWS), rows=rows, source_path=source_path)

    @staticmethod
    def _write_db_indexes(tx: ManagedTransaction, source_path: str, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_DB_INDEXES), rows=rows, source_path=source_path)

    @staticmethod
    def _write_column_references(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_COLUMN_REFERENCES), pairs=pairs)

    @staticmethod
    def _write_table_references(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_TABLE_REFERENCES), pairs=pairs)

    @staticmethod
    def _write_view_depends_on(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_VIEW_DEPENDS_ON), pairs=pairs)

    @staticmethod
    def _write_policy_rules(tx: ManagedTransaction, source_path: str, rules: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_POLICY_RULES), rules=rules, source_path=source_path)

    @staticmethod
    def _write_applies_to(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_APPLIES_TO), pairs=pairs)

    @staticmethod
    def _write_config_files(tx: ManagedTransaction, source_path: str, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_CONFIG_FILES), rows=rows, source_path=source_path)

    @staticmethod
    def _write_config_properties(tx: ManagedTransaction, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_CONFIG_PROPERTIES), rows=rows)

    @staticmethod
    def _write_config_property_references(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_CONFIG_PROPERTY_REFERENCES), pairs=pairs)

    @staticmethod
    def _write_spring_xml_beans(tx: ManagedTransaction, source_path: str, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_SPRING_XML_BEANS), rows=rows, source_path=source_path)

    @staticmethod
    def _write_jpa_entity_defs(tx: ManagedTransaction, source_path: str, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_JPA_ENTITY_DEFS), rows=rows, source_path=source_path)

    @staticmethod
    def _write_spring_data_repo_defs(
        tx: ManagedTransaction, source_path: str, rows: list[dict]
    ) -> None:
        tx.run(
            cast(LiteralString, _MERGE_SPRING_DATA_REPO_DEFS), rows=rows, source_path=source_path
        )

    @staticmethod
    def _write_modules(tx: ManagedTransaction, source_path: str, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_MODULES), rows=rows, source_path=source_path)

    @staticmethod
    def _write_external_artifacts(tx: ManagedTransaction, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_EXTERNAL_ARTIFACTS), rows=rows)

    @staticmethod
    def _write_module_depends_on(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_MODULE_DEPENDS_ON), pairs=pairs)

    @staticmethod
    def _write_module_depends_on_external(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_MODULE_DEPENDS_ON_EXTERNAL), pairs=pairs)

    @staticmethod
    def _reconcile_chunks(tx: ManagedTransaction, source_path: str, keep_ids: list[str]) -> None:
        tx.run(cast(LiteralString, _RECONCILE_CHUNKS), source_path=source_path, keep_ids=keep_ids)

    @staticmethod
    def _reconcile_sections(tx: ManagedTransaction, source_path: str, keep_ids: list[str]) -> None:
        tx.run(cast(LiteralString, _RECONCILE_SECTIONS), source_path=source_path, keep_ids=keep_ids)

    @staticmethod
    def _reconcile_code_entities(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_CODE_ENTITIES),
            source_path=source_path,
            keep_ids=keep_ids,
        )

    @staticmethod
    def _reconcile_annotations(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_ANNOTATIONS),
            source_path=source_path,
            keep_ids=keep_ids,
        )
        tx.run(cast(LiteralString, _SWEEP_ORPHAN_ANNOTATIONS))

    @staticmethod
    def _reconcile_http_endpoints(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_HTTP_ENDPOINTS),
            source_path=source_path,
            keep_ids=keep_ids,
        )

    @staticmethod
    def _reconcile_policy_rules(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_POLICY_RULES),
            source_path=source_path,
            keep_ids=keep_ids,
        )

    @staticmethod
    def _reconcile_config_properties(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_CONFIG_PROPERTIES),
            source_path=source_path,
            keep_ids=keep_ids,
        )

    @staticmethod
    def _reconcile_spring_xml_beans(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_SPRING_XML_BEANS),
            source_path=source_path,
            keep_ids=keep_ids,
        )

    @staticmethod
    def _reconcile_jpa_entity_defs(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_JPA_ENTITY_DEFS),
            source_path=source_path,
            keep_ids=keep_ids,
        )

    @staticmethod
    def _reconcile_spring_data_repo_defs(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_SPRING_DATA_REPO_DEFS),
            source_path=source_path,
            keep_ids=keep_ids,
        )

    @staticmethod
    def _reconcile_config_files(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_CONFIG_FILES),
            source_path=source_path,
            keep_ids=keep_ids,
        )

    @staticmethod
    def _reconcile_modules(tx: ManagedTransaction, source_path: str, keep_ids: list[str]) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_MODULES),
            source_path=source_path,
            keep_ids=keep_ids,
        )

    @staticmethod
    def _reconcile_db_tables(tx: ManagedTransaction, source_path: str, keep_ids: list[str]) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_DB_TABLES), source_path=source_path, keep_ids=keep_ids
        )

    @staticmethod
    def _reconcile_db_columns(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_DB_COLUMNS), source_path=source_path, keep_ids=keep_ids
        )

    @staticmethod
    def _reconcile_db_views(tx: ManagedTransaction, source_path: str, keep_ids: list[str]) -> None:
        tx.run(cast(LiteralString, _RECONCILE_DB_VIEWS), source_path=source_path, keep_ids=keep_ids)

    @staticmethod
    def _reconcile_db_indexes(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_DB_INDEXES), source_path=source_path, keep_ids=keep_ids
        )

    @staticmethod
    def _source_import_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": document.source.path, "to": imported} for imported in document.source_imports
        ]

    @staticmethod
    def _chunk_pairs(document: ParsedDocument) -> list[dict]:
        # section_id embeds a zero-padded index, so this sort is full document reading order.
        ordered = sorted(document.chunks, key=lambda c: (c.section_id, c.order))
        return [{"from": a.id, "to": b.id} for a, b in zip(ordered, ordered[1:], strict=False)]

    @staticmethod
    def _annotation_rows(document: ParsedDocument) -> list[dict]:
        return [
            {
                "id": annotation.id,
                "owner_qualified_name": annotation.owner_qualified_name,
                "target": annotation.target,
                "fqn": annotation.fqn,
                "name": annotation.name,
                "attributes_json": annotation.attributes_json,
                "line": annotation.line,
            }
            for annotation in document.annotations
        ]

    @staticmethod
    def _call_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": callee}
            for entity in document.code_entities
            for callee in entity.calls
        ]

    @staticmethod
    def _import_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": imported}
            for entity in document.code_entities
            for imported in entity.imports
        ]

    @staticmethod
    def _render_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": rendered}
            for entity in document.code_entities
            for rendered in entity.renders
        ]

    @staticmethod
    def _extends_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": supertype}
            for entity in document.code_entities
            for supertype in entity.extends_types
        ]

    @staticmethod
    def _implements_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": interface}
            for entity in document.code_entities
            for interface in entity.implements_types
        ]

    @staticmethod
    def _column_reference_pairs(document: ParsedDocument) -> list[dict]:
        pairs = [
            {"from": column.qualified_name, "to": target}
            for column in document.db_columns
            for target in column.references
        ]
        pairs.extend(
            {"from": reference.from_qualified_name, "to": reference.to_qualified_name}
            for reference in document.db_references
            if reference.level == "column"
        )
        return pairs

    @staticmethod
    def _table_reference_pairs(document: ParsedDocument) -> list[dict]:
        pairs = [
            {"from": table.qualified_name, "to": target}
            for table in document.db_tables
            for target in table.references
        ]
        pairs.extend(
            {"from": reference.from_qualified_name, "to": reference.to_qualified_name}
            for reference in document.db_references
            if reference.level == "table"
        )
        return pairs

    @staticmethod
    def _view_depends_on_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": view.qualified_name, "to": target}
            for view in document.db_views
            for target in view.depends_on
        ]

    @staticmethod
    def _reads_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": table}
            for entity in document.code_entities
            for table in entity.reads
        ]

    @staticmethod
    def _writes_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": table}
            for entity in document.code_entities
            for table in entity.writes
        ]

    @staticmethod
    def _trigger_on_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": entity.trigger_table}
            for entity in document.code_entities
            if entity.trigger_table
        ]

    @staticmethod
    def _applies_to_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": rule.id, "to": resource_type}
            for rule in document.policy_rules
            for resource_type in rule.resource_types
        ]

    @staticmethod
    def _config_property_rows(document: ParsedDocument) -> list[dict]:
        return [
            {
                "id": prop.id,
                "file_path": prop.file_path,
                "key": prop.key,
                "value": prop.value,
                "profile": prop.profile,
                "origin_line": prop.origin_line,
            }
            for prop in document.config_properties
        ]

    @staticmethod
    def _config_property_reference_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": prop.id, "to": target_id}
            for prop in document.config_properties
            for target_id in prop.references
        ]

    @staticmethod
    def _module_depends_on_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": dep.module_path, "to": dep.target_path, "scope": dep.scope}
            for dep in document.module_dependencies
            if dep.target_path is not None
        ]

    @staticmethod
    def _module_depends_on_external_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": dep.module_path, "gav": dep.target_gav, "scope": dep.scope}
            for dep in document.module_dependencies
            if dep.target_path is None and dep.target_gav is not None
        ]

    @staticmethod
    def _batched(rows: list) -> list[list]:
        return [rows[i : i + _BATCH_SIZE] for i in range(0, len(rows), _BATCH_SIZE)]
