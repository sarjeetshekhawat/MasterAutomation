from datetime import datetime

from master_update_automation.config import Category, Operation
from master_update_automation.excel_writer import generate_output_filename
from master_update_automation.ui_support import (
    ENGINE_MANDATORY_SOURCE_TARGETS,
    UI_OPERATION_GROUPS,
    WORKFLOW_STEPS,
    action_counts,
    compute_step_statuses,
    file_fingerprint,
    format_file_size,
    humanize_exception,
    invalidate_processing_results,
    output_workbook_name,
    report_filename,
    results_status_label,
    upload_limit_caption,
)


class _Audit:
    def __init__(self, failed=0, review=0, warnings=0, total=1, entries=None):
        self.failed_count = failed
        self.review_count = review
        self.warning_count = warnings
        self.total_records = total
        self.entries = entries or []


class _Validation:
    def __init__(self, warnings=None):
        self.warnings = warnings or []


class _Result:
    def __init__(self, ready, audit, validation=None):
        self.ready_for_output = ready
        self.audit = audit
        self.validation = validation or _Validation()


class _Entry:
    def __init__(self, action, status):
        self.action = action
        self.status = status


def test_workflow_has_seven_steps_in_order():
    labels = [label for _, label in WORKFLOW_STEPS]
    assert labels == [
        "Template", "Operation", "Hierarchy", "Consumer Data",
        "Mappings", "Validate", "Export",
    ]


def test_all_nine_operations_are_grouped_once():
    grouped = [i for ids in UI_OPERATION_GROUPS.values() for i in ids]
    assert sorted(grouped) == list(range(1, 10))
    assert set(UI_OPERATION_GROUPS["Category Conversion"]) == {1, 2, 3, 4, 8, 9}
    assert set(UI_OPERATION_GROUPS["Same-Category Update"]) == {5, 6, 7}


def test_meter_category_is_not_a_required_source_mapping():
    assert "meter_category" not in ENGINE_MANDATORY_SOURCE_TARGETS


def test_file_fingerprint_and_size():
    assert file_fingerprint("a.xlsx", 2048) == ("a.xlsx", 2048)
    assert "KB" in format_file_size(2048)
    assert format_file_size(None) == "Unknown size"
    assert "GB" in format_file_size(3 * 1024 * 1024 * 1024)


def test_output_filename_includes_source_and_destination():
    op = Operation(Category.WC, Category.HTCT)
    when = datetime(2026, 10, 11, 8, 15, 0)
    name = output_workbook_name(op, when)
    assert name == "Consumer_Master_WC_to_HTCT_20261011_081500.xlsx"
    assert "HTCT_Consumer_Master" not in name
    audit = report_filename(op, "audit", when)
    assert audit.startswith("Consumer_Master_WC_to_HTCT_")
    assert audit.endswith("_audit.xlsx")


def test_generate_output_filename_backward_compatible():
    path = generate_output_filename(Category.LTCT, timestamp="20261011_000000")
    assert path.endswith("LTCT_Consumer_Master_Updated_20261011_000000.xlsx")


def test_results_status_labels():
    assert results_status_label(None) == "Not run"
    assert results_status_label(_Result(True, _Audit())) == "Complete"
    assert results_status_label(_Result(True, _Audit(warnings=2))) == "Complete with warnings"
    assert results_status_label(_Result(False, _Audit(failed=3, total=3))) == "Failed"
    assert results_status_label(_Result(False, _Audit(failed=1, total=3))) == "Action required"


def test_action_counts_skip_failed_rows():
    entries = [
        _Entry("INSERT", "INSERTED"),
        _Entry("UPDATE", "UPDATED"),
        _Entry("INSERT", "FAILED"),
        _Entry("UPDATE", "REQUIRES_REVIEW"),
    ]
    counts = action_counts(entries)
    assert counts == {"inserted": 1, "updated": 1}


def test_humanize_missing_reference_sheet():
    msg, detail = humanize_exception(ValueError("ref_project_masters_lov not found"), "template")
    assert "Main Meter" in msg or "ref_project_masters_lov" in msg
    assert "not found" in detail


def test_step_status_requires_validation_not_just_filename():
    state = {
        "template_path": "x.xlsx",
        "ref_sheet_ok": False,
        "target_sheet": "Sheet",
        "operation_id": 1,
        "hierarchy_path": None,
        "source_path": None,
        "mapping_confirmed": False,
        "pipeline_result": None,
        "output_bytes": None,
    }
    statuses = {item["label"]: item["status"] for item in compute_step_statuses(state, 1)}
    assert statuses["Template"] == "attention"
    assert statuses["Operation"] == "complete"


def test_upload_limit_caption_matches_configured_limit():
    assert upload_limit_caption() == "Maximum file size: 3 GB per file"


def test_source_csv_status_does_not_require_worksheet():
    state = {
        "template_path": "x.xlsx",
        "ref_sheet_ok": True,
        "target_sheet": "Sheet",
        "operation_id": 1,
        "hierarchy_path": "h.csv",
        "hierarchy_summary": {"duplicates": {}, "missing_levels": []},
        "source_path": "s.csv",
        "source_is_csv": True,
        "source_sheet": None,
        "source_key_column": "Consumer Number",
        "source_error": None,
        "mapping_confirmed": False,
        "pipeline_result": None,
        "output_bytes": None,
    }
    statuses = {item["label"]: item["status"] for item in compute_step_statuses(state, 4)}
    assert statuses["Consumer Data"] == "complete"


def test_humanize_oversize_keeps_actionable_message():
    msg, _ = humanize_exception(
        ValueError('The file "big.csv" is 4.00 GB, which exceeds the maximum allowed size of 3 GB per file.'),
        "source",
    )
    assert "3 GB" in msg
    assert "big.csv" in msg


def test_invalidate_processing_results_clears_outputs():
    state = {
        "pipeline_result": object(),
        "output_bytes": b"abc",
        "output_name": "old.xlsx",
        "audit_bytes": b"a",
        "error_bytes": b"e",
        "audit_name": "a.xlsx",
        "error_name": "e.xlsx",
        "operation_id": 1,
    }
    invalidate_processing_results(state)
    assert state["pipeline_result"] is None
    assert state["output_bytes"] is None
    assert state["operation_id"] == 1
