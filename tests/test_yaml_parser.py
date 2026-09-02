from pathlib import Path

from graph_rag.ingest.parsers.yaml_parser import YamlParser

_CHECKOV_POLICY = """
metadata:
  id: "CKV2_CUSTOM_1"
  name: "Ensure RDS instances are encrypted at rest"
  category: "GENERAL_SECURITY"
  severity: "HIGH"
  guideline: "https://example.com/guidance"
scope:
  provider: "aws"
definition:
  and:
    - cond_type: "attribute"
      resource_types:
        - "aws_db_instance"
      attribute: "storage_encrypted"
      operator: "equals"
      value: true
    - or:
        - cond_type: "attribute"
          resource_types:
            - "aws_db_instance"
            - "aws_rds_cluster"
          attribute: "kms_key_id"
          operator: "exists"
"""

_GENERIC_YAML = """
name: my-service
replicas: 3
labels:
  team: platform
"""


def test_checkov_policy_becomes_policy_rule(tmp_path: Path) -> None:
    path = tmp_path / "encrypted_rds.yaml"
    path.write_text(_CHECKOV_POLICY)

    document = YamlParser().parse(path)

    assert len(document.policy_rules) == 1
    rule = document.policy_rules[0]
    assert rule.id == "CKV2_CUSTOM_1"
    assert rule.name == "Ensure RDS instances are encrypted at rest"
    assert rule.category == "GENERAL_SECURITY"
    assert rule.severity == "HIGH"
    assert rule.guideline == "https://example.com/guidance"
    assert rule.provider == "aws"
    assert rule.file_path == str(path)
    assert rule.resource_types == ["aws_db_instance", "aws_rds_cluster"]
    assert document.sections == []
    assert document.chunks == []


def test_checkov_embed_text_includes_key_fields(tmp_path: Path) -> None:
    path = tmp_path / "encrypted_rds.yaml"
    path.write_text(_CHECKOV_POLICY)

    document = YamlParser().parse(path)

    embed_text = document.policy_rules[0].embed_text
    assert "Ensure RDS instances are encrypted at rest" in embed_text
    assert "GENERAL_SECURITY" in embed_text
    assert "aws_db_instance" in embed_text
    assert "aws_rds_cluster" in embed_text


def test_multi_document_yaml_produces_one_policy_rule_each(tmp_path: Path) -> None:
    second_policy = _CHECKOV_POLICY.replace("CKV2_CUSTOM_1", "CKV2_CUSTOM_2")
    path = tmp_path / "policies.yaml"
    path.write_text(_CHECKOV_POLICY + "\n---\n" + second_policy)

    document = YamlParser().parse(path)

    ids = {rule.id for rule in document.policy_rules}
    assert ids == {"CKV2_CUSTOM_1", "CKV2_CUSTOM_2"}


def test_non_scalar_metadata_fields_degrade_to_none_instead_of_failing(tmp_path: Path) -> None:
    policy = """
metadata:
  id: "CKV2_CUSTOM_9"
  name: ["ensure", "encrypted"]
  category: {a: b}
  severity: 3
scope:
  provider: ["aws", "gcp"]
definition:
  cond_type: "attribute"
  resource_types:
    - "aws_db_instance"
"""
    path = tmp_path / "messy_policy.yaml"
    path.write_text(policy)

    document = YamlParser().parse(path)

    assert len(document.policy_rules) == 1
    rule = document.policy_rules[0]
    assert rule.id == "CKV2_CUSTOM_9"
    assert rule.name is None
    assert rule.category is None
    assert rule.severity == "3"  # scalar int coerced
    assert rule.provider is None
    assert rule.resource_types == ["aws_db_instance"]


def test_policy_with_non_scalar_id_falls_back_to_generic_chunking(tmp_path: Path) -> None:
    policy = """
metadata:
  id: ["CKV2_CUSTOM_1", "CKV2_CUSTOM_2"]
  name: "bad id"
definition:
  cond_type: "attribute"
"""
    path = tmp_path / "bad_id.yaml"
    path.write_text(policy)

    document = YamlParser().parse(path)

    assert document.policy_rules == []
    assert len(document.sections) == 1
    assert len(document.chunks) == 2  # metadata + definition


def test_yaml_with_metadata_id_but_no_definition_is_not_a_policy(tmp_path: Path) -> None:
    manifest = """
apiVersion: v1
kind: ConfigMap
metadata:
  id: some-config
  name: my-config
"""
    path = tmp_path / "configmap.yaml"
    path.write_text(manifest)

    document = YamlParser().parse(path)

    assert document.policy_rules == []
    assert len(document.chunks) == 3  # apiVersion + kind + metadata


def test_generic_yaml_falls_back_to_structural_chunking_by_top_level_key(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(_GENERIC_YAML)

    document = YamlParser().parse(path)

    assert document.policy_rules == []
    assert len(document.sections) == 1
    assert document.sections[0].title == "config"
    assert len(document.chunks) == 3
    texts = [chunk.text for chunk in document.chunks]
    assert any("name: my-service" in text for text in texts)
    assert any("replicas: 3" in text for text in texts)
    assert any("team: platform" in text for text in texts)
