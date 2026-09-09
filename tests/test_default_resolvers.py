"""#166 — the post-ingest resolver list is defined once, in
`build_default_resolvers`, so a new pass can't be added to one entry point
(ingest / eval / serve) and forgotten in another.
"""

from pathlib import Path

import graph_rag.cli as cli_module
from graph_rag.graph.default_resolvers import build_default_resolvers


def test_build_default_resolvers_returns_the_nine_passes_in_order() -> None:
    resolvers = build_default_resolvers(driver=object())  # type: ignore[arg-type]
    assert [type(resolver).__name__ for resolver in resolvers] == [
        "ProjectModelResolver",
        "SpringBeanResolver",
        "SpringXmlResolver",
        "SpringDataResolver",
        "SpringInjectionResolver",
        "AopResolver",
        "ServiceCallResolver",
        "MyBatisResolver",
        "CamelResolver",
    ]


def test_cli_has_no_inline_resolver_list() -> None:
    """Every entry point must go through the factory — no hand-maintained copy."""
    cli_src = Path(cli_module.__file__).read_text()
    assert "build_default_resolvers(driver)" in cli_src
    assert "ProjectModelResolver(" not in cli_src
