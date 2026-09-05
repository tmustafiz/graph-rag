import json

import httpx
import pytest

from graph_rag.mcp_server import query_rewriter_factory as factory
from graph_rag.mcp_server.heuristic_query_rewriter import HeuristicQueryRewriter
from graph_rag.mcp_server.llm_query_rewriter import LlmQueryRewriter, _strip_code_fence
from graph_rag.mcp_server.query_rewriter import normalize_variants
from graph_rag.mcp_server.query_rewriter_factory import build_query_rewriter, select_query_rewriter

_RealClient = httpx.Client


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    """Route every `LlmQueryRewriter` HTTP call through `handler`, recording the requests."""
    seen: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def client_factory(**_kwargs: object) -> httpx.Client:
        return _RealClient(transport=httpx.MockTransport(recording_handler))

    monkeypatch.setattr("graph_rag.mcp_server.llm_query_rewriter.httpx.Client", client_factory)
    return seen


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


# --- normalize_variants ------------------------------------------------------


def test_normalize_variants_forces_original_first_and_dedupes() -> None:
    result = normalize_variants("Auth flow", ["auth flow", "session tokens", "  "], max_queries=5)
    assert result == ["Auth flow", "session tokens"]


def test_normalize_variants_caps_at_max_but_never_below_one() -> None:
    assert normalize_variants("q", ["a", "b", "c"], max_queries=2) == ["q", "a"]
    assert normalize_variants("q", ["a", "b"], max_queries=0) == ["q"]


# --- HeuristicQueryRewriter -------------------------------------------------


def test_heuristic_expands_a_known_acronym() -> None:
    rewriter = HeuristicQueryRewriter(max_queries=5)
    variants = rewriter.rewrite("how does k8s scheduling work")
    assert variants[0] == "how does k8s scheduling work"
    assert "how does kubernetes scheduling work" in variants


def test_heuristic_synonym_override_beats_the_builtin_map() -> None:
    rewriter = HeuristicQueryRewriter(synonyms={"k8s": "container orchestrator"}, max_queries=5)
    variants = rewriter.rewrite("k8s upgrade path")
    assert "container orchestrator upgrade path" in variants
    assert "kubernetes upgrade path" not in variants


def test_heuristic_splits_a_substantial_multipart_question() -> None:
    rewriter = HeuristicQueryRewriter(max_queries=5)
    variants = rewriter.rewrite(
        "how to configure the reranker and how to tune the candidate window"
    )
    assert "how to configure the reranker" in variants
    assert "how to tune the candidate window" in variants


def test_heuristic_does_not_split_when_a_side_is_too_short() -> None:
    rewriter = HeuristicQueryRewriter(max_queries=5)
    variants = rewriter.rewrite("read and write access to the database")
    assert variants == ["read and write access to the database"]


def test_heuristic_returns_only_the_original_when_nothing_matches() -> None:
    rewriter = HeuristicQueryRewriter(max_queries=5)
    assert rewriter.rewrite("supervisor tree restart strategy") == [
        "supervisor tree restart strategy"
    ]


def test_heuristic_respects_max_queries() -> None:
    rewriter = HeuristicQueryRewriter(max_queries=2)
    variants = rewriter.rewrite("db and ci and auth pipeline wiring details here")
    assert len(variants) == 2
    assert variants[0] == "db and ci and auth pipeline wiring details here"


# --- LlmQueryRewriter ------------------------------------------------------


def test_llm_posts_chat_completions_and_parses_a_json_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _install_transport(
        monkeypatch,
        lambda _r: _chat_response('["identity and access management policy", "iam role trust"]'),
    )
    rewriter = LlmQueryRewriter(model="gpt-4o-mini", api_key="sk-test", max_queries=5)

    variants = rewriter.rewrite("iam policy")

    assert variants == [
        "iam policy",
        "identity and access management policy",
        "iam role trust",
    ]
    request = seen[0]
    assert str(request.url) == "https://api.openai.com/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert body["model"] == "gpt-4o-mini"
    assert body["messages"][-1] == {"role": "user", "content": "iam policy"}


def test_llm_honours_api_base_override(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install_transport(monkeypatch, lambda _r: _chat_response('["x"]'))
    rewriter = LlmQueryRewriter(
        model="llama3", api_key="ignored", api_base="http://localhost:11434/"
    )
    rewriter.rewrite("q")
    assert str(seen[0].url) == "http://localhost:11434/v1/chat/completions"


def test_llm_falls_back_to_the_original_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_transport(monkeypatch, lambda _r: httpx.Response(500, text="boom"))
    assert LlmQueryRewriter(model="m", api_key="k").rewrite("original query") == ["original query"]


def test_llm_falls_back_when_the_content_is_not_a_json_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_transport(monkeypatch, lambda _r: _chat_response("here are some ideas: ..."))
    assert LlmQueryRewriter(model="m", api_key="k").rewrite("q") == ["q"]


def test_llm_falls_back_when_the_array_holds_non_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_transport(monkeypatch, lambda _r: _chat_response('["ok", 42]'))
    assert LlmQueryRewriter(model="m", api_key="k").rewrite("q") == ["q"]


def test_llm_tolerates_a_json_code_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_transport(monkeypatch, lambda _r: _chat_response('```json\n["alpha", "beta"]\n```'))
    assert LlmQueryRewriter(model="m", api_key="k", max_queries=5).rewrite("q") == [
        "q",
        "alpha",
        "beta",
    ]


def test_strip_code_fence_passes_bare_json_through() -> None:
    assert _strip_code_fence('["a"]') == '["a"]'


# --- build_query_rewriter / select_query_rewriter -------------------------


def _clear_rewrite_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GRAG_QUERY_REWRITE",
        "GRAG_QUERY_REWRITE_MODEL",
        "GRAG_QUERY_REWRITE_API_KEY",
        "GRAG_QUERY_REWRITE_API_BASE",
        "GRAG_QUERY_REWRITE_SYNONYMS",
        "GRAG_QUERY_REWRITE_MAX_QUERIES",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_build_is_none_unless_the_switch_is_truthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_rewrite_env(monkeypatch)
    assert build_query_rewriter() is None
    monkeypatch.setenv("GRAG_QUERY_REWRITE", "off")
    assert build_query_rewriter() is None


def test_build_returns_heuristic_backend_when_only_the_switch_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_rewrite_env(monkeypatch)
    monkeypatch.setenv("GRAG_QUERY_REWRITE", "1")
    assert isinstance(build_query_rewriter(), HeuristicQueryRewriter)


def test_build_returns_llm_backend_when_a_model_and_key_are_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_rewrite_env(monkeypatch)
    monkeypatch.setenv("GRAG_QUERY_REWRITE", "yes")
    monkeypatch.setenv("GRAG_QUERY_REWRITE_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fallback")
    rewriter = build_query_rewriter()
    assert isinstance(rewriter, LlmQueryRewriter)


def test_build_raises_when_a_model_is_set_without_any_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_rewrite_env(monkeypatch)
    monkeypatch.setenv("GRAG_QUERY_REWRITE", "1")
    monkeypatch.setenv("GRAG_QUERY_REWRITE_MODEL", "gpt-4o-mini")
    with pytest.raises(RuntimeError, match="no API key"):
        build_query_rewriter()


def test_select_ignores_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_rewrite_env(monkeypatch)
    assert isinstance(select_query_rewriter(), HeuristicQueryRewriter)


def test_bad_max_queries_env_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_rewrite_env(monkeypatch)
    monkeypatch.setenv("GRAG_QUERY_REWRITE_MAX_QUERIES", "not-a-number")
    assert factory._read_max_queries() == factory.DEFAULT_MAX_QUERIES


def test_synonyms_file_is_loaded_and_merged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    _clear_rewrite_env(monkeypatch)
    path = tmp_path / "syn.json"  # type: ignore[operator]
    path.write_text(json.dumps({"grag": "graph rag"}))
    monkeypatch.setenv("GRAG_QUERY_REWRITE_SYNONYMS", str(path))
    rewriter = select_query_rewriter()
    assert isinstance(rewriter, HeuristicQueryRewriter)
    assert "graph rag ingest path" in rewriter.rewrite("grag ingest path")


def test_malformed_synonyms_file_is_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    _clear_rewrite_env(monkeypatch)
    path = tmp_path / "syn.json"  # type: ignore[operator]
    path.write_text('["not", "an", "object"]')
    monkeypatch.setenv("GRAG_QUERY_REWRITE_SYNONYMS", str(path))
    assert factory._load_synonyms() is None
