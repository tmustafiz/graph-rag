import textwrap
from pathlib import Path

from graph_rag.graph.graph_writer import GraphWriter
from graph_rag.ingest.parser_registry import ParserRegistry
from graph_rag.ingest.parsers import ConfigFileParser, YamlParser

_CHECKOV_POLICY = """
metadata:
  id: "CKV2_CUSTOM_1"
  name: "Ensure something"
definition:
  cond_type: "attribute"
  resource_types:
    - "aws_db_instance"
  attribute: "storage_encrypted"
  operator: "equals"
  value: true
"""


def _by_key(document, key: str, profile: str | None = None):
    matches = [
        prop for prop in document.config_properties if prop.key == key and prop.profile == profile
    ]
    assert len(matches) == 1, f"expected one {key!r} (profile={profile!r}), got {matches}"
    return matches[0]


def test_can_handle_matches_spring_config_names_and_all_properties() -> None:
    assert ConfigFileParser.can_handle(Path("application.yml"))
    assert ConfigFileParser.can_handle(Path("application-dev.yaml"))
    assert ConfigFileParser.can_handle(Path("bootstrap.properties"))
    assert ConfigFileParser.can_handle(Path("messages.properties"))
    assert ConfigFileParser.can_handle(Path("app/src/main/resources/logback-spring.yml"))
    assert not ConfigFileParser.can_handle(Path("k8s/deployment.yaml"))
    assert not ConfigFileParser.can_handle(Path("notes.md"))


def test_can_handle_defers_checkov_policy_to_yaml_parser(tmp_path: Path) -> None:
    policy = tmp_path / "application.yml"
    policy.write_text(_CHECKOV_POLICY)
    assert not ConfigFileParser.can_handle(policy)


def test_properties_flatten_comments_continuation_and_filename_profile(tmp_path: Path) -> None:
    path = tmp_path / "application-dev.properties"
    path.write_text(
        textwrap.dedent(
            """\
            # datasource
            spring.datasource.url=jdbc:postgresql://db:5432/app
            ! legacy comment marker
            spring.datasource.username = svc
            app.description=first line \\
            and second line
            servers[0]=alpha
            servers[1]=beta
            """
        )
    )

    document = ConfigFileParser().parse(path)

    assert document.config_files[0].format == "properties"
    assert {prop.profile for prop in document.config_properties} == {"dev"}
    url = _by_key(document, "spring.datasource.url", "dev")
    assert url.value == "jdbc:postgresql://db:5432/app"
    assert url.origin_line == 2
    assert _by_key(document, "spring.datasource.username", "dev").value == "svc"
    assert _by_key(document, "app.description", "dev").value == "first line and second line"
    assert _by_key(document, "servers[1]", "dev").value == "beta"


def test_yaml_nesting_flattened_to_dotted_keys_with_line_numbers(tmp_path: Path) -> None:
    path = tmp_path / "application.yml"
    path.write_text(
        textwrap.dedent(
            """\
            server:
              port: 8080
            spring:
              datasource:
                url: jdbc:postgresql://db/app
            management:
              endpoints:
                web:
                  exposure:
                    include:
                      - health
                      - info
            """
        )
    )

    document = ConfigFileParser().parse(path)

    port = _by_key(document, "server.port")
    assert port.value == "8080"
    assert port.origin_line == 2
    assert _by_key(document, "spring.datasource.url").value == "jdbc:postgresql://db/app"
    assert _by_key(document, "management.endpoints.web.exposure.include[0]").value == "health"
    assert _by_key(document, "management.endpoints.web.exposure.include[1]").value == "info"


def test_yaml_multi_doc_and_on_profile_marker(tmp_path: Path) -> None:
    path = tmp_path / "application.yml"
    path.write_text(
        textwrap.dedent(
            """\
            server:
              port: 8080
            ---
            spring:
              config:
                activate:
                  on-profile: prod
            server:
              port: 9090
            """
        )
    )

    document = ConfigFileParser().parse(path)

    assert _by_key(document, "server.port", None).value == "8080"
    assert _by_key(document, "server.port", "prod").value == "9090"


def test_placeholder_creates_reference_edge_between_properties(tmp_path: Path) -> None:
    path = tmp_path / "application.yml"
    path.write_text(
        textwrap.dedent(
            """\
            app:
              host: db.internal
              url: jdbc://${app.host}:5432/app
              external: ${ENV_ONLY:fallback}
            """
        )
    )

    document = ConfigFileParser().parse(path)

    host = _by_key(document, "app.host")
    url = _by_key(document, "app.url")
    assert url.references == [host.id]
    assert _by_key(document, "app.external").references == []

    pairs = GraphWriter._config_property_reference_pairs(document)
    assert {"from": url.id, "to": host.id} in pairs


def test_secret_values_redacted_in_chunk_text_but_key_and_node_value_kept(tmp_path: Path) -> None:
    path = tmp_path / "application.properties"
    path.write_text(
        textwrap.dedent(
            """\
            spring.datasource.password=s3cr3t
            api.token=abc123
            app.name=billing
            """
        )
    )

    document = ConfigFileParser().parse(path)

    assert _by_key(document, "spring.datasource.password").value == "s3cr3t"
    chunk_text = "\n".join(chunk.text for chunk in document.chunks)
    assert "s3cr3t" not in chunk_text
    assert "abc123" not in chunk_text
    assert "spring.datasource.password = ***" in chunk_text
    assert "app.name = billing" in chunk_text


def test_registry_routes_config_here_and_checkov_to_yaml_parser(tmp_path: Path) -> None:
    registry = ParserRegistry()
    assert isinstance(registry.for_path(Path("application.yml")), ConfigFileParser)
    assert isinstance(registry.for_path(Path("db.properties")), ConfigFileParser)
    assert isinstance(registry.for_path(Path("policy.yaml")), YamlParser)

    policy = tmp_path / "application.yaml"
    policy.write_text(_CHECKOV_POLICY)
    assert isinstance(registry.for_path(policy), YamlParser)


def test_graph_writer_config_property_rows_shape(tmp_path: Path) -> None:
    path = tmp_path / "application.yml"
    path.write_text("server:\n  port: 8080\n")

    document = ConfigFileParser().parse(path)
    rows = GraphWriter._config_property_rows(document)

    assert rows == [
        {
            "id": document.config_properties[0].id,
            "file_path": str(path),
            "key": "server.port",
            "value": "8080",
            "profile": None,
            "origin_line": 2,
        }
    ]
