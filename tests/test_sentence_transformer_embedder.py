from pathlib import Path

import pytest

from graph_rag.ingest.embedders import SentenceTransformerEmbedder
from graph_rag.ingest.embedders import sentence_transformer_embedder as ste


def test_env_var_overrides_every_local_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAG_EMBEDDING_MODEL", "some-org/some-model")
    monkeypatch.setattr(ste, "_IMAGE_MODEL_DIR", Path("/does/not/matter"))
    monkeypatch.setattr(ste, "_REPO_MODEL_DIR", Path("/does/not/matter"))

    assert SentenceTransformerEmbedder._resolve_model() == "some-org/some-model"


def test_image_model_dir_wins_over_repo_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GRAG_EMBEDDING_MODEL", raising=False)
    image_dir = tmp_path / "image"
    repo_dir = tmp_path / "repo"
    image_dir.mkdir()
    repo_dir.mkdir()
    monkeypatch.setattr(ste, "_IMAGE_MODEL_DIR", image_dir)
    monkeypatch.setattr(ste, "_REPO_MODEL_DIR", repo_dir)

    assert SentenceTransformerEmbedder._resolve_model() == str(image_dir)


def test_falls_back_to_hub_id_when_no_local_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GRAG_EMBEDDING_MODEL", raising=False)
    monkeypatch.setattr(ste, "_IMAGE_MODEL_DIR", tmp_path / "absent-image")
    monkeypatch.setattr(ste, "_REPO_MODEL_DIR", tmp_path / "absent-repo")

    assert SentenceTransformerEmbedder._resolve_model() == ste.DEFAULT_MODEL_NAME
