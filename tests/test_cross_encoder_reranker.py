from pathlib import Path

import pytest

from graph_rag.mcp_server import cross_encoder_reranker as cer
from graph_rag.mcp_server.cross_encoder_reranker import CrossEncoderReranker, build_reranker


def test_env_var_overrides_every_local_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAG_RERANK_MODEL", "some-org/some-reranker")
    monkeypatch.setattr(cer, "_IMAGE_MODEL_DIR", Path("/does/not/matter"))
    monkeypatch.setattr(cer, "_REPO_MODEL_DIR", Path("/does/not/matter"))

    assert CrossEncoderReranker._resolve_model() == "some-org/some-reranker"


def test_image_model_dir_wins_over_repo_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GRAG_RERANK_MODEL", raising=False)
    image_dir = tmp_path / "image"
    repo_dir = tmp_path / "repo"
    image_dir.mkdir()
    repo_dir.mkdir()
    monkeypatch.setattr(cer, "_IMAGE_MODEL_DIR", image_dir)
    monkeypatch.setattr(cer, "_REPO_MODEL_DIR", repo_dir)

    assert CrossEncoderReranker._resolve_model() == str(image_dir)


def test_raises_when_no_local_model_and_no_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GRAG_RERANK_MODEL", raising=False)
    monkeypatch.setattr(cer, "_IMAGE_MODEL_DIR", tmp_path / "absent-image")
    monkeypatch.setattr(cer, "_REPO_MODEL_DIR", tmp_path / "absent-repo")

    with pytest.raises(RuntimeError, match="make fetch-reranker"):
        CrossEncoderReranker._resolve_model()


def test_override_still_wins_when_it_is_a_hub_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAG_RERANK_MODEL", cer.DEFAULT_MODEL_NAME)
    assert CrossEncoderReranker._resolve_model() == cer.DEFAULT_MODEL_NAME


def test_build_reranker_is_none_unless_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GRAG_RERANK", raising=False)
    assert build_reranker() is None
    monkeypatch.setenv("GRAG_RERANK", "false")
    assert build_reranker() is None


def test_build_reranker_constructs_one_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAG_RERANK", "1")
    monkeypatch.setattr(cer, "CrossEncoderReranker", lambda: "a-reranker")
    assert build_reranker() == "a-reranker"
