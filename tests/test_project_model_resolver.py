from graph_rag.graph.project_model_resolver import ProjectModelResolver
from graph_rag.ingestion_pipeline import _ingest_rank


def test_first_party_target_is_always_internal() -> None:
    assert not ProjectModelResolver._is_external(
        "anything.at.all", first_party=True, internal_prefixes=[]
    )


def test_target_under_a_known_module_package_is_internal() -> None:
    prefixes = ["com.acme.platform", "com.acme.shared"]
    assert not ProjectModelResolver._is_external(
        "com.acme.platform.orders.OrderService", first_party=False, internal_prefixes=prefixes
    )
    assert not ProjectModelResolver._is_external(
        "com.acme.shared", first_party=False, internal_prefixes=prefixes
    )


def test_third_party_and_unknown_targets_are_external() -> None:
    prefixes = ["com.acme.platform"]
    assert ProjectModelResolver._is_external(
        "org.springframework.stereotype.Service", first_party=False, internal_prefixes=prefixes
    )
    # A prefix must stop on a package boundary, not mid-segment.
    assert ProjectModelResolver._is_external(
        "com.acme.platformx.Thing", first_party=False, internal_prefixes=prefixes
    )
    assert ProjectModelResolver._is_external(None, first_party=False, internal_prefixes=prefixes)


def test_ingest_rank_puts_build_files_first() -> None:
    from pathlib import Path

    assert _ingest_rank(Path("a/pom.xml")) == 0
    assert _ingest_rank(Path("a/build.gradle")) == 0
    assert _ingest_rank(Path("a/build.gradle.kts")) == 0
    assert _ingest_rank(Path("a/settings.gradle")) == 0
    assert _ingest_rank(Path("a/Service.java")) == 1
    assert _ingest_rank(Path("a/notes.md")) == 1
