import textwrap
from pathlib import Path

from graph_rag.graph.graph_writer import GraphWriter
from graph_rag.ingest.parsers import MavenParser

_PARENT_POM = """\
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.acme.platform</groupId>
  <artifactId>platform-parent</artifactId>
  <version>2.4.0</version>
  <packaging>pom</packaging>
  <modules>
    <module>core-domain</module>
    <module>web-app</module>
  </modules>
</project>
"""

_CHILD_POM = """\
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>com.acme.platform</groupId>
    <artifactId>platform-parent</artifactId>
    <version>2.4.0</version>
  </parent>
  <artifactId>web-app</artifactId>
  <properties>
    <spring.version>6.1.4</spring.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>com.acme.platform</groupId>
      <artifactId>core-domain</artifactId>
      <version>${project.version}</version>
    </dependency>
    <dependency>
      <groupId>org.springframework</groupId>
      <artifactId>spring-context</artifactId>
      <version>${spring.version}</version>
    </dependency>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <version>5.10.0</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
</project>
"""


def test_can_handle_only_pom_xml() -> None:
    assert MavenParser.can_handle(Path("service/pom.xml"))
    assert not MavenParser.can_handle(Path("build.gradle"))
    assert not MavenParser.can_handle(Path("pom.xml.bak"))


def test_parent_pom_yields_module_and_reactor_edges(tmp_path: Path) -> None:
    pom = tmp_path / "pom.xml"
    pom.write_text(_PARENT_POM)

    document = MavenParser().parse(pom)

    module = document.modules[0]
    assert (module.group, module.artifact, module.version) == (
        "com.acme.platform",
        "platform-parent",
        "2.4.0",
    )
    assert module.build_tool == "maven"
    assert module.packages == ["com.acme.platform"]
    reactor = {Path(dep.target_path).name for dep in document.module_dependencies}
    assert reactor == {"core-domain", "web-app"}
    assert all(dep.scope == "reactor" for dep in document.module_dependencies)


def test_child_pom_inherits_parent_and_interpolates_versions(tmp_path: Path) -> None:
    pom = tmp_path / "web-app" / "pom.xml"
    pom.parent.mkdir()
    pom.write_text(_CHILD_POM)

    document = MavenParser().parse(pom)

    module = document.modules[0]
    assert module.group == "com.acme.platform"  # inherited from <parent>
    assert module.artifact == "web-app"
    assert module.version == "2.4.0"  # inherited

    by_artifact = {a.artifact: a for a in document.external_artifacts}
    assert by_artifact["core-domain"].version == "2.4.0"  # ${project.version}
    assert by_artifact["spring-context"].version == "6.1.4"  # ${spring.version}

    scopes = {dep.target_gav: dep.scope for dep in document.module_dependencies}
    assert scopes["org.springframework:spring-context"] == "compile"
    assert scopes["org.junit.jupiter:junit-jupiter"] == "test"


_REVISION_POM = """\
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.acme</groupId>
  <artifactId>ci-friendly</artifactId>
  <version>${revision}</version>
  <properties>
    <revision>1.2.3</revision>
    <lib.version>${revision}</lib.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>com.acme</groupId>
      <artifactId>shared</artifactId>
      <version>${lib.version}</version>
    </dependency>
  </dependencies>
</project>
"""


def test_revision_and_chained_properties_resolve_to_a_fixed_point(tmp_path: Path) -> None:
    pom = tmp_path / "pom.xml"
    pom.write_text(_REVISION_POM)

    document = MavenParser().parse(pom)

    assert document.modules[0].version == "1.2.3"  # ${revision}
    shared = {a.artifact: a for a in document.external_artifacts}["shared"]
    assert shared.version == "1.2.3"  # ${lib.version} -> ${revision} -> 1.2.3


def test_source_roots_include_existing_generated_sources(tmp_path: Path) -> None:
    pom = tmp_path / "pom.xml"
    pom.write_text(
        textwrap.dedent(
            """\
            <project xmlns="http://maven.apache.org/POM/4.0.0">
              <groupId>com.acme</groupId>
              <artifactId>svc</artifactId>
              <version>1.0.0</version>
              <build><sourceDirectory>src/main/kotlin</sourceDirectory></build>
            </project>
            """
        )
    )
    (tmp_path / "target" / "generated-sources").mkdir(parents=True)

    roots = {Path(root).relative_to(tmp_path).as_posix() for root in document_roots(pom)}
    assert roots == {"src/main/kotlin", "src/test/java", "target/generated-sources"}


def document_roots(pom: Path) -> list[str]:
    return MavenParser().parse(pom).modules[0].source_roots


def test_malformed_pom_yields_source_with_no_module(tmp_path: Path) -> None:
    pom = tmp_path / "pom.xml"
    pom.write_text("<project><unclosed>")

    document = MavenParser().parse(pom)

    assert document.source.source_type == "maven"
    assert document.modules == []


def test_graph_writer_module_dependency_pairs_split_internal_and_external(tmp_path: Path) -> None:
    pom = tmp_path / "web-app" / "pom.xml"
    pom.parent.mkdir()
    pom.write_text(_CHILD_POM)

    document = MavenParser().parse(pom)
    external = GraphWriter._module_depends_on_external_pairs(document)
    internal = GraphWriter._module_depends_on_pairs(document)

    assert internal == []  # sibling promotion happens later, in the resolver
    assert {pair["gav"] for pair in external} == {
        "com.acme.platform:core-domain",
        "org.springframework:spring-context",
        "org.junit.jupiter:junit-jupiter",
    }
