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

# Files that must exist afterwards for the model to load offline. One weights
# file is enough (the repo ships both formats).
REQUIRED_FILES = ["config.json", "tokenizer_config.json", "vocab.txt"]
REQUIRED_WEIGHTS = ["model.safetensors", "pytorch_model.bin"]


def _verify() -> None:
    missing = [name for name in REQUIRED_FILES if not (TARGET_DIR / name).is_file()]
    if not any((TARGET_DIR / name).is_file() for name in REQUIRED_WEIGHTS):
        missing.append(" or ".join(REQUIRED_WEIGHTS))
    if missing:
        raise SystemExit(
            f"Download incomplete — {TARGET_DIR} is missing: {', '.join(missing)}. "
            "Delete the directory and re-run."
        )


def main() -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=REPO_ID,
        local_dir=str(TARGET_DIR),
        allow_patterns=ALLOW_PATTERNS,
    )
    _verify()
    print(f"Reranker files written to {TARGET_DIR}")


if __name__ == "__main__":
    main()
