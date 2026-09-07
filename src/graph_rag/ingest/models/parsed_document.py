from pydantic import BaseModel, Field

from .annotation import Annotation
from .chunk import Chunk
from .code_entity import CodeEntity
from .config_file import ConfigFile
from .config_property import ConfigProperty
from .db_column import DbColumn
from .db_index import DbIndex
from .db_reference import DbReference
from .db_table import DbTable
from .db_view import DbView
from .external_artifact import ExternalArtifact
from .http_endpoint import HttpEndpoint
from .module import Module
from .module_dependency import ModuleDependency
from .policy_rule import PolicyRule
from .section import Section
from .source import Source
from .spring_xml_bean import SpringXmlBean


class ParsedDocument(BaseModel):
    """A parser's output: one `Source`, plus whichever shape fits its source
    type — a `Section`/`Chunk` tree (prose sources like PDF/Markdown), a
    `CodeEntity` list (source code), a `PolicyRule` list (Checkov YAML), or a
    `DbTable`/`DbColumn`/`DbView`/`DbIndex` set (SQL DDL).
    """

    source: Source
    sections: list[Section] = Field(default_factory=list)
    chunks: list[Chunk] = Field(default_factory=list)
    code_entities: list[CodeEntity] = Field(default_factory=list)
    # Structured annotations on the code entities above, each carrying its
    # `owner_qualified_name`; feeds `(CodeEntity)-[:ANNOTATED_WITH]->(:Annotation)`.
    annotations: list[Annotation] = Field(default_factory=list)
    policy_rules: list[PolicyRule] = Field(default_factory=list)
    # Spring / Java application config: one `ConfigFile` per parsed file plus its
    # flattened `ConfigProperty` list; feeds
    # `(:ConfigFile)-[:HAS_PROPERTY]->(:ConfigProperty)-[:REFERENCES]->(:ConfigProperty)`.
    config_files: list[ConfigFile] = Field(default_factory=list)
    config_properties: list[ConfigProperty] = Field(default_factory=list)
    # Spring XML `<beans>` context: one `SpringXmlBean` per `<bean>` def; feeds
    # `(:ConfigFile)-[:DECLARES_BEAN]->(:SpringXmlBean)`, projected by the
    # `SpringXmlResolver` pass into the shared `(:Bean {defined_in:'xml'})` graph.
    spring_xml_beans: list[SpringXmlBean] = Field(default_factory=list)
    # Maven/Gradle project model: one `Module` per parsed build file, its
    # declared third-party `ExternalArtifact`s, and its `ModuleDependency`
    # edges; feeds `(:Module)-[:DEPENDS_ON|DEPENDS_ON_EXTERNAL]->(...)` and,
    # after the resolver pass, `(:Source)-[:IN_MODULE]->(:Module)`.
    modules: list[Module] = Field(default_factory=list)
    external_artifacts: list[ExternalArtifact] = Field(default_factory=list)
    module_dependencies: list[ModuleDependency] = Field(default_factory=list)
    # Spring MVC / JAX-RS routes, one per (http_method, path); feeds
    # `(:HttpEndpoint)-[:HANDLED_BY]->(:CodeEntity)`.
    http_endpoints: list[HttpEndpoint] = Field(default_factory=list)
    db_tables: list[DbTable] = Field(default_factory=list)
    db_columns: list[DbColumn] = Field(default_factory=list)
    db_views: list[DbView] = Field(default_factory=list)
    db_indexes: list[DbIndex] = Field(default_factory=list)
    db_references: list[DbReference] = Field(default_factory=list)
    # Paths of other `Source` files this one pulls in — stylesheet `@import` /
    # `@use` / `@forward`; feeds `(Source)-[:IMPORTS]->(Source)` edges.
    source_imports: list[str] = Field(default_factory=list)
