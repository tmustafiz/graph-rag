"""Download the vendored cross-encoder reranker into models/ms-marco-MiniLM-L-6-v2/.

Only needed if you turn reranking on (`GRAG_RERANK=1`) and want it to run
offline. See docs/operations.md.

Usage:
    uv run python scripts/fetch_reranker.py
"""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ID = "cross-encoder/ms-marco-MiniLM-L-6-v2"
TARGET_DIR = Path(__file__).resolve().parents[1] / "models" / "ms-marco-MiniLM-L-6-v2"
ALLOW_PATTERNS = [
    "config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "model.safetensors",
    "pytorch_model.bin",
]


def main() -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=REPO_ID,
        local_dir=str(TARGET_DIR),
        allow_patterns=ALLOW_PATTERNS,
    )
    print(f"Reranker files written to {TARGET_DIR}")


if __name__ == "__main__":
    main()
