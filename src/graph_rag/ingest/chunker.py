import hashlib

from graph_rag.ingest.chunk import Chunk

TARGET_WORDS = 400
OVERLAP_RATIO = 0.15


class Chunker:
    """Splits one section's body text into overlapping, word-bounded chunks.

    Word count is used as a token-count approximation (no tokenizer
    dependency) — close enough to keep chunks in the target range.
    """

    def __init__(
        self, target_words: int = TARGET_WORDS, overlap_ratio: float = OVERLAP_RATIO
    ) -> None:
        self._target_words = target_words
        self._overlap_words = int(target_words * overlap_ratio)

    def chunk(
        self,
        text: str,
        section_id: str,
        start_order: int,
        start_page: int | None,
        end_page: int | None,
    ) -> list[Chunk]:
        words = text.split()
        if not words:
            return []

        step = self._target_words - self._overlap_words
        chunks: list[Chunk] = []
        order = start_order
        index = 0
        while True:
            window = words[index : index + self._target_words]
            chunk_text = " ".join(window)
            chunks.append(
                Chunk(
                    id=f"{section_id}::c{order:04d}",
                    section_id=section_id,
                    order=order,
                    text=chunk_text,
                    token_count=len(window),
                    content_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
                    start_page=start_page,
                    end_page=end_page,
                )
            )
            order += 1
            if index + self._target_words >= len(words):
                break
            index += step
        return chunks
