"""Lightweight Streamlit smoke tests for the polished workflow UI."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from master_update_automation.config import REFERENCE_SHEET_NAME, OPERATIONS
from master_update_automation.file_loader import (
    detect_source_sheet,
    detect_target_sheet,
    get_sheet_headers,
    get_sheet_names,
    load_excel_workbook,
    read_excel_data,
    read_hierarchy_file,
)
from master_update_automation.hierarchy_mapper import HierarchyMapper
from master_update_automation.pipeline import find_source_key_column
from tests.conftest import MAIN_METER_ID, TOD_ID
from tests.test_pipeline_integration import (
    _base_source_row,
    _hierarchy_csv,
    _source_excel,
    _template_path,
    _tmpdir,
)


def _click(at: AppTest, label: str) -> AppTest:
    matches = [btn for btn in at.button if btn.label == label]
    assert matches, f"Button {label!r} not found in {[b.label for b in at.button]}"
    return matches[0].click().run()


def test_app_loads_branding_and_first_step():
    at = AppTest.from_file("app.py", default_timeout=12)
    at.run()
    assert not at.exception
    markdown = " ".join(str(item.value) for item in at.markdown)
    assert "Master Data Automation" in markdown
    assert "Consumer Master Update System" in markdown
    assert "Template" in markdown


def test_operation_buttons_cover_all_nine_operations():
    at = AppTest.from_file("app.py", default_timeout=12)
    at.session_state["step"] = 2
    at.session_state["template_path"] = "dummy.xlsx"
    at.session_state["target_sheet"] = "HTCT Consumer Master"
    at.session_state["ref_sheet_ok"] = True
    at.run()
    assert not at.exception
    labels = [btn.label for btn in at.button]
    for op in OPERATIONS.values():
        assert any(op.label in label for label in labels)


def test_selecting_operation_is_retained():
    at = AppTest.from_file("app.py", default_timeout=12)
    at.session_state["step"] = 2
    at.run()
    conversion = [btn for btn in at.button if "HTCT → LTCT" in btn.label]
    assert conversion
    conversion[0].click().run()
    assert at.session_state["operation_id"] == 9
    assert at.session_state["pipeline_result"] is None


def _preload_inputs(at: AppTest, template: Path, hierarchy: Path, source: Path) -> None:
    wb = load_excel_workbook(str(template))
    sheets = get_sheet_names(wb)
    target = detect_target_sheet(wb) or sheets[0]
    at.session_state["template_path"] = str(template)
    at.session_state["template_name"] = template.name
    at.session_state["template_size"] = template.stat().st_size
    at.session_state["template_fp"] = (template.name, template.stat().st_size)
    at.session_state["sheet_names"] = sheets
    at.session_state["ref_sheet_ok"] = REFERENCE_SHEET_NAME in wb.sheetnames
    at.session_state["target_sheet"] = target
    at.session_state["template_headers"] = get_sheet_headers(wb, target)
    wb.close()

    mapper = HierarchyMapper()
    summary = mapper.load_hierarchy(read_hierarchy_file(str(hierarchy)))
    at.session_state["hierarchy_path"] = str(hierarchy)
    at.session_state["hierarchy_name"] = hierarchy.name
    at.session_state["hierarchy_size"] = hierarchy.stat().st_size
    at.session_state["hierarchy_fp"] = (hierarchy.name, hierarchy.stat().st_size)
    at.session_state["hierarchy_summary"] = summary
    at.session_state["hierarchy_warnings"] = mapper.validate_hierarchy_columns()

    swb = load_excel_workbook(str(source))
    source_sheets = get_sheet_names(swb)
    source_sheet = detect_source_sheet(swb) or source_sheets[0]
    swb.close()
    sdf = read_excel_data(str(source), source_sheet)
    at.session_state["source_path"] = str(source)
    at.session_state["source_name"] = source.name
    at.session_state["source_size"] = source.stat().st_size
    at.session_state["source_fp"] = (source.name, source.stat().st_size)
    at.session_state["source_sheets"] = source_sheets
    at.session_state["source_sheet"] = source_sheet
    at.session_state["source_headers"] = list(sdf.columns)
    at.session_state["source_row_count"] = len(sdf)
    at.session_state["source_key_column"] = find_source_key_column(list(sdf.columns))


def test_wizard_runs_pipeline_and_clears_stale_results():
    d = _tmpdir()
    template = Path(_template_path(d))
    hierarchy = Path(_hierarchy_csv(d))
    source = Path(_source_excel(d, [_base_source_row()]))

    at = AppTest.from_file("app.py", default_timeout=45)
    at.run()
    _preload_inputs(at, template, hierarchy, source)
    at.session_state["operation_id"] = 1
    at.session_state["mapping_confirmed"] = True
    at.session_state["step"] = 6
    at.run()
    assert not at.exception
    _click(at, "Run validation")
    assert not at.exception
    result = at.session_state["pipeline_result"]
    assert result is not None
    rec = result.records[0]
    assert rec.get("meter_category", "").strip() == f"{{{MAIN_METER_ID}}}"
    assert rec.get("consumer_identy", "").strip() == f"{{{TOD_ID}}}"
    assert at.session_state["audit_bytes"]
    assert at.session_state["output_bytes"] is None

    _click(at, "Continue")
    _click(at, "Generate output workbook")
    assert not at.exception
    assert at.session_state["output_bytes"]
    assert "WC_to_HTCT" in (at.session_state["output_name"] or "")

    at.session_state["step"] = 2
    at.run()
    alt_op = [btn for btn in at.button if "WC → LTCT" in btn.label]
    assert alt_op
    alt_op[0].click().run()
    assert at.session_state["operation_id"] == 2
    assert at.session_state["pipeline_result"] is None
    assert at.session_state["output_bytes"] is None
