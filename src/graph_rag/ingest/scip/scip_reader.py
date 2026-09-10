from .scip_document import ScipDocument
from .scip_occurrence import ScipOccurrence
from .scip_symbol import ScipSymbol

# SCIP protobuf field numbers (scip.proto, stable across 0.2 / 0.3).
# Index: metadata=1, documents=2, external_symbols=3
# Document: relative_path=1, occurrences=2, symbols=3, language=4
# SymbolInformation: symbol=1, documentation=3, relationships=4, kind=5, display_name=6
# Relationship: symbol=1, is_reference=2, is_implementation=3, is_type_definition=4
# Occurrence: range=1, symbol=2, symbol_roles=3, enclosing_range=9
_WIRE_VARINT = 0
_WIRE_LEN = 2
_WIRE_I64 = 1
_WIRE_I32 = 5


class ScipReader:
    """Minimal reader for the SCIP (Sourcegraph Code Intelligence Protocol)
    protobuf `Index` message — just the fields graph-rag consumes, decoded from
    the wire format directly so no `protobuf` runtime / generated stubs are
    needed.

    Language-agnostic: validated against `scip-java` output, the field layout
    is identical for `scip-typescript` / `scip-python`.
    """

    @classmethod
    def read(cls, data: bytes) -> list[ScipDocument]:
        documents: list[ScipDocument] = []
        for field_number, wire_type, value in cls._iter_fields(data):
            if field_number == 2 and wire_type == _WIRE_LEN:
                documents.append(cls._document(value))
        return documents

    # -- message decoders --

    @classmethod
    def _document(cls, data: bytes) -> ScipDocument:
        document = ScipDocument(relative_path="")
        for field_number, wire_type, value in cls._iter_fields(data):
            if field_number == 1 and wire_type == _WIRE_LEN:
                document.relative_path = value.decode("utf-8", "replace")
            elif field_number == 4 and wire_type == _WIRE_LEN:
                document.language = value.decode("utf-8", "replace")
            elif field_number == 2 and wire_type == _WIRE_LEN:
                document.occurrences.append(cls._occurrence(value))
            elif field_number == 3 and wire_type == _WIRE_LEN:
                document.symbols.append(cls._symbol(value))
        return document

    @classmethod
    def _symbol(cls, data: bytes) -> ScipSymbol:
        symbol = ScipSymbol(symbol="")
        for field_number, wire_type, value in cls._iter_fields(data):
            if field_number == 1 and wire_type == _WIRE_LEN:
                symbol.symbol = value.decode("utf-8", "replace")
            elif field_number == 3 and wire_type == _WIRE_LEN:
                symbol.documentation.append(value.decode("utf-8", "replace"))
            elif field_number == 4 and wire_type == _WIRE_LEN:
                symbol.relationships.append(cls._relationship(value))
            elif field_number == 5 and wire_type == _WIRE_VARINT:
                symbol.kind = value
            elif field_number == 6 and wire_type == _WIRE_LEN:
                symbol.display_name = value.decode("utf-8", "replace")
        return symbol

    @classmethod
    def _relationship(cls, data: bytes) -> tuple[str, bool, bool, bool]:
        target = ""
        is_reference = is_implementation = is_type_definition = False
        for field_number, wire_type, value in cls._iter_fields(data):
            if field_number == 1 and wire_type == _WIRE_LEN:
                target = value.decode("utf-8", "replace")
            elif field_number == 2 and wire_type == _WIRE_VARINT:
                is_reference = bool(value)
            elif field_number == 3 and wire_type == _WIRE_VARINT:
                is_implementation = bool(value)
            elif field_number == 4 and wire_type == _WIRE_VARINT:
                is_type_definition = bool(value)
        return target, is_reference, is_implementation, is_type_definition

    @classmethod
    def _occurrence(cls, data: bytes) -> ScipOccurrence:
        occurrence = ScipOccurrence(symbol="")
        for field_number, wire_type, value in cls._iter_fields(data):
            if field_number == 2 and wire_type == _WIRE_LEN:
                occurrence.symbol = value.decode("utf-8", "replace")
            elif field_number == 3 and wire_type == _WIRE_VARINT:
                occurrence.symbol_roles = value
            elif field_number == 1 and wire_type == _WIRE_LEN:
                occurrence.range = cls._packed_ints(value)
            elif field_number == 1 and wire_type == _WIRE_VARINT:
                occurrence.range.append(value)
            elif field_number == 9 and wire_type == _WIRE_LEN:
                occurrence.enclosing_range = cls._packed_ints(value)
            elif field_number == 9 and wire_type == _WIRE_VARINT:
                occurrence.enclosing_range.append(value)
        return occurrence

    # -- wire format --

    @classmethod
    def _iter_fields(cls, data: bytes):
        position = 0
        length = len(data)
        while position < length:
            tag, position = cls._read_varint(data, position)
            field_number = tag >> 3
            wire_type = tag & 0x7
            if wire_type == _WIRE_VARINT:
                value, position = cls._read_varint(data, position)
                yield field_number, wire_type, value
            elif wire_type == _WIRE_LEN:
                size, position = cls._read_varint(data, position)
                if position + size > length:
                    raise ValueError(
                        "SCIP index truncated: length-delimited field runs past end of buffer"
                    )
                yield field_number, wire_type, data[position : position + size]
                position += size
            elif wire_type == _WIRE_I64:
                yield field_number, wire_type, data[position : position + 8]
                position += 8
            elif wire_type == _WIRE_I32:
                yield field_number, wire_type, data[position : position + 4]
                position += 4
            else:  # unknown / group — stop rather than misread
                break

    @classmethod
    def _packed_ints(cls, data: bytes) -> list[int]:
        values: list[int] = []
        position = 0
        while position < len(data):
            value, position = cls._read_varint(data, position)
            values.append(value)
        return values

    @staticmethod
    def _read_varint(data: bytes, position: int) -> tuple[int, int]:
        result = 0
        shift = 0
        while position < len(data):
            byte = data[position]
            position += 1
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return result, position
            shift += 7
            if shift >= 64:
                raise ValueError("SCIP varint exceeds 64 bits (corrupt index)")
        raise ValueError("SCIP index truncated mid-varint")
