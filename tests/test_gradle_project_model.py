import textwrap
from pathlib import Path

from graph_rag.ingest.parsers import GradleParser

_GROOVY_BUILD = """\
group = "com.acme.platform"
version = "1.2.3"

dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-web:3.2.0'
    api "com.google.guava:guava:33.0.0-jre"
    testImplementation 'org.junit.jupiter:junit-jupiter:5.10.0'
    implementation project(':core-domain')
}

sourceSets {
    main {
        java {
            srcDirs 'src/main/java', 'src/generated/java'
        }
    }
}
"""

_KOTLIN_BUILD = """\
group = "com.acme.platform"
version = "1.2.3"

dependencies {
    implementation("org.springframework.boot:spring-boot-starter-web:3.2.0")
    api("com.google.guava:guava:33.0.0-jre")
    testImplementation(project(":core-domain"))
}
"""

_SETTINGS = """\
rootProject.name = "acme-parent"
include ":core-domain", ":web-app"
include(":billing")
"""


def test_can_handle_build_and_settings_files() -> None:
    assert GradleParser.can_handle(Path("app/build.gradle"))
    assert GradleParser.can_handle(Path("app/build.gradle.kts"))
    assert GradleParser.can_handle(Path("settings.gradle"))
    assert GradleParser.can_handle(Path("settings.gradle.kts"))
    assert not GradleParser.can_handle(Path("pom.xml"))


def test_groovy_build_extracts_coordinates_scope_project_dep_and_source_dirs(
    tmp_path: Path,
) -> None:
    build = tmp_path / "web-app" / "build.gradle"
    build.parent.mkdir()
    build.write_text(_GROOVY_BUILD)

    document = GradleParser().parse(build)

    module = document.modules[0]
    assert (module.group, module.version, module.build_tool) == (
        "com.acme.platform",
        "1.2.3",
        "gradle",
    )
    assert module.packages == ["com.acme.platform"]

    by_artifact = {a.artifact: a for a in document.external_artifacts}
    assert by_artifact["guava"].version == "33.0.0-jre"
    scopes = {d.target_gav: d.scope for d in document.module_dependencies if d.target_gav}
    assert scopes["org.springframework.boot:spring-boot-starter-web"] == "implementation"
    assert scopes["org.junit.jupiter:junit-jupiter"] == "testImplementation"
    assert scopes["project:core-domain"] == "implementation"

    roots = {Path(root).relative_to(build.parent).as_posix() for root in module.source_roots}
    assert {"src/main/java", "src/test/java", "src/generated/java"} <= roots


def test_kotlin_dsl_build_extracts_coordinates_and_project_dep(tmp_path: Path) -> None:
    build = tmp_path / "build.gradle.kts"
    build.write_text(_KOTLIN_BUILD)

    document = GradleParser().parse(build)

    assert document.modules[0].group == "com.acme.platform"
    gavs = {a.gav for a in document.external_artifacts}
    assert gavs == {
        "org.springframework.boot:spring-boot-starter-web",
        "com.google.guava:guava",
    }
    project_deps = {d.target_gav for d in document.module_dependencies if d.target_gav}
    assert "project:core-domain" in project_deps


def test_settings_file_yields_root_name_and_reactor_edges(tmp_path: Path) -> None:
    settings = tmp_path / "settings.gradle"
    settings.write_text(_SETTINGS)

    document = GradleParser().parse(settings)

    assert document.modules[0].artifact == "acme-parent"
    included = {Path(d.target_path).name for d in document.module_dependencies}
    assert included == {"core-domain", "web-app", "billing"}
    assert all(d.scope == "reactor" for d in document.module_dependencies)


_ROOT_BUILD_WITH_SUBPROJECTS = """\
group = "com.acme.platform"
version = "1.0.0"

subprojects {
    dependencies {
        implementation 'com.google.guava:guava:33.0.0-jre'
    }
}

dependencies {
    implementation 'org.slf4j:slf4j-api:2.0.9'
}
"""


def test_subprojects_block_dependencies_are_not_attributed_to_the_root(tmp_path: Path) -> None:
    build = tmp_path / "build.gradle"
    build.write_text(_ROOT_BUILD_WITH_SUBPROJECTS)

    document = GradleParser().parse(build)

    gavs = {a.gav for a in document.external_artifacts}
    assert "org.slf4j:slf4j-api" in gavs  # the root's own dependency
    assert "com.google.guava:guava" not in gavs  # belongs to the subprojects


def test_unparseable_gradle_still_yields_a_module(tmp_path: Path) -> None:
    build = tmp_path / "build.gradle"
    build.write_text(textwrap.dedent("this is not ( valid groovy {{{"))

    document = GradleParser().parse(build)

    assert document.source.source_type == "gradle"
    assert len(document.modules) == 1
    assert document.modules[0].build_tool == "gradle"
