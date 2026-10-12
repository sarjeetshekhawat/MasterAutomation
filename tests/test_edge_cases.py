"""Edge-case tests for validators and record matcher."""

from __future__ import annotations

import pandas as pd
import pytest

from master_update_automation.config import AuditStatus, UUID_FIELDS
from master_update_automation.record_matcher import detect_duplicate_keys, match_records
from master_update_automation.uuid_utils import (
    is_valid_uuid,
    normalise_uuid,
    split_valid_uuid,
    strip_uuid_braces,
    uuid_output_is_canonical,
    validate_uuid_field,
)
from master_update_automation.validator import (
    validate_output_dataset,
    validate_output_record,
    validate_source_data,
)


# ── UUID edge cases ──────────────────────────────────────────────────────────

VALID_UUID = "a1b2c3d4-1234-5678-9012-abcdef123456"


class TestUUIDEdgeCases:
    def test_uuid_case_insensitive(self):
        upper = "A1B2C3D4-1234-5678-9012-ABCDEF123456"
        assert is_valid_uuid(upper)
        assert normalise_uuid(upper) == f"{{{VALID_UUID}}}"

    def test_uuid_with_surrounding_spaces_and_braces(self):
        messy = "  { a1b2c3d4-1234-5678-9012-abcdef123456 }  "
        assert normalise_uuid(messy) == f"{{{VALID_UUID}}}"

    def test_triple_braces_collapsed(self):
        triple = "{{{" + VALID_UUID + "}}}"
        assert normalise_uuid(triple) == f"{{{VALID_UUID}}}"
        assert "{{" not in normalise_uuid(triple)

    def test_non_uuid_string_returned_as_is(self):
        val = "CONSUMER-001"
        assert normalise_uuid(val) == val
        assert not is_valid_uuid(val)

    def test_numeric_input_handled(self):
        # float or int passed by accident
        assert normalise_uuid(12345) == "12345"
        assert not is_valid_uuid("12345")

    def test_nan_like_handled(self):
        assert normalise_uuid("nan") == "nan"
        assert normalise_uuid("None") == "None"
        assert normalise_uuid(None) == ""

    def test_uuid_output_is_canonical_false_for_no_braces(self):
        assert not uuid_output_is_canonical(VALID_UUID)

    def test_uuid_output_is_canonical_true_for_braced(self):
        assert uuid_output_is_canonical(f"{{{VALID_UUID}}}")

    def test_strip_uuid_braces(self):
        assert strip_uuid_braces(f"{{{VALID_UUID}}}") == VALID_UUID
        assert strip_uuid_braces(VALID_UUID) == VALID_UUID
        assert strip_uuid_braces("") == ""
        assert strip_uuid_braces(None) == ""

    def test_split_valid_uuid(self):
        valid, canon = split_valid_uuid(VALID_UUID)
        assert valid
        assert canon == f"{{{VALID_UUID}}}"
        valid2, canon2 = split_valid_uuid("")
        assert valid2
        assert canon2 == ""
        valid3, canon3 = split_valid_uuid(None)
        assert valid3
        assert canon3 == ""

    def test_validate_uuid_field_returns_error_for_bad(self):
        err = validate_uuid_field("id", "not-a-uuid")
        assert err is not None
        assert "invalid" in err.lower()

    def test_validate_uuid_field_ok_for_valid(self):
        assert validate_uuid_field("id", VALID_UUID) is None
        assert validate_uuid_field("id", f"{{{VALID_UUID}}}") is None


# ── Record matcher edge cases ────────────────────────────────────────────────


class TestRecordMatcher:
    def test_detect_duplicate_keys(self):
        df = pd.DataFrame({
            "key": ["A", "B", "A", "C", "B"],
            "val": [1, 2, 3, 4, 5],
        })
        dups = detect_duplicate_keys(df, "key")
        assert "A" in dups
        assert "B" in dups
        assert "C" not in dups

    def test_detect_no_duplicates(self):
        df = pd.DataFrame({"key": ["A", "B", "C"]})
        dups = detect_duplicate_keys(df, "key")
        assert len(dups) == 0

    def test_match_against_empty_target(self):
        source = pd.DataFrame({"key": ["A", "B"]})
        results = match_records(source, None, "key")
        assert len(results) == 2
        assert all(r.action == "INSERT" for r in results)

    def test_match_with_target(self):
        source = pd.DataFrame({"key": ["A", "B", "C"]})
        target = pd.DataFrame({"key": ["B"]})
        results = match_records(source, target, "key")
        actions = {r.business_key: r.action for r in results}
        assert actions["A"] == "INSERT"
        assert actions["B"] == "UPDATE"
        assert actions["C"] == "INSERT"

    def test_missing_key_column_in_source(self):
        source = pd.DataFrame({"other": ["A"]})
        results = match_records(source, None, "key")
        assert len(results) == 1
        assert results[0].action == "FAILED"

    def test_duplicate_source_keys_flagged(self):
        source = pd.DataFrame({"key": ["A", "A"]})
        results = match_records(source, None, "key")
        dup = [r for r in results if r.action == "DUPLICATE"]
        assert len(dup) == 1

    def test_ambiguous_target_match(self):
        source = pd.DataFrame({"key": ["A"]})
        target = pd.DataFrame({"key": ["A", "A"]})
        results = match_records(source, target, "key")
        assert results[0].action == "AMBIGUOUS"


# ── Validator edge cases ─────────────────────────────────────────────────────


class TestValidator:
    def test_empty_source_data(self):
        df = pd.DataFrame()
        report = validate_source_data(df, {"consumer number"})
        assert not report.passed

    def test_missing_required_columns_warned(self):
        df = pd.DataFrame({"foo": [1]})
        report = validate_source_data(df, {"consumer number", "account number"})
        assert report.warning_count >= 2

    def test_valid_output_record(self):
        record = {
            "consumer_number": "C001",
            "account_number": "A001",
            "consumer_name": "Test",
            "meter_category": f"{{{VALID_UUID}}}",
            "cons_available_mst": "Yes",
            "cons_connect_type": f"{{{VALID_UUID}}}",
            "consumer_identy": f"{{{VALID_UUID}}}",
            "is_old_mtr_available": f"{{{VALID_UUID}}}",
            "consumer_uan_suffix": "UAN",
        }
        report = validate_output_record(record, 0, list(record.keys()))
        assert report.error_count == 0

    def test_invalid_uuid_in_output_record(self):
        record = {
            "consumer_identy": "NOT_A_UUID",
        }
        report = validate_output_record(record, 0, list(record.keys()))
        # Should have a UUID validation error
        uuid_errors = [e for e in report.errors if e.category == "uuid"]
        assert len(uuid_errors) >= 1

    def test_duplicate_business_keys_in_output(self):
        records = [
            {"consumer_number": "C001", "other": "val1"},
            {"consumer_number": "C001", "other": "val2"},
        ]
        report = validate_output_dataset(records, ["consumer_number", "other"])
        assert not report.passed
        dup_errors = [e for e in report.errors if "Duplicate" in e.message]
        assert len(dup_errors) >= 1

    def test_empty_output_dataset(self):
        report = validate_output_dataset([], ["consumer_number"])
        assert not report.passed
