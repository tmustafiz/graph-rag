"""Unit tests for SpringInjectionResolver._assemble (pure — no Neo4j)."""

import json

from graph_rag.graph.spring_injection_resolver import SpringInjectionResolver


def _bean(bean_id, name, bean_type, unresolved=None):
    return {
        "id": bean_id,
        "name": name,
        "bean_type": bean_type,
        "unresolved": json.dumps(unresolved or []),
    }


def _unresolved(type_, via="constructor", qualifier="", reason="no matching bean"):
    return {"type": type_, "via": via, "qualifier": qualifier, "reason": reason}


def test_second_pass_wires_repository_injection_and_prunes_the_entry() -> None:
    service = _bean(
        "com.acme.OrderService",
        "orderService",
        "com.acme.OrderService",
        [_unresolved("OrderRepository")],
    )
    repo = _bean("com.acme.OrderRepository", "orderRepository", "com.acme.OrderRepository")

    assembled = SpringInjectionResolver._assemble([service, repo], {})

    assert assembled.injects == [
        {"from": "com.acme.OrderService", "to": "com.acme.OrderRepository", "via": "constructor"}
    ]
    assert assembled.unresolved_updates == [
        {"id": "com.acme.OrderService", "unresolved_injections": "[]"}
    ]


def test_second_pass_resolves_by_supertype_simple_name() -> None:
    consumer = _bean(
        "com.acme.Consumer", "consumer", "com.acme.Consumer", [_unresolved("Gateway", via="field")]
    )
    impl = _bean("com.acme.LegacyGateway", "legacyGateway", "com.acme.LegacyGateway")

    assembled = SpringInjectionResolver._assemble(
        [consumer, impl], {"com.acme.LegacyGateway": ["com.acme.Gateway"]}
    )

    assert assembled.injects == [
        {"from": "com.acme.Consumer", "to": "com.acme.LegacyGateway", "via": "field"}
    ]


def test_qualifier_mismatch_is_left_unresolved() -> None:
    service = _bean("com.acme.S", "s", "com.acme.S", [_unresolved("Repo", qualifier="primaryRepo")])
    repo = _bean("com.acme.Repo", "repo", "com.acme.Repo")

    assembled = SpringInjectionResolver._assemble([service, repo], {})

    assert assembled.injects == []
    assert assembled.unresolved_updates == []  # nothing changed


def test_ambiguous_target_is_left_unresolved() -> None:
    service = _bean("com.acme.S", "s", "com.acme.S", [_unresolved("Repo")])
    repo_a = _bean("com.acme.a.Repo", "repoA", "com.acme.a.Repo")
    repo_b = _bean("com.acme.b.Repo", "repoB", "com.acme.b.Repo")

    assembled = SpringInjectionResolver._assemble([service, repo_a, repo_b], {})

    assert assembled.injects == []


def test_xml_ref_keyed_entry_is_ignored() -> None:
    entry = {"ref": "somebean", "via": "xml-property", "reason": "ambiguous"}
    bean = {
        "id": "gid-a",
        "name": "a",
        "bean_type": "com.acme.A",
        "unresolved": json.dumps([entry]),
    }

    assembled = SpringInjectionResolver._assemble([bean], {})

    assert assembled.injects == []
    assert assembled.unresolved_updates == []


def test_only_resolved_entries_are_dropped_partial_update() -> None:
    service = _bean(
        "com.acme.S",
        "s",
        "com.acme.S",
        [_unresolved("Repo"), _unresolved("MissingThing", via="field")],
    )
    repo = _bean("com.acme.Repo", "repo", "com.acme.Repo")

    assembled = SpringInjectionResolver._assemble([service, repo], {})

    assert assembled.injects == [
        {"from": "com.acme.S", "to": "com.acme.Repo", "via": "constructor"}
    ]
    remaining = json.loads(assembled.unresolved_updates[0]["unresolved_injections"])
    assert [entry["type"] for entry in remaining] == ["MissingThing"]
