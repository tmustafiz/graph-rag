from graph_rag.ingest.chunker import Chunker


def test_short_text_produces_single_chunk() -> None:
    chunks = Chunker().chunk("one two three", "sec-1", 0, 1, 1)
    assert len(chunks) == 1
    assert chunks[0].id == "sec-1::c0000"
    assert chunks[0].text == "one two three"
    assert chunks[0].token_count == 3


def test_long_text_splits_with_overlap() -> None:
    words = [f"word{i}" for i in range(1000)]
    text = " ".join(words)
    chunker = Chunker(target_words=400, overlap_ratio=0.15)
    chunks = chunker.chunk(text, "sec-1", 0, None, None)

    assert len(chunks) > 1
    assert all(c.section_id == "sec-1" for c in chunks)
    # order is contiguous starting at the given start_order
    assert [c.order for c in chunks] == list(range(len(chunks)))
    # consecutive chunks overlap: chunk0 covers words[0:400], chunk1 starts at word[340]
    # (step = target_words - overlap_words = 400 - 60), so word "word350" is in both.
    assert "word350" in chunks[0].text
    assert "word350" in chunks[1].text


def test_empty_text_produces_no_chunks() -> None:
    assert Chunker().chunk("   ", "sec-1", 0, None, None) == []


def test_start_order_offset_is_respected() -> None:
    chunks = Chunker().chunk("hello world", "sec-1", 7, None, None)
    assert chunks[0].order == 7
    assert chunks[0].id == "sec-1::c0007"


def test_content_hash_is_deterministic_and_text_specific() -> None:
    a = Chunker().chunk("same text", "sec-1", 0, None, None)[0]
    b = Chunker().chunk("same text", "sec-2", 0, None, None)[0]
    c = Chunker().chunk("different text", "sec-1", 0, None, None)[0]
    assert a.content_hash == b.content_hash
    assert a.content_hash != c.content_hash
