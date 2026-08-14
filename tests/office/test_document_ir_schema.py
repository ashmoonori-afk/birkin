import copy, json
from pathlib import Path
import pytest
from birkin.office.schema import load_document_ir_schema

def test_document_ir_schema_is_draft_2020_12_and_rejects_positional_only_locator():
    jsonschema = pytest.importorskip("jsonschema")
    schema = load_document_ir_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    fixture = json.loads((Path(__file__).parent / "fixtures/ir/minimal-docx.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(fixture)
    invalid = copy.deepcopy(fixture)
    invalid["nodes"][0]["source_locator"] = {"format":"docx", "part_uri":"/word/document.xml", "story":"body", "section_id":None, "paragraph_native_id":None, "paragraph_fingerprint":None, "run_index":1}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid)
