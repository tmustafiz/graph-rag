import json

import httpx
import pytest

from graph_rag.ingest.embedders import (
    CohereEmbedder,
    GeminiEmbedder,
    OllamaEmbedder,
    OpenAiEmbedder,
    VoyageEmbedder,
)
from graph_rag.ingest.embedders import rest_embedder as rest

_RealClient = httpx.Client


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    """Route every `RestEmbedder` HTTP call through `handler`, recording the requests."""
    seen: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def client_factory(**_kwargs: object) -> httpx.Client:
        return _RealClient(transport=httpx.MockTransport(recording_handler))

    monkeypatch.setattr(rest.httpx, "Client", client_factory)
    return seen


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def test_openai_builds_bearer_request_and_reorders_by_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen = _install_transport(
        monkeypatch,
        lambda _r: httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            },
        ),
    )

    vectors = OpenAiEmbedder().embed(["first", "second"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]  # sorted back into input order
    request = seen[0]
    assert str(request.url) == "https://api.openai.com/v1/embeddings"
    assert request.headers["authorization"] == "Bearer sk-test"
    assert _body(request) == {"model": "text-embedding-3-small", "input": ["first", "second"]}


def test_openai_honours_api_base_and_model_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen = _install_transport(
        monkeypatch,
        lambda _r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]}),
    )

    OpenAiEmbedder(model="nomic-embed", api_base="http://localhost:1234/").embed(["x"])

    assert str(seen[0].url) == "http://localhost:1234/v1/embeddings"
    assert _body(seen[0])["model"] == "nomic-embed"


def test_openai_missing_key_raises_before_any_http_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    seen = _install_transport(monkeypatch, lambda _r: httpx.Response(200, json={"data": []}))

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        OpenAiEmbedder().embed(["x"])
    assert seen == []


def test_voyage_sends_document_input_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "vk-test")
    seen = _install_transport(
        monkeypatch,
        lambda _r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5, 0.6]}]}),
    )

    vectors = VoyageEmbedder().embed(["doc"])

    assert vectors == [[0.5, 0.6]]
    assert str(seen[0].url) == "https://api.voyageai.com/v1/embeddings"
    assert seen[0].headers["authorization"] == "Bearer vk-test"
    assert _body(seen[0]) == {"model": "voyage-3", "input": ["doc"], "input_type": "document"}


def test_cohere_reads_nested_float_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CO_API_KEY", "co-test")
    seen = _install_transport(
        monkeypatch,
        lambda _r: httpx.Response(200, json={"embeddings": {"float": [[0.1], [0.2]]}}),
    )

    vectors = CohereEmbedder().embed(["a", "b"])

    assert vectors == [[0.1], [0.2]]
    assert str(seen[0].url) == "https://api.cohere.com/v2/embed"
    body = _body(seen[0])
    assert body["texts"] == ["a", "b"]
    assert body["input_type"] == "search_document"
    assert body["embedding_types"] == ["float"]


def test_ollama_needs_no_auth_and_hits_the_batch_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install_transport(
        monkeypatch,
        lambda _r: httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]}),
    )

    vectors = OllamaEmbedder().embed(["a", "b"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert str(seen[0].url) == "http://localhost:11434/api/embed"
    assert "authorization" not in seen[0].headers
    assert _body(seen[0]) == {"model": "nomic-embed-text", "input": ["a", "b"]}


def test_gemini_puts_key_on_the_query_string_and_wraps_each_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    seen = _install_transport(
        monkeypatch,
        lambda _r: httpx.Response(200, json={"embeddings": [{"values": [0.1]}, {"values": [0.2]}]}),
    )

    vectors = GeminiEmbedder().embed(["a", "b"])

    assert vectors == [[0.1], [0.2]]
    url = seen[0].url
    assert url.path == "/v1beta/models/text-embedding-004:batchEmbedContents"
    assert url.params["key"] == "g-test"
    assert _body(seen[0]) == {
        "requests": [
            {"model": "models/text-embedding-004", "content": {"parts": [{"text": "a"}]}},
            {"model": "models/text-embedding-004", "content": {"parts": [{"text": "b"}]}},
        ]
    }


def test_empty_input_short_circuits_without_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen = _install_transport(monkeypatch, lambda _r: httpx.Response(200, json={"data": []}))

    assert OpenAiEmbedder().embed([]) == []
    assert seen == []


def test_http_error_is_wrapped_with_provider_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    _install_transport(monkeypatch, lambda _r: httpx.Response(429, text="rate limit exceeded"))

    with pytest.raises(RuntimeError, match=r"OpenAI embeddings request failed \(HTTP 429\)"):
        OpenAiEmbedder().embed(["x"])


def test_truncated_response_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    _install_transport(
        monkeypatch,
        lambda _r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]}),
    )

    with pytest.raises(RuntimeError, match="returned 1 vectors for 2 inputs"):
        OpenAiEmbedder().embed(["a", "b"])
