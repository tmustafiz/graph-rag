from graph_rag.memory.memory_writer import _MERGE_ABOUT, _MERGE_AGENT_MEMORY, MemoryWriter


class _StubEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]


class _RecordingTx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def run(self, query: str, **params: object) -> None:
        self.calls.append((query, params))


class _FakeSession:
    def __init__(self, tx: _RecordingTx) -> None:
        self._tx = tx

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_exc_info: object) -> bool:
        return False

    def execute_write(self, fn, *args):  # noqa: ANN001, ANN002, ANN003, ANN201
        return fn(self._tx, *args)


class _FakeDriver:
    def __init__(self, tx: _RecordingTx) -> None:
        self._tx = tx

    def session(self) -> _FakeSession:
        return _FakeSession(self._tx)


def _writer_with(tx: _RecordingTx) -> MemoryWriter:
    return MemoryWriter(driver=_FakeDriver(tx), embedder=_StubEmbedder())  # type: ignore[arg-type]


def test_remember_always_stores_about_qualified_name_as_a_property() -> None:
    tx = _RecordingTx()
    memory = _writer_with(tx).remember("note", "finding", about_qualified_name="pkg.mod.fn")

    assert memory.about_qualified_name == "pkg.mod.fn"
    query, params = tx.calls[0]
    assert query == _MERGE_AGENT_MEMORY
    assert params["about_qualified_name"] == "pkg.mod.fn"


def test_remember_with_about_qualified_name_also_merges_the_edge() -> None:
    tx = _RecordingTx()
    memory = _writer_with(tx).remember("note", "finding", about_qualified_name="pkg.mod.fn")

    query, params = tx.calls[1]
    assert query == _MERGE_ABOUT
    assert params == {"memory_id": memory.id, "qualified_name": "pkg.mod.fn"}


def test_remember_without_about_qualified_name_skips_the_edge_merge() -> None:
    tx = _RecordingTx()
    memory = _writer_with(tx).remember("note", "finding")

    assert memory.about_qualified_name is None
    assert len(tx.calls) == 1  # only the AgentMemory upsert — no ABOUT merge attempted
    assert tx.calls[0][1]["about_qualified_name"] is None


def test_the_property_write_does_not_depend_on_a_matching_code_entity_existing() -> None:
    # _MERGE_AGENT_MEMORY (the property write) is unconditional and has no
    # CodeEntity pattern in it — unlike _MERGE_ABOUT, it can't silently no-op
    # in a database that has no CodeEntity nodes at all (the split-deployment
    # case). This is the actual fix: previously about_qualified_name only
    # existed via _MERGE_ABOUT, which *does* require a matching CodeEntity.
    assert "CodeEntity" not in _MERGE_AGENT_MEMORY
    assert "CodeEntity" in _MERGE_ABOUT
