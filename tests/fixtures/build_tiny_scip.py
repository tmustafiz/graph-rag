"""Regenerates `tests/fixtures/tiny_java.scip` — a hand-encoded SCIP index for a
two-file toy Java project, used by `tests/test_scip_ingest.py`.

We cannot run `scip-java` in CI, so this writes the protobuf wire format
directly (same field numbers as `scip.proto`). Run from the repo root:

    uv run python tests/fixtures/build_tiny_scip.py

The toy project:

    com/acme/OrderService.java
        class  com/acme/OrderService#
        method com/acme/OrderService#submit().   (calls repo.save)
    com/acme/OrderRepository.java
        interface com/acme/OrderRepository#
        class     com/acme/JpaOrderRepository#   (implements OrderRepository)
        method    com/acme/JpaOrderRepository#save().
"""

from pathlib import Path

_JAVA = "scip-java maven com.acme 1.0"


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _tag(field_number: int, wire_type: int) -> bytes:
    return _varint((field_number << 3) | wire_type)


def _len_field(field_number: int, payload: bytes) -> bytes:
    return _tag(field_number, 2) + _varint(len(payload)) + payload


def _varint_field(field_number: int, value: int) -> bytes:
    return _tag(field_number, 0) + _varint(value)


def _string_field(field_number: int, value: str) -> bytes:
    return _len_field(field_number, value.encode("utf-8"))


def _packed_ints_field(field_number: int, values: list[int]) -> bytes:
    return _len_field(field_number, b"".join(_varint(value) for value in values))


def _relationship(symbol: str, *, implementation: bool = False, reference: bool = False) -> bytes:
    body = _string_field(1, symbol)
    if reference:
        body += _varint_field(2, 1)
    if implementation:
        body += _varint_field(3, 1)
    return _len_field(4, body)


def _symbol_information(
    symbol: str, kind: int, display_name: str, docs: list[str], relationships: list[bytes]
) -> bytes:
    body = _string_field(1, symbol)
    for doc in docs:
        body += _string_field(3, doc)
    for relationship in relationships:
        body += relationship
    body += _varint_field(5, kind)
    body += _string_field(6, display_name)
    return _len_field(3, body)


def _occurrence(
    symbol: str, roles: int, span: list[int], enclosing: list[int] | None = None
) -> bytes:
    body = _packed_ints_field(1, span) + _string_field(2, symbol) + _varint_field(3, roles)
    if enclosing:
        body += _packed_ints_field(9, enclosing)
    return _len_field(2, body)


def _document(relative_path: str, symbols: list[bytes], occurrences: list[bytes]) -> bytes:
    body = _string_field(1, relative_path)
    for occurrence in occurrences:
        body += occurrence
    for symbol in symbols:
        body += symbol
    body += _string_field(4, "java")
    return _len_field(2, body)


def build() -> bytes:
    service_class = f"{_JAVA} com/acme/OrderService#"
    service_submit = f"{_JAVA} com/acme/OrderService#submit()."
    repo_interface = f"{_JAVA} com/acme/OrderRepository#"
    jpa_repo_class = f"{_JAVA} com/acme/JpaOrderRepository#"
    jpa_repo_save = f"{_JAVA} com/acme/JpaOrderRepository#save()."

    service_doc = _document(
        "com/acme/OrderService.java",
        symbols=[
            _symbol_information(service_class, 6, "OrderService", ["An order service."], []),
            _symbol_information(
                service_submit,
                38,
                "submit",
                ["Submits an order."],
                [_relationship(repo_interface, reference=True)],
            ),
        ],
        occurrences=[
            _occurrence(service_class, 1, [0, 13, 0, 25]),
            _occurrence(service_submit, 1, [4, 16, 4, 22]),
            # inside submit(): a call to JpaOrderRepository#save (enclosing = submit range)
            _occurrence(jpa_repo_save, 0, [5, 8, 5, 12], enclosing=[4, 16, 7, 5]),
        ],
    )
    repo_doc = _document(
        "com/acme/OrderRepository.java",
        symbols=[
            _symbol_information(repo_interface, 26, "OrderRepository", [], []),
            _symbol_information(
                jpa_repo_class,
                6,
                "JpaOrderRepository",
                [],
                [_relationship(repo_interface, implementation=True)],
            ),
            _symbol_information(jpa_repo_save, 38, "save", [], []),
        ],
        occurrences=[
            _occurrence(repo_interface, 1, [0, 17, 0, 32]),
            _occurrence(jpa_repo_class, 1, [2, 13, 2, 31]),
            _occurrence(jpa_repo_save, 1, [3, 16, 3, 20]),
        ],
    )
    return service_doc + repo_doc


if __name__ == "__main__":
    out_path = Path(__file__).with_name("tiny_java.scip")
    out_path.write_bytes(build())
    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
