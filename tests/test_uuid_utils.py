from master_update_automation.uuid_utils import (
    is_valid_uuid,
    normalise_uuid,
    uuid_output_is_canonical,
    validate_uuid_field,
)

SAMPLE = "a1b2c3d4-1234-5678-9012-abcdef123456"


def test_uuid_without_braces():
    assert normalise_uuid(SAMPLE) == f"{{{SAMPLE}}}"
    assert uuid_output_is_canonical(normalise_uuid(SAMPLE))


def test_uuid_already_braced():
    assert normalise_uuid(f"{{{SAMPLE}}}") == f"{{{SAMPLE}}}"
    assert "{{" not in normalise_uuid(f"{{{SAMPLE}}}")


def test_double_braces_collapsed():
    assert normalise_uuid("{{" + SAMPLE + "}}") == f"{{{SAMPLE}}}"


def test_invalid_uuid_returned_as_is():
    raw = "not-a-uuid"
    assert normalise_uuid(raw) == raw
    assert not is_valid_uuid(raw)
    assert validate_uuid_field("id", raw)


def test_empty_uuid_preserved():
    assert normalise_uuid("") == ""
    assert normalise_uuid(None) == ""
    assert validate_uuid_field("id", "") is None


def test_whitespace_stripped():
    assert normalise_uuid(f"  {SAMPLE}  ") == f"{{{SAMPLE}}}"
