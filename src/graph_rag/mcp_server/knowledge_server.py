from pathlib import Path

from mcp.server import MCPServer

from ..ingestion_pipeline import IngestionPipeline
from ..ingestion_result import IngestionResult
from .models import (
    ArchitectureOutline,
    BeanDetail,
    CodeCentralityResult,
    CodeSearchResult,
    EndpointResult,
    MessageFlowResult,
    NeighborResult,
    OutlineNode,
    PolicyResult,
    RouteResult,
    SearchResult,
    SectionDetail,
    ServiceCallResult,
    SourceInfo,
)
from .retriever import Retriever

KNOWLEDGE_INSTRUCTIONS = (
    "Look up whatever has been ingested into this knowledge base — prose/"
    "Markdown documentation, source code, and Checkov policies. Call "
    "`list_sources` first to see what's actually available. `search` covers ingested "
    "prose/Markdown/generic-YAML chunks ONLY — it does not cover source code "
    "or Checkov policy text; use `search_code` for a natural-language "
    "question about this codebase's code (functions, classes, modules) in any "
    "indexed language, and `search_policies` "
    "for a natural-language question about Checkov policies when you don't "
    "know the exact Terraform resource type. `get_section` returns the full "
    "text of a known section, `get_outline` browses a source's table of "
    "contents, `list_sources` shows what's ingested, `find_policies_for` is "
    "an exact-match traversal from a Terraform resource type (e.g. "
    "`aws_db_instance`) to the policies that apply to it — no fuzzy fallback, "
    "so an empty result may mean the resource type string is off, not that "
    "no policy exists; try `search_policies` instead of guessing variants. "
    "`get_neighbors` walks the graph from any node (Source path, "
    "Section/Chunk/PolicyRule/Bean/HttpEndpoint id, CodeEntity qualified_name, "
    "Module path, or Concept name). `get_central_code_entities` ranks code by "
    "PageRank over the CALLS/IMPORTS graph — use it to find what's most "
    "depended-upon (and riskiest to change) in this codebase; empty until "
    "`grag-mcp compute-centrality` has been run at least once. `cite` returns "
    "a human-readable citation string for a chunk. `ingest_path` (re-)ingests "
    "a file or directory after it changes. For an enterprise Java (Spring / "
    "Jakarta / Camel) codebase the graph also carries beans + dependency "
    "injection, Spring MVC / JAX-RS HTTP endpoints, Spring Data repositories "
    "and JPA entities, application config, Apache Camel routes, in-process "
    "events + broker messaging, AOP advice + behavioral markers "
    "(transactional / scheduled / async / …), MyBatis mapper SQL, and "
    "declarative HTTP clients (`@FeignClient` / `@HttpExchange`). Framework "
    "tools: `search_code` filters `stereotype=` / `annotation=` / `module=` / "
    "`route=` / `endpoint=` / `listens_to=` / `behavior=`; "
    "`get_beans_for(qualified_name)` (wiring + route/listener/behavior context); "
    "`get_endpoints(path_glob?, http_method?, module?)`; "
    "`get_routes(uri_glob?, module?)`; "
    "`get_message_flows(event_or_topic)` (publisher↔consumer); "
    "`get_service_calls(qualified_name)` (in/out HTTP, cross-service); "
    "`get_architecture_outline(module?)` (beans / endpoints / routes / "
    "listeners / scheduled jobs by module). `get_central_code_entities` folds "
    "the framework edges into PageRank. `get_neighbors` also walks `INJECTS` / "
    "`HANDLED_BY` / `PUBLISHES` / `CONSUMED_BY` / `PRODUCES_TO` / "
    "`CALLS_SERVICE` / `RESOLVES_TO` / `EXECUTES` / `ACCESSES` / route "
    "`FROM` / `TO` / `STEP` / `INVOKES` / `ADVISES` / `HAS_BEHAVIOR`. Today's "
    "Java graph is best-effort static; compiler-grade cross-file / library "
    "resolution is `grag-mcp ingest --scip` (`CodeEntity.resolution`). The "
    "source list is also browsable as a resource (`graph-rag://sources`) "
    "without a tool call."
)


def register_knowledge_tools(
    server: MCPServer, retriever: Retriever, ingestion_pipeline: IngestionPipeline
) -> None:
    """Wires the search/lookup/ingest tools onto `server`.

    Shared by `build_knowledge_server` (knowledge-only deployments) and
    `build_server` (the combined, default deployment) so the tool bodies
    exist in exactly one place.
    """

    @server.tool()
    def search(
        query: str,
        top_k: int = 5,
        source_type: str | None = None,
        source_path: str | None = None,
    ) -> list[SearchResult]:
        """Hybrid (vector + full-text) search over ingested prose/Markdown/
        generic-YAML document chunks ONLY — does not cover source code
        (use `search_code`) or Checkov policy text (use `search_policies`).
        """
        return retriever.search(query, top_k, source_type, source_path)

    @server.tool()
    def search_code(
        query: str,
        top_k: int = 5,
        stereotype: str | None = None,
        annotation: str | None = None,
        module: str | None = None,
        route: str | None = None,
        endpoint: str | None = None,
        listens_to: str | None = None,
        behavior: str | None = None,
    ) -> list[CodeSearchResult]:
        """Hybrid (vector + full-text) search over indexed source code —
        functions, classes, modules, and other per-language entities — the
        code-search complement to `search`.

        Optional filters narrow to the Spring / Java-framework graph:
        `stereotype` (`Service` / `RestController` / `Repository` /
        `Configuration` / … — a Spring bean stereotype or a bare type-level
        annotation name), `annotation` (any annotation, simple name or FQN),
        `module` (owning `Module` artifact id or a path suffix), `route` (a
        Camel `Route.route_id` whose steps invoke the entity), `endpoint` (a
        path glob a handler on the entity serves), `listens_to` (an event type
        fqn/simple name or broker destination the entity — or a method it
        contains — consumes), `behavior` (`transactional` / `scheduled` /
        `async` / `retryable` / `cacheable` / `pre_authorize` / …).
        """
        return retriever.search_code(
            query, top_k, stereotype, annotation, module, route, endpoint, listens_to, behavior
        )

    @server.tool()
    def get_section(section_id: str, max_chars: int = 8000) -> SectionDetail | None:
        """Full text of one section (truncated past `max_chars`), plus its parent/child outline."""
        return retriever.get_section(section_id, max_chars)

    @server.tool()
    def get_outline(source_path: str) -> list[OutlineNode]:
        """Section outline (table of contents) for a prose source, as a nested tree."""
        return retriever.get_outline(source_path)

    @server.tool()
    def list_sources() -> list[SourceInfo]:
        """List every source currently ingested into the graph."""
        return retriever.list_sources()

    @server.tool()
    def find_policies_for(resource_type: str) -> list[PolicyResult]:
        """Exact-match: Checkov policies whose APPLIES_TO edge names this
        Terraform resource type precisely (e.g. `aws_db_instance`). No fuzzy
        fallback — an empty result may mean the exact spelling is off, not
        that no policy exists; try `search_policies` instead of guessing
        variants.
        """
        return retriever.find_policies_for(resource_type)

    @server.tool()
    def search_policies(query: str, top_k: int = 5) -> list[PolicyResult]:
        """Hybrid (vector + full-text) search over Checkov policy content —
        the semantic/fuzzy complement to `find_policies_for`, for when the
        exact Terraform resource type isn't known.
        """
        return retriever.search_policies(query, top_k)

    @server.tool()
    def get_neighbors(node_id: str, rel_types: list[str] | None = None) -> list[NeighborResult]:
        """Every node directly connected to `node_id`, in both relationship directions.

        `node_id` is matched against whichever unique key its node type uses:
        `Source.path`, `Section`/`Chunk`/`PolicyRule`/`Bean`/`HttpEndpoint.id`,
        `CodeEntity.qualified_name`, `Module.path`, `ConfigProperty.id`, or
        `Concept.name`. Optionally filter to specific relationship types — the
        Java-framework ones are `INJECTS` / `PRODUCES` / `BINDS` / `IS_BEAN`
        (beans), `HANDLED_BY` (endpoint → handler), `MANAGES` / `PERSISTS_AS` /
        `RELATES_TO` (Spring Data / JPA), `EXTENDS` / `IMPLEMENTS`,
        `ANNOTATED_WITH`, `IMPORTS_CONTEXT` — alongside `CALLS` / `IMPORTS` /
        `IN_MODULE` / `DEPENDS_ON`.
        """
        return retriever.get_neighbors(node_id, rel_types)

    @server.tool()
    def get_beans_for(qualified_name: str) -> BeanDetail | None:
        """The Spring bean for a `CodeEntity.qualified_name` (or a `Bean.id`):
        its stereotype / scope / type, what it `INJECTS` and what injects it,
        what `PRODUCES` it (an `@Bean` method's `@Configuration`), and the
        `ConfigProperty` keys it `BINDS` (`@Value` / `@ConfigurationProperties`
        / XML `${…}`). Annotation- and XML-wired beans are both covered.
        `None` if the name is not a bean.
        """
        return retriever.get_beans_for(qualified_name)

    @server.tool()
    def get_endpoints(
        path_glob: str | None = None,
        http_method: str | None = None,
        module: str | None = None,
    ) -> list[EndpointResult]:
        """Spring MVC / JAX-RS HTTP routes (`HttpEndpoint` nodes) with their
        handler method and module. Optional filters: `path_glob` (`*` / `?`
        wildcards; matches a substring of the path unless pinned with `^` / `$`),
        `http_method` (`GET` / `POST` / … / `EXCEPTION`), `module` (owning
        `Module` artifact id or path suffix).
        """
        return retriever.get_endpoints(path_glob, http_method, module)

    @server.tool()
    def get_routes(uri_glob: str | None = None, module: str | None = None) -> list[RouteResult]:
        """Apache Camel routes (`Route` nodes) — `from` endpoint, `to` endpoints,
        ordered step list, and the `CodeEntity`s the `process` / `bean` steps
        invoke. Optional `uri_glob` (`*` / `?`; substring unless `^` / `$`) is
        matched against the route's `from` and any `to` endpoint URI; `module`
        is the owning `Module` artifact id or path suffix.
        """
        return retriever.get_routes(uri_glob, module)

    @server.tool()
    def get_message_flows(event_or_topic: str) -> list[MessageFlowResult]:
        """Publisher ↔ consumer flow for an in-process application event
        (`EventType.fqn` or simple name) or a broker destination
        (`Destination.name` — a Kafka topic / Rabbit queue / JMS destination /
        SQS queue). Returns the `CodeEntity` qualified_names on each side.
        """
        return retriever.get_message_flows(event_or_topic)

    @server.tool()
    def get_service_calls(qualified_name: str) -> ServiceCallResult:
        """Inbound (`@RestController` routes it handles) and outbound
        (`@FeignClient` / `@HttpExchange` calls it declares, plus the ingested
        controller route each resolves to) HTTP edges for one
        `CodeEntity.qualified_name` — a slice of the cross-service call graph.
        """
        return retriever.get_service_calls(qualified_name)

    @server.tool()
    def get_architecture_outline(module: str | None = None) -> ArchitectureOutline:
        """Beans, HTTP endpoints, Camel routes, message listeners, and scheduled
        jobs, grouped by Maven/Gradle module (an `unassigned` bucket holds
        nodes in no module). Optionally restricted to one `Module.artifact`.
        The fastest way to see the shape of an enterprise Java service.
        """
        return retriever.get_architecture_outline(module)

    @server.tool()
    def get_central_code_entities(top_k: int = 10) -> list[CodeCentralityResult]:
        """Most central `CodeEntity` nodes by PageRank over the dependency graph
        — direct `CALLS` / `IMPORTS` plus framework-mediated edges (`INJECTS`,
        `PUBLISHES` / `CONSUMED_BY`, Camel `INVOKES`, `CALLS_SERVICE`,
        `EXECUTES`) — i.e. what's most heavily depended-upon (and riskiest to
        change). Empty until `grag-mcp compute-centrality` has been run.
        """
        return retriever.get_central_code_entities(top_k)

    @server.tool()
    def cite(chunk_id: str) -> str | None:
        """Human-readable citation string for a chunk (source + breadcrumb + page range)."""
        return retriever.cite(chunk_id)

    @server.tool()
    def ingest_path(path: str, dry_run: bool = False) -> list[IngestionResult]:
        """(Re-)ingest a file or directory; skips files unchanged since the last ingest."""
        return ingestion_pipeline.run(Path(path), dry_run=dry_run)

    @server.resource("graph-rag://sources")
    def sources_resource() -> list[SourceInfo]:
        """Browsable list of every ingested source, without a tool call."""
        return retriever.list_sources()


def build_knowledge_server(
    retriever: Retriever, ingestion_pipeline: IngestionPipeline
) -> MCPServer:
    """A standalone MCP server exposing only the knowledge-base tools —
    for a deployment split from agent memory (`serve-mcp --role knowledge`).
    """
    server = MCPServer(name="graph-rag-knowledge", instructions=KNOWLEDGE_INSTRUCTIONS)
    register_knowledge_tools(server, retriever, ingestion_pipeline)
    return server
