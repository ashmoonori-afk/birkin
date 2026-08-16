from birkin.office.adapters.docx_types import StructureRange, StructureRecord
from birkin.office.adapters.xlsx_types import SheetLocator


def test_not_required_fields_retain_runtime_typed_dict_metadata() -> None:
    assert SheetLocator.__required_keys__ == frozenset({"sheet"})
    assert SheetLocator.__optional_keys__ == frozenset({"sheet_id", "part_uri"})
    assert StructureRange.__required_keys__ == frozenset()
    assert StructureRange.__optional_keys__ == frozenset(
        {
            "start",
            "separate",
            "end",
            "zero_length",
            "cross_paragraph",
            "start_order",
            "end_order",
            "start_offset",
            "end_offset",
        }
    )
    assert StructureRecord.__optional_keys__ == frozenset(
        {"instruction", "boundaries"}
    )
