# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Declarative HTTP clients. `@FeignClient(name, path)` and `@HttpExchange`
  interface methods (`@GetMapping` / `@GetExchange` / …) become *outbound*
  `HttpEndpoint`s (`outbound=true`, `target_service`, path composed from the
  type base + method path), wired `(:CodeEntity)-[:CALLS_SERVICE]->(:HttpEndpoint)`.
  New `ServiceCallResolver` post-ingest pass matches each to an ingested
  `@RestController` route by `(http_method, path)` (path variables normalized)
  and adds `(:HttpEndpoint outbound)-[:RESOLVES_TO]->(:HttpEndpoint inbound)` —
  a cross-service call graph; unmatched outbound endpoints stay standalone.
  ([#86](https://github.com/tmustafiz/graph-rag/issues/86))
- MyBatis mapper model. New `MyBatisMapperParser` claims a `.xml` with a
  `<mapper namespace>` root and emits a `SqlStatement` per
  `<select|insert|update|delete>` — SQL flattened (`<include>` fragments
  expanded, dynamic `<if>` / `<where>` / `<foreach>` unwrapped) and scanned for
  table names + `read` / `write` mode. `@Select` / `@Insert` / `@Update` /
  `@Delete` annotations on `@Mapper` methods are handled in `JavaParser` via
  `MyBatisExtractor`. `MyBatisResolver` binds XML statements to their interface
  method by `namespace` + `id`. Feeds
  `(:CodeEntity)-[:EXECUTES]->(:SqlStatement)-[:ACCESSES {mode}]->(:DbTable)`
  (reusing a real `DbTable` by name, else a `stub:true` node).
  ([#85](https://github.com/tmustafiz/graph-rag/issues/85))
- AOP & behavioral-annotation model. `@Transactional` / `@Async` / `@Scheduled`
  / `@Retryable` / `@Cacheable` / `@CacheEvict` / `@PreAuthorize` / `@Secured` /
  `@RolesAllowed` on a type or method become `(:CodeEntity)-[:HAS_BEHAVIOR
  {marker}]->(:BehaviorMarker)` carrying the annotation's attributes (cron,
  propagation, readOnly, maxAttempts, …); the marker slugs are mirrored onto
  `CodeEntity.behaviors` for cheap "all scheduled jobs" scans. Every `@Aspect`
  advice / `@Pointcut` method becomes an `(:Advice)` node, and the new
  `AopResolver` post-ingest pass does best-effort AspectJ pointcut matching
  (`execution(…)` / `within(…)` / `@annotation(…)`, `&&` / `||`, one level of
  named-`@Pointcut` substitution) to wire `(:Advice)-[:ADVISES]->(:CodeEntity)`,
  recording `Advice.unresolved_reason` for what it can't match.
  ([#83](https://github.com/tmustafiz/graph-rag/issues/83))

## [0.6.0] - 2026-09-07

### Added
- Spring-aware retrieval surface + enterprise-Java example. `search_code` gains
  optional `stereotype=` / `annotation=` / `module=` filters (guards baked into
  the hybrid query — an unfiltered call is unchanged). New MCP tools
  `get_beans_for(qualified_name)` (a bean's `INJECTS` / `PRODUCES` wiring both
  ways + the `ConfigProperty` keys it `BINDS`, annotation- and XML-wired alike)
  and `get_endpoints(path_glob?, http_method?, module?)` (Spring MVC / JAX-RS
  routes with handler + module; `path_glob` is `*` / `?` whole-path match).
  `get_neighbors` now surfaces `Bean` / `HttpEndpoint` / `ConfigProperty`
  summaries and its docs call out the Java-framework edges (`INJECTS` /
  `HANDLED_BY` / `MANAGES` / `PERSISTS_AS` / `RELATES_TO` / `BINDS` /
  `IMPORTS_CONTEXT`). MCP server instructions describe the Spring graph. New
  `examples/spring-boot/` — a runnable two-module sample (`@RestController`,
  `@Service` with constructor + field injection, `@ConfigurationProperties`,
  `@Repository` + `@Entity` with a `@ManyToOne`, `application.yml`, and an
  XML-wired bean the `@Autowired` field resolves to) with a query walkthrough in
  its `README.md`. `docs/ARCHITECTURE.md` gains a "Java frameworks" section;
  `README.md` notes the Spring capability and the v0.7.0 `--scip` precision path.
  ([#77](https://github.com/tmustafiz/graph-rag/issues/77))
- Spring Data repository + JPA entity model. New pure `SpringDataExtractor`
  (inside `JavaParser`) turns repository interfaces (`Repository` /
  `CrudRepository` / `JpaRepository` / `PagingAndSortingRepository` /
  `List*Repository` / reactive `ReactiveCrudRepository` / `R2dbcRepository` / …,
  Mongo / Cassandra / ES, plus `@RepositoryDefinition`; `@NoRepositoryBean`
  suppressed) into `SpringDataRepoDef`s — managed `entity_type` / `id_type` from
  the base's generic arguments (`JpaRepository<Order, Long>`, read from the AST
  since `CodeEntity.extends_types` drops generics), and every declared method
  classified `derived` / `jpql` / `native` / `modifying` / `procedure` /
  `inherited` with `@Query` / procedure text and, for derived queries, a
  best-effort property-path parse of the method name
  (`findByCustomerIdAndStatusOrderByCreatedAtDesc` → `customerId`, `status`)
  that never raises on an unparseable name. JPA entities (`@Entity` /
  `@Embeddable` / `@MappedSuperclass`, `@Table(name)`, `@Id`, `@OneToMany` /
  `@ManyToOne` / `@ManyToMany` / `@OneToOne` + `mappedBy`) become `JpaEntityDef`s.
  New `SpringDataResolver` — a fourth post-directory-ingest pass — tags the
  `CodeEntity`s `:Repository` / `:JpaEntity` (with `repository_*` / `jpa_*`
  props), tags repo methods with `query_kind` / `query_text` /
  `query_properties`, and wires `(:Repository)-[:MANAGES]->(:JpaEntity)`,
  `(:JpaEntity)-[:PERSISTS_AS]->(:DbTable)` (only when a `DbTable` of that name
  was ingested — the SQL-schema bridge) and
  `(:JpaEntity)-[:RELATES_TO {kind, mapped_by, field}]->(:JpaEntity)`. New
  `jpa_entity_def_qn` / `spring_data_repo_def_qn` constraints;
  `(:Source)-[:DEFINES]->(:SpringDataRepoDef|:JpaEntityDef)`.
  ([#76](https://github.com/tmustafiz/graph-rag/issues/76))
- Spring XML context parser (`<beans>`) into the same bean/DI graph. New
  `SpringXmlParser` (stdlib `xml.etree`, registered ahead of `ConfigFileParser`,
  matches only `.xml` files whose root element is `<beans>`) turns each `<bean>`
  — inner beans included — into a `SpringXmlBean` def carrying its `class`,
  `scope`, `parent`, `factory-*`, `primary`, `abstract`, aliases (`<alias>` +
  extra `name` tokens), `<constructor-arg ref>` / `<property name ref>` wiring
  (`<ref bean>`, inner `<bean>`, `<list>` / `<set>` / `<map>` of refs, `p:` /
  `c:` shortcut namespaces) and the `${key}`s in `value=` attributes.
  `<context:component-scan>`, `<context:property-placeholder>`, `<import
  resource>` and non-`beans` namespace elements (`aop:*`, `tx:*`, `util:*` —
  recorded) land on the `ConfigFile` (`format="spring-xml"`). New
  `SpringXmlResolver` — a third post-directory-ingest pass, after
  `SpringBeanResolver` — projects each `SpringXmlBean` into the **same** `Bean`
  graph (`(:Bean {defined_in:'xml', stereotype:'XmlBean'})`), links
  `(:CodeEntity)-[:IS_BEAN]->` when the class was ingested, resolves refs by
  name/alias across XML **and** annotation beans into
  `(:Bean)-[:INJECTS {via:'xml-constructor'|'xml-property', property}]->(:Bean)`
  (unknown ref → `stereotype:'XmlBeanStub'` bean; ambiguous →
  `Bean.unresolved_injections`), links `${key}` property values via `BINDS`, and
  wires `(:ConfigFile)-[:IMPORTS_CONTEXT {kind:'import'|'property-placeholder'}]->(:ConfigFile)`.
  New `spring_xml_bean_id` constraint; `(:ConfigFile)-[:DECLARES_BEAN]->(:SpringXmlBean)`.
  ([#74](https://github.com/tmustafiz/graph-rag/issues/74))
- Spring MVC / JAX-RS HTTP endpoint model. `HttpEndpointExtractor` (inside
  `JavaParser`) turns controller handler methods into `(:HttpEndpoint
  {http_method, path, framework, produces, consumes, params, bindings,
  embed_text})` nodes — Spring MVC (`@RequestMapping` + `@GetMapping` /
  `@PostMapping` / `@PutMapping` / `@DeleteMapping` / `@PatchMapping`, class +
  method path composition) and JAX-RS (`@Path` + `@GET` / `@POST` / …). One
  endpoint per `(http_method, path)`; parameter bindings (`@PathVariable`,
  `@RequestParam`, `@RequestBody`, `@RequestHeader`, `@ModelAttribute`;
  `@PathParam`, `@QueryParam`, `@HeaderParam`, `@FormParam`) matched to the
  handler params by name with types from the signature; `@ExceptionHandler`
  methods recorded best-effort as `http_method="EXCEPTION"`.
  `(:HttpEndpoint)-[:HANDLED_BY]->(:CodeEntity)` and, via the project-model
  resolver, `-[:IN_MODULE]->(:Module)`. `embed_text` is natural language
  (`"GET /orders/{id} -> OrderController.getOrder (returns Order) [spring-mvc]"`)
  and endpoints are embedded + get a vector index, so `search` / `search_code`
  surface routes from natural language. New `http_endpoint_id` constraint,
  `http_endpoint_fulltext` + `http_endpoint_embedding` indexes.
  ([#75](https://github.com/tmustafiz/graph-rag/issues/75))
- Spring / Spring Boot bean & dependency-injection graph. New
  `SpringBeanResolver` — a second post-directory-ingest graph pass, after the
  project-model resolver — derives a `Bean` layer from the annotation,
  type-hierarchy and config layers already in Neo4j. Stereotyped classes
  (`@Component` / `@Service` / `@Repository` / `@Controller` /
  `@RestController` / `@Configuration` / `@SpringBootApplication` /
  `@ConfigurationProperties`, plus one level of custom meta-annotated
  stereotype) and `@Bean` factory methods become
  `(:Bean {name, stereotype, scope, primary, bean_type})`, linked
  `(:CodeEntity)-[:IS_BEAN]->(:Bean)`; a `@Configuration` bean
  `-[:PRODUCES]->` its `@Bean` methods. Constructor parameters (incl. Lombok's
  synthetic `@RequiredArgsConstructor`), `@Autowired` / `@Inject` / `@Resource`
  fields and setters resolve to a target `Bean` **by type** — matched against
  each bean's own type and its `EXTENDS` / `IMPLEMENTS` supertypes, unwrapping
  `List<X>` / `Optional<X>` / `ObjectProvider<X>` / `X[]` (recorded as
  `multiplicity`), then narrowed by `@Qualifier` / `@Named` — as
  `(:Bean)-[:INJECTS {via, qualifier, multiplicity}]->(:Bean)`; ambiguous or
  unmatched injections are left on `Bean.unresolved_injections` (JSON) with a
  reason, never guessed. `@Value("${key:default}")` and
  `@ConfigurationProperties(prefix=…)` add `(:Bean)-[:BINDS]->(:ConfigProperty)`.
  New `bean_id` constraint + `bean_fulltext` index; `IngestionPipeline` now
  takes a list of post-ingest resolvers.
  ([#73](https://github.com/tmustafiz/graph-rag/issues/73))
- Java type-hierarchy edges. `JavaParser` now records a type's direct
  supertypes on `CodeEntity` (`extends_types` / `implements_types`,
  import-resolved to FQNs where possible, else the simple name) and
  `GraphWriter` writes `(:CodeEntity)-[:EXTENDS]->(:CodeEntity)` (superclass, or
  an interface's super-interface) and `-[:IMPLEMENTS]->` edges. Foundation for
  injection-target-by-type resolution in the Spring bean model.
  ([#73](https://github.com/tmustafiz/graph-rag/issues/73))
- Lombok member synthesis + generated-sources ingestion. `LombokSynthesizer`
  (inside `JavaParser`) materialises the `CodeEntity`s a compile-time
  annotation processor would generate: `@Getter` / `@Setter` / `@Data` /
  `@Value` → `getX()` / `isX()` / `setX()` per field; `@NoArgsConstructor` /
  `@AllArgsConstructor` / `@RequiredArgsConstructor` (and the `@Data` /
  `@Value` implied ones) → a constructor entity with the right parameter types
  (the `@RequiredArgsConstructor` one is what Spring DI resolves through);
  `@Builder` → `builder()` + a `<Type>Builder` stub; `@Slf4j` and friends → a
  `log` field. Each is flagged `synthetic=true`, `origin="lombok"`; an explicit
  accessor of the same name suppresses its synthetic twin. `CodeEntity` gains
  `synthetic` / `origin`. A directory ingest also parses annotation-processor
  output under `target/generated-sources` / `build/generated` as normal
  `.java`; `GRAG_INGEST_GENERATED_SOURCES=false` skips it.
  ([#71](https://github.com/tmustafiz/graph-rag/issues/71))
- Maven / Gradle project model. New `MavenParser` (`pom.xml`, stdlib
  `xml.etree`) and `GradleParser` (`build.gradle` / `build.gradle.kts` /
  `settings.gradle(.kts)`, tree-sitter `groovy` / `kotlin`) turn build files
  into `(:Module {group, artifact, version, path, build_tool, packages,
  source_roots})` nodes with `(:Module)-[:DEPENDS_ON {scope}]->(:Module)` and
  `-[:DEPENDS_ON_EXTERNAL {gav, scope}]->(:ExternalArtifact)` edges. Maven reads
  `<parent>` inheritance, `<properties>` `${...}` interpolation, the reactor
  `<modules>` list, `<dependencies>` GAV + `<scope>`, and
  `<build><sourceDirectory>`; Gradle does a shallow tree-sitter pass for
  `group` / `version` / `rootProject.name`, `include`, `dependencies { }`
  coordinates (configuration → `scope`), `project(':x')` deps, and `srcDirs`.
  Source-root discovery adds `src/test/java` and `target/generated-sources` /
  `build/generated` when present. On a directory ingest, build files parse
  first and a new `ProjectModelResolver` then wires
  `(:Source)-[:IN_MODULE]->(:Module)` (nearest module dir), promotes sibling
  dependencies (`project(':x')` / matching GAV → `DEPENDS_ON`), and sets
  `external` (bool) on every `(:CodeEntity)-[:IMPORTS]->(:CodeEntity)` edge —
  `false` for first-party / in-project targets, `true` for third-party. New
  `module_path` / `external_artifact_gav` constraints and a `module_fulltext`
  index. ([#70](https://github.com/tmustafiz/graph-rag/issues/70))
- Spring / Java application-config parser (`ConfigFileParser`, stdlib + PyYAML,
  no extra). Handles `application*` / `bootstrap*` (`.yml` / `.yaml` /
  `.properties`) and any `*.properties` / `*.yml` under a `resources`
  directory; registered ahead of `YamlParser`, which still gets Checkov custom
  policies (name-matched `.yml` with `metadata.id` + `definition` is handed
  back) and all other generic YAML. Each file becomes a `ConfigFile` plus a
  flattened `ConfigProperty` list — YAML nesting collapsed to dotted keys
  (list items `[i]`), `.properties` read line-wise (comment markers, `\` line
  continuations, `#---` multi-document separators), real line numbers kept.
  Spring profile resolved from an `application-<profile>` filename or a
  `spring.config.activate.on-profile` key; `${a.b:default}` placeholders become
  `(:ConfigProperty)-[:REFERENCES]->(:ConfigProperty)` edges within the file.
  A `Section` + one `Chunk` per profile makes config searchable via `search`,
  with secret-looking keys (`password` / `secret` / `token` / `credential` /
  `key`) redacted in the chunk text (real value stays on the node). New
  `config_file_path` / `config_property_id` constraints and
  `config_property_fulltext` index. Feeds `@Value` / `@ConfigurationProperties`
  resolution in the Spring bean model.
  ([#72](https://github.com/tmustafiz/graph-rag/issues/72))
- Structured Java annotation model. `JavaParser` now captures annotations on
  types, methods, constructors, fields, and parameters as `Annotation` nodes
  (`(CodeEntity)-[:ANNOTATED_WITH]->(:Annotation {fqn, name, target, attributes,
  line})`), keyed by `(owner, target, fqn, line)`. Attribute values (string /
  number / boolean / class-literal / enum-constant / array / nested annotation)
  are parsed into a map and persisted as a JSON string (`attributes` property);
  the annotation FQN is resolved against the file's imports, falling back to the
  simple name. Type-level annotations (`@RestController` on a class, …), which
  were previously dropped entirely, are now captured. Fields carrying at least
  one annotation are emitted as `field` `CodeEntity`s (`kind` `field`,
  `qualified_name` `<type>#<field>`); plain fields stay folded into the owning
  type's `embed_text` as before. New `Annotation` uniqueness constraint and
  `annotation_name_fulltext` index. Foundation for the Spring bean / MVC /
  Spring-Data models. ([#69](https://github.com/tmustafiz/graph-rag/issues/69))

### Fixed
- Enterprise-Java review sweep (v0.6.0 release gate,
  [#114](https://github.com/tmustafiz/graph-rag/issues/114)–[#131](https://github.com/tmustafiz/graph-rag/issues/131)):
  - **Spring Data repositories are now beans.** New final post-ingest pass
    `SpringInjectionResolver` MERGEs a `(:Bean {stereotype:'Repository'})` +
    `IS_BEAN` for every repository interface (`bean_type` = interface FQN) and
    re-runs injection resolution over the complete annotation + XML + repository
    bean set, so an `@Service` `@Autowired`-ing an XML-only bean or a
    `JpaRepository` (both unresolvable when the first pass ran) gets its
    `INJECTS` edge instead of a `"no matching bean"` entry.
    ([#114](https://github.com/tmustafiz/graph-rag/issues/114),
    [#122](https://github.com/tmustafiz/graph-rag/issues/122))
  - `@Bean` factory methods declared `public` / `static` no longer get a
    `bean_type` like `"Bean public DataSource"` (broke type-based `@Autowired`
    to them). ([#115](https://github.com/tmustafiz/graph-rag/issues/115))
  - `search_code` `stereotype=` / `annotation=` / `module=` filters resolve the
    matching set on the graph first, so a filter is no longer starved by the
    kNN truncation and returning `[]` for a real match.
    ([#117](https://github.com/tmustafiz/graph-rag/issues/117))
  - `get_endpoints(path_glob=…)` substring-matches unless the caller pins an end
    with `^` / `$` — a bare fragment (`"orders"`) no longer silently returns
    `[]`. ([#118](https://github.com/tmustafiz/graph-rag/issues/118))
  - A relative-path directory ingest (`grag ingest examples/spring-boot`) now
    wires `IN_MODULE` / endpoint-module edges — `ProjectModelResolver` compares
    `os.path.abspath` of `Source.path` and `Module.path` instead of a raw string
    prefix (`Source.path` stays stored as ingested). A single-file ingest /
    `ingest_path` / `--watch` now also runs the post-ingest resolvers and the
    generated-source skip, not just directory ingest.
    ([#116](https://github.com/tmustafiz/graph-rag/issues/116),
    [#120](https://github.com/tmustafiz/graph-rag/issues/120))
  - A Gradle root dir's `settings.gradle` no longer nulls the `group` /
    `version` / `packages` its `build.gradle` set on the same `Module`.
    ([#119](https://github.com/tmustafiz/graph-rag/issues/119))
  - Renaming or removing an annotated Java type no longer leaks its `Annotation`
    nodes (deleted with their owner; a global orphan sweep self-heals earlier
    leaks). ([#121](https://github.com/tmustafiz/graph-rag/issues/121))
  - Multi-path request mappings (`@GetMapping({"/a","/b"})`, class-level
    `@RequestMapping({"/v1","/v2"})`) emit one `HttpEndpoint` per
    (method, path). ([#123](https://github.com/tmustafiz/graph-rag/issues/123))
  - Enum method / field / nested-type members (inside `enum_body_declarations`)
    are emitted as `CodeEntity`s.
    ([#124](https://github.com/tmustafiz/graph-rag/issues/124))
  - Lombok: a `boolean isX` field's getter is the field name (not `isIsX()`),
    `@Accessors(fluent=…/chain=…)` is honoured, and `@AllArgsConstructor`
    excludes initialised `final` fields.
    ([#125](https://github.com/tmustafiz/graph-rag/issues/125))
  - Gradle `subprojects {}` / `allprojects {}` dependency blocks are skipped
    rather than attributed to the root module.
    ([#126](https://github.com/tmustafiz/graph-rag/issues/126))
  - Spring Data derived-query subjects tokenise on the PascalCase boundary, so
    `findByOrderId` yields `orderId`, not `derId`.
    ([#127](https://github.com/tmustafiz/graph-rag/issues/127))
  - Maven `${revision}` / `${sha1}` and property-to-property chains interpolate
    to a fixed point. ([#128](https://github.com/tmustafiz/graph-rag/issues/128))
  - Nested `<beans profile="…">` blocks in a Spring XML context are walked
    (their beans were silently skipped); the `profile` is recorded on each bean.
    ([#129](https://github.com/tmustafiz/graph-rag/issues/129))
  - Self-referential JPA associations (`Category.parent` + `Category.children`)
    keep their `RELATES_TO` self-edge.
    ([#130](https://github.com/tmustafiz/graph-rag/issues/130))
  - A `)` / `,` inside an annotation attribute string (`@Pattern(regexp = ")")`)
    no longer truncates the handler parameter scan, so bindings keep their real
    types. ([#131](https://github.com/tmustafiz/graph-rag/issues/131))

## [0.5.0] - 2026-09-06

### Added
- CSS / SCSS / Less stylesheet parser (`StylesheetParser`, opt-in
  `grag-mcp[css]` extra, tree-sitter `css` / `scss` / `less` grammars).
  `.css` / `.scss` / `.sass` / `.less` ingest as `Section` + `Chunk` (no
  `CodeEntity` — CSS has no call graph), so the plain `search` tool covers
  them: one `Section` per file (plus one per top-level `@media` / `@supports`)
  and one `Chunk` per rule, with SCSS nesting flattened into full selector
  paths (`.card .title`, `.card:hover`). Custom properties (`--x`), SCSS
  `$variables`, and `@mixin`s each also get a small name-bearing chunk.
  `@import` / `@use` / `@forward` resolve against the file tree to a new
  `(Source)-[:IMPORTS]->(Source)` edge (Sass built-ins and remote URLs
  skipped). `.sass` indented syntax and grammar-version gaps (`@extend`, some
  `@include` forms) degrade to a partial result with a logged warning.
  `ParsedDocument` gains `source_imports`. Sample under `examples/stylesheets/`.
  ([#66](https://github.com/tmustafiz/graph-rag/issues/66))
- Procedural SQL parsing (`ProceduralSqlExtractor`, run by `SqlParser` on the
  same `grag-mcp[sql]` extra). Stored procedures, functions, packages, package
  bodies, and triggers become `CodeEntity` nodes (`kind` ∈ `package` |
  `package_body` | `procedure` | `function` | `trigger`; packaged routines get
  `parent_qualified_name` = the package). Best-effort `CALLS` between routines,
  plus `READS` / `WRITES` edges to `:DbTable` (from `SELECT` vs
  `INSERT`/`UPDATE`/`DELETE`/`MERGE` in the body) and `ON` (trigger → its
  table). `sqlglot` parses T-SQL procedure bodies as an AST; PL/pgSQL `$$…$$`
  bodies and all of Oracle PL/SQL (packages, triggers) fall back to a
  delimiter-scoped regex sweep — accuracy ceiling documented per dialect in
  `docs/operations.md`. A routine whose body can't be analyzed still yields its
  header entity with a logged warning. `SqlParser` now also claims `.pks` /
  `.pkb` / `.prc` / `.fnc` / `.trg` / `.plsql`; `CodeEntity` gains `reads` /
  `writes` / `trigger_table`. Sample under `examples/sql-schema/procedures/`.
  ([#65](https://github.com/tmustafiz/graph-rag/issues/65))
- SQL schema parser (`SqlParser`, opt-in `grag-mcp[sql]` extra, backed by
  `sqlglot`). `.sql` DDL becomes a database-schema graph — not `CodeEntity` —
  of `:DbTable` / `:DbColumn` (type, nullability, default, PK flag) / `:DbView`
  (incl. materialized) / `:DbIndex` (covered columns) nodes keyed by
  dialect-qualified `qualified_name`. Foreign keys (inline, table-level, and
  `ALTER TABLE … ADD CONSTRAINT`, including when the `ALTER` is in a different
  migration file) yield `REFERENCES` edges at column and table level; a view's
  `SELECT` yields `DEPENDS_ON` edges (CTE names excluded); `HAS_COLUMN` /
  `HAS_INDEX` link a table to its parts. Dialect is `settings.sql_dialect`
  (env `GRAG_SQL_DIALECT`), overridable per file with a
  `-- grag:dialect=<name>` marker; an unknown dialect or unparseable file logs
  a warning and yields an empty `Source`. Tables and views are embedded and get
  vector + full-text indexes; wiring them into `search_code` / a
  `search_schema` tool is a follow-up. Sample migrations under
  `examples/sql-schema/`.
  ([#64](https://github.com/tmustafiz/graph-rag/issues/64))
- React-aware enrichment (`ReactEnricher`, run automatically by
  `JavaScriptParser` on `.jsx` / `.tsx` and `react`-importing `.js` / `.ts`).
  A `function` / `class` `CodeEntity` that returns JSX or extends
  `React.Component` is retagged `kind="component"`; each PascalCase JSX element
  it mounts that resolves to a local definition or an import becomes a new
  `(component)-[:RENDERS]->(component)` edge (lowercase host tags and
  unresolved names skipped, like `calls`); the hook calls (`useState`,
  `useEffect`, custom `useX`) and prop names (first-argument destructuring or
  `props.` member accesses) it uses are folded into `embed_text` / `signature`
  so `search_code("component that uses useAuth")` can match. `CodeEntity` gains
  a `renders` list; `GraphWriter` writes the `RENDERS` edge. Prop types and
  lifecycle call graphs are out of scope.
  ([#63](https://github.com/tmustafiz/graph-rag/issues/63))
- JavaScript / TypeScript source parser (`JavaScriptParser`, opt-in
  `grag-mcp[js]` extra, same `tree-sitter` backend). One parser for
  `.js` / `.mjs` / `.cjs` / `.jsx` / `.ts` / `.tsx` — TS and JSX are grammar
  variants of the same parse. Each file becomes a `module` `CodeEntity`
  (`qualified_name` is the project-relative path — nearest `package.json` /
  `tsconfig.json` ancestor — dotted and extension-stripped, `index` collapsed
  to its directory) carrying the file's `imports`, plus one entity per
  top-level `function` / `class` (+ `method` / `constructor`) / exported
  arrow-`const`, and signature-only `interface` / `type` / `enum`. `IMPORTS`
  covers ESM (`import`, `export … from`, `export *`, dynamic `import()`) and
  CommonJS (`require`); relative specifiers resolve against the project tree
  (named imports as `module.symbol`), bare specifiers (`react`) stay verbatim.
  Best-effort static `CALLS` for local, imported, and `this.*` shapes — same
  no-type-inference policy as `PythonParser`. JSDoc becomes
  `docstring`/`embed_text`. Sample project under `examples/js/`.
  ([#62](https://github.com/tmustafiz/graph-rag/issues/62))
- Java source parser (`JavaParser`, opt-in `grag-mcp[java]` extra, backed by
  `tree-sitter` + `tree-sitter-language-pack`). A `.java` file becomes a
  `Source` plus one `CodeEntity` per type (`class` / `interface` / `enum` /
  `record` / `annotation`) and per `method` / `constructor`, with
  package-prefixed, overload-safe `qualified_name`s, `CONTAINS` nesting,
  Javadoc as `docstring`/`embed_text`, `IMPORTS` from all four import forms,
  and best-effort static `CALLS` for the resolvable shapes (unqualified /
  `this` / `super` / statically-imported / `Type.method` on a known type) —
  same no-type-inference policy as `PythonParser`. Fields fold into the
  owning type's `embed_text`; there is no file-level `module` entity. Feeds
  `search_code` / `get_neighbors` / `compute-centrality` with no
  retrieval-side change. Sample tree under `examples/java/`.
  ([#61](https://github.com/tmustafiz/graph-rag/issues/61))

### Changed
- Code parsing is no longer Python-framed. `CodeEntity` carries a `language`
  property, `CodeSearchResult` exposes it, and `qualified_name` is documented
  as the single cross-language unique key that each parser must namespace.
  MCP instructions, `search` / `search_code` tool descriptions, the
  `compute-centrality` hint, README, and `docs/ARCHITECTURE.md` (new "Adding
  a language" section) now say "source code" rather than "Python". Groundwork
  for the Java / JavaScript-TypeScript / SQL / PL-SQL / CSS parsers; Python
  ingestion behavior is unchanged.
  ([#60](https://github.com/tmustafiz/graph-rag/issues/60))
- `examples/agent-memory/` instructions snippets (`AGENTS.md.example`,
  `copilot/copilot-instructions.md.example`): firmer, more directive wording
  so an agent actually writes memory during a task instead of treating it as
  optional — enumerated `remember` triggers per `kind` and an explicit
  "before you end your turn" checkpoint that folds saving into task
  completion. No behavior change; prompt text only.

## [0.4.0] - 2026-09-05

### Added
- `examples/agent-memory/`: copy-paste templates for a coding agent in a
  *downstream* project to use graph-rag's `remember`/`recall`/`forget` tools
  as its own persistent working memory, for both **Claude Code** and **VS
  Code Copilot Chat** — an always-on instructions snippet (`AGENTS.md` /
  `copilot-instructions.md`), a skill / prompt file, and a `SessionStart`
  hook (`session_start_recall.py`, using the `mcp` Python client) that
  recalls relevant memories into context automatically at the start of a
  session. ([#49](https://github.com/tmustafiz/graph-rag/issues/49))
- Opt-in split deployment: `docker-compose.knowledge.yml` /
  `docker-compose.memory.yml` run the knowledge base and agent memory as fully
  independent stacks — separate Neo4j, separate MCP server, optionally
  separate hosts — instead of `docker-compose.yml`'s combined default (still
  unchanged). Both build from the same `Dockerfile`: a `knowledge` target
  (full parser stack, incl. `[pdf]`; content-identical to the default image,
  just pinned to `--role knowledge`) and a `memory` target (bare package, no
  parsers, no `pymupdf` — smaller image and CVE-scan surface, pinned to
  `--role memory`). CI builds and scans both.
  ([#45](https://github.com/tmustafiz/graph-rag/issues/45))
- `serve-mcp --role knowledge|memory|all` (default `all`, unchanged behavior).
  `knowledge` and `memory` each start a standalone MCP server with only that
  half of the tools — `search`/`search_code`/`search_policies`/`get_section`/
  `get_outline`/`list_sources`/`find_policies_for`/`get_neighbors`/
  `get_central_code_entities`/`cite`/`ingest_path` for `knowledge`;
  `remember`/`recall`/`forget` for `memory` — so the knowledge base and agent
  memory can run as independent deployments, each against its own Neo4j.
  `POST /ingest` is only mounted for `knowledge`/`all`.
  ([#44](https://github.com/tmustafiz/graph-rag/issues/44))

### Fixed
- `recall(about_qualified_name=...)` could silently return zero results in a
  database with no `CodeEntity` nodes — the link was represented only as an
  `(:AgentMemory)-[:ABOUT]->(:CodeEntity)` edge, so the filter pattern could
  never match. `about_qualified_name` is now also stored as a plain property
  on `AgentMemory` (the source of truth for `recall`'s filter); the edge is
  still merged, best-effort, when a matching `CodeEntity` exists in the same
  database. ([#43](https://github.com/tmustafiz/graph-rag/issues/43))

## [0.3.0] - 2026-09-05

### Added
- Opt-in **query rewriting** ahead of `search` / `search_code` /
  `search_policies`. `GRAG_QUERY_REWRITE=1` rewrites a query into a few variants
  (acronym expansion, multi-part splitting, paraphrase), runs hybrid search for
  each, and fuses the hit sets (best `[0, 1]` score per hit) before the
  reranker/top-k stage. Two backends: an offline `HeuristicQueryRewriter`
  (built-in acronym map + `GRAG_QUERY_REWRITE_SYNONYMS` JSON override, no
  network) by default, and an opt-in `LlmQueryRewriter` when
  `GRAG_QUERY_REWRITE_MODEL` is set — an OpenAI-compatible `POST
  /v1/chat/completions` call (`GRAG_QUERY_REWRITE_API_BASE` points it at a local
  Ollama / LM Studio / vLLM endpoint) that fails at startup without a key and
  degrades to the unrewritten query on any request error.
  `GRAG_QUERY_REWRITE_MAX_QUERIES` (default 3) caps the variant count;
  `grag-mcp eval-retrieval --rewrite` measures a pass (composable with
  `--rerank`). Off by default, no new dependencies.
  ([#40](https://github.com/tmustafiz/graph-rag/issues/40))
- Config-selected hosted embedding backends. `GRAG_EMBEDDING_PROVIDER` selects
  `openai`, `ollama`, `voyage`, `cohere`, or `gemini` (unset keeps the local
  `all-MiniLM-L6-v2` — still the default, no API key). Each backend is a plain
  `httpx` REST call; no provider SDKs are added. `GRAG_EMBEDDING_MODEL` sets the
  model id and `GRAG_EMBEDDING_API_BASE` the endpoint (OpenAI-compatible
  gateways, non-local Ollama). `build_embedder()` probes the provider once at
  startup and fails fast if the vector width doesn't match `EMBEDDING_DIMENSIONS`
  rather than corrupting the index mid-ingest.
  ([#10](https://github.com/tmustafiz/graph-rag/issues/10))
- Optional cross-encoder reranking for `search` / `search_code` /
  `search_policies`. Set `GRAG_RERANK=1` to re-score the fused hybrid-search
  shortlist with `cross-encoder/ms-marco-MiniLM-L-6-v2` (read query + document
  together) before truncating to `top_k`; the fused score breaks ties. Off by
  default. The model is not baked into the image and there is no implicit Hub
  download — `make fetch-reranker` vendors it, or set `GRAG_RERANK_MODEL` to a
  local path (or a Hub id to allow a pull); with reranking on and nothing
  resolvable the process exits at startup. Search results gain a `rerank_score`
  field (the raw cross-encoder logit, `null` when off); `score` keeps its
  `[0, 1]` fused meaning unchanged. `grag-mcp eval-retrieval --rerank` prints a
  baseline-vs-reranked comparison; a naive-vector / hybrid / hybrid+rerank table
  is in the README. ([#14](https://github.com/tmustafiz/graph-rag/issues/14))

### Changed
- `grag-mcp prune-memory` runs with no arguments — the decay score is now
  `(1 + access_count) * exp(-days_since_last_recall / 30)` (reads
  `last_accessed_at`, which nothing used before), with a default `--threshold`
  of `0.5` (a never-recalled memory decays out ~3 weeks after creation; a
  reinforced one lasts months). Adds `--dry-run` (list what would be
  soft/hard-deleted, write nothing), `--list-important` (review the
  never-decaying `importance=True` memories), a `make prune` target, and a
  scheduling recipe in `docs/operations.md`.
- `recall` ranks by semantic relevance **plus** a flat boost for
  `importance=True` memories and a recency/frequency boost (a saturating
  function of `access_count` decayed by time since last recall) — previously
  those signals only fed pruning. `recall` also takes optional `kind`,
  `about_qualified_name`, and `session_id` filters, returns `last_accessed_at`
  and `access_count` on each hit, only reinforces hits above a similarity
  floor, and no longer 500s on a query with Lucene metacharacters.

## [0.2.0] - 2026-09-03

### Added
- A multi-arch (`linux/amd64` + `linux/arm64`) runtime image published to
  `ghcr.io/tmustafiz/graph-rag` on every `vX.Y.Z` tag (new `image` job in
  `release.yml`). Tags: `X.Y.Z`, `X.Y`, `sha-…`, and `latest` for a
  non-prerelease release.
- Tracked agent configuration: `AGENTS.md` (cross-agent guide),
  `.github/copilot-instructions.md` (auto-loaded by GitHub Copilot),
  `.github/prompts/*.prompt.md` (setup / run / deploy / add-a-parser /
  cut-a-release recipes), and `.github/workflows/copilot-setup-steps.yml`
  (pre-provisions the Copilot coding agent's environment). `CLAUDE.md` and the
  editor rule-files stay in a separate repo.
- Published to PyPI as **`grag-mcp`** — `uvx grag-mcp` / `uv tool install grag-mcp` /
  `pipx install grag-mcp`, no clone needed. `.github/workflows/release.yml`
  builds and publishes via Trusted Publishing on a `vX.Y.Z` tag push.
  (The importable package stays `graph_rag`; the CLI command is `grag-mcp`.)
- CI job that builds the Docker image and scans it with Trivy, failing on
  fixable HIGH/CRITICAL CVEs. Also runs weekly so newly-disclosed CVEs against
  an unchanged image are caught.
- `grag-mcp serve-mcp --stdio` — serve the MCP server over stdio for clients
  that launch it as a subprocess (Claude Desktop, etc.). HTTP stays the default.
- `docs/ARCHITECTURE.md` (present-tense design + component map) and
  `docs/ROADMAP.md` (pointer to the GitHub project board / milestones).
- `.github/release.yml` so GitHub release notes are auto-categorized by label.
- `LICENSE` (Apache-2.0) and `NOTICE`; `license`, `keywords`, `classifiers`,
  and `[project.urls]` in `pyproject.toml`.
- `CONTRIBUTING.md` (with the code-convention rules), `CODE_OF_CONDUCT.md`,
  `SECURITY.md`.
- GitHub Actions CI (`ruff check`, `ruff format --check`, `pytest`),
  issue/PR templates, and Dependabot config.
- `py.typed` marker so downstream type checkers see the package's hints.
- `scripts/fetch_model.py` and `make fetch-model` for the local embedding model.

### Changed
- The retrieval eval (`grag-mcp eval-retrieval`) covers `search_code` and
  `search_policies`, not just prose `search`, plus negative cases and the
  `top_k` boundary — 5 cases over 2 fixtures grew to 13 over 4. An `EvalCase`
  now carries a `tool` and an `expect_match` flag; the fixture corpus gains a
  `scheduler.py` module and a `policies.yaml`. Existing eval-set rows are
  unchanged (they default to `tool: search`).
- The Docker image bakes the embedding model in at `/opt/models/all-MiniLM-L6-v2`
  (the builder stage runs `scripts/fetch_model.py`), so `docker compose up` needs
  no `huggingface.co` access for embeddings. `SentenceTransformerEmbedder` now
  resolves the model via `GRAG_EMBEDDING_MODEL` (a directory or a Hub repo id) →
  the baked-in image copy → `models/` in a checkout → the Hub id, replacing a
  `Path(__file__).parents[4]` lookup that silently missed in the installed wheel
  layout and always fell through to the Hub.
- The PDF parser cuts section bodies at the `(page, y)` coordinates of the
  outline destinations instead of at page boundaries. Previously, when several
  headings shared a page, each leaf section re-extracted and re-embedded the
  whole page — on the sample FSx guide that was 46% of chunks byte-identical to
  another. It also drops recurring running headers/footers, NFKC-normalizes text
  (so `ﬁle` → `file`), keeps a parent heading's preamble instead of discarding
  it, and no longer produces an empty result for a PDF that has no outline.
- The YAML parser no longer fails a whole file when a Checkov policy has a
  non-scalar (list/dict) value where a string is expected — `name`, `category`,
  `severity`, `guideline`, and `provider` degrade to absent, and a policy whose
  `metadata.id` isn't a scalar falls back to generic chunking. `_is_checkov_policy`
  now also requires a `definition`, so unrelated YAML with a stray `metadata.id`
  isn't misrouted.
- All `docker compose` base images are overridable via `.env`
  (`NEO4J_IMAGE`, `BUILDER_IMAGE`, `RUNTIME_IMAGE`, `UV_IMAGE`) so
  restricted environments can build against an approved hardened registry
  (e.g. Docker Hardened Images) without editing tracked files. Defaults
  are unchanged. See docs/operations.md.
- The Neo4j service now runs unchanged on `dhi.io/neo4j:2026` (Docker
  Hardened Image): the healthcheck uses `cypher-shell` instead of `wget`,
  `NEO4J_PLUGINS` is overridable (set it empty for images with no
  `wget`/`awk`), and the plugins volume mounts at Neo4j's default plugin
  dir so preloaded APOC/GDS jars load without an entrypoint-written
  `server.directories.plugins`.
- The app image builds and runs on Docker Hardened Images end to end
  (`BUILDER_IMAGE=dhi.io/python:3-dev`, `RUNTIME_IMAGE=dhi.io/python:3`).
  The `Dockerfile` now chowns and `USER`s by numeric uid 65532 instead of
  the `nonroot` name so the runtime base is interchangeable; torch runs
  on `dhi.io/python:3` despite it having no system `libgomp` (the wheel
  bundles OpenMP).
- README restructured for first-time visitors (positioning, client setup
  snippets, tools table, architecture diagram).
- The embedding model is no longer vendored in git — fetch it with
  `make fetch-model` (falls back to a first-use Hub download otherwise).
- The repo ships no document corpus. `make ingest` now requires
  `INGEST_PATH` (`make ingest INGEST_PATH=…`); bring your own files.
- `grag-mcp eval-retrieval` / `make eval` is self-contained: it ingests a
  small fixture corpus (`src/graph_rag/eval/corpus/`) before running, so it no
  longer depends on a specific document being ingested first. Added a CI job
  that runs it against a Neo4j service container.
- The `Dockerfile` is now a multi-stage build: the app venv is built against a
  standalone CPython 3.13 and copied into `gcr.io/distroless/cc-debian13:nonroot`
  — no shell, no package manager, non-root by default. Base-OS High/Critical
  CVEs go from 2C/5H to 0; the runtime image scans clean at High/Critical.

### Fixed
- `search` / `search_code` / `search_policies` no longer 500 when the query
  contains a Lucene metacharacter (a pasted CLI flag like `--dry-run`, a
  `resource:type` string, code, a path). The query is escaped before it reaches
  `db.index.fulltext.queryNodes`, and any residual parser error (e.g. a bare
  `AND`/`OR`) is caught so the search degrades to vector-only instead of
  failing.

### Removed
- `docs/IMPLEMENTATION_PLAN.md` and `docs/progress.md` — planning, roadmap, and
  release notes now live in GitHub Issues, Milestones, the project board, and
  Releases. Architecture that outlived the plan moved to `docs/ARCHITECTURE.md`.
- Agent-instruction files (`CLAUDE.md`, `AGENTS.md`) are no longer tracked here;
  they live in a separate repository.
- `training-docs/` is no longer tracked. The three sample Checkov policies moved
  to `examples/checkov-policies/`; the bundled AWS PDFs are gone (also purged
  from git history).

## [0.1.0] - 2026-08-26

Initial implementation: Graph RAG pipeline (PDF / Markdown / Python / YAML
ingestion into Neo4j), hybrid vector + full-text retrieval, GDS PageRank over
the code graph, agent working-memory with decay pruning, and an MCP server
(Streamable HTTP) exposing lookup + memory tools. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how it fits together.

[Unreleased]: https://github.com/tmustafiz/graph-rag/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/tmustafiz/graph-rag/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/tmustafiz/graph-rag/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/tmustafiz/graph-rag/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/tmustafiz/graph-rag/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/tmustafiz/graph-rag/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/tmustafiz/graph-rag/releases/tag/v0.1.0
