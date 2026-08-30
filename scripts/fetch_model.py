"""Download the vendored embedding model into models/all-MiniLM-L6-v2/.

Only the PyTorch + tokenizer files the sentence-transformers runtime needs
(~87 MB) — the ONNX/OpenVINO variants this repo doesn't use are skipped.

Usage:
    uv run python scripts/fetch_model.py
"""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ID = "sentence-transformers/all-MiniLM-L6-v2"
TARGET_DIR = Path(__file__).resolve().parents[1] / "models" / "all-MiniLM-L6-v2"
ALLOW_PATTERNS = [
    "config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "model.safetensors",
    "1_Pooling/*",
]


def main() -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=REPO_ID,
        local_dir=str(TARGET_DIR),
        allow_patterns=ALLOW_PATTERNS,
    )
    print(f"Model files written to {TARGET_DIR}")


if __name__ == "__main__":
    main()
