"""Guided Streamlit workflow for master Excel update automation."""

from __future__ import annotations

import html
import io
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from .column_mapper import create_column_mapping
from .config import (
    HIERARCHY_EXTENSIONS,
    OPERATIONS,
    REFERENCE_SHEET_NAME,
    SOURCE_EXTENSIONS,
    TEMPLATE_EXTENSIONS,
)
from .excel_writer import write_output_workbook
from .file_loader import (
    detect_source_sheet,
    detect_target_sheet,
    get_sheet_headers,
    get_sheet_names,
    inspect_csv_file,
    inspect_excel_sheet,
    load_excel_workbook,
    read_hierarchy_file,
    remove_temp_file,
    save_upload_stream,
    validate_extension,
)
from .hierarchy_mapper import HierarchyMapper
from .pipeline import find_source_key_column, run_pipeline
from .schema_detector import detect_template_schema
from .ui_support import (
    ENGINE_MANDATORY_SOURCE_TARGETS,
    ENGINE_POPULATED_TARGETS,
    MAX_TABLE_PREVIEW_ROWS,
    PROCESSING_STAGES,
    UI_OPERATION_GROUPS,
    WORKFLOW_STEPS,
    action_counts,
    compute_step_statuses,
    file_fingerprint,
    format_file_size,
    humanize_exception,
    humanize_validation_issue,
    invalidate_processing_results,
    operation_explanation,
    output_workbook_name,
    report_filename,
    results_status_label,
    stepper_html,
    upload_limit_caption,
)


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap');
        html, body, [class*="st-"], .stApp {
            font-family: 'IBM Plex Sans', sans-serif;
            color: #1B2428;
        }
        .stApp {
            background:
                linear-gradient(180deg, rgba(15,92,86,0.05) 0%, transparent 220px),
                repeating-linear-gradient(0deg, transparent, transparent 31px, rgba(27,36,40,0.035) 32px),
                #F3EFE6;
        }
        .block-container { padding-top: 1.15rem; max-width: 1180px; overflow-x: hidden; }
        h1, h2, h3 { font-family: 'Source Serif 4', 'IBM Plex Sans', serif !important; color: #132026; letter-spacing: -0.02em; }
        #MainMenu, footer, header { visibility: hidden; }
        .mda-hero {
            display: grid; grid-template-columns: auto 1fr; gap: 1rem 1.15rem;
            align-items: start; padding: 1.05rem 1.2rem 1.15rem;
            background: #FFFcf7; border: 1px solid #D8D0C2; border-radius: 10px;
            box-shadow: 0 1px 0 rgba(255,255,255,0.8) inset, 0 8px 24px rgba(27,36,40,0.05);
            margin-bottom: 0.9rem;
        }
        .mda-mark {
            width: 44px; height: 44px; border-radius: 8px;
            background: #0F5C56; color: #F4EFE4;
            display: flex; align-items: center; justify-content: center;
            font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 0.82rem;
            letter-spacing: 0.04em;
        }
        .mda-kicker {
            font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem;
            letter-spacing: 0.16em; text-transform: uppercase; color: #0F5C56; margin: 0 0 0.2rem;
        }
        .mda-hero h1 { margin: 0; font-size: 1.72rem; line-height: 1.15; }
        .mda-hero p { margin: 0.35rem 0 0; color: #4B585E; font-size: 0.95rem; max-width: 58rem; }
        .mda-stepper {
            list-style: none; display: flex; flex-wrap: wrap; gap: 0.4rem; padding: 0; margin: 0 0 1rem;
        }
        .mda-step {
            display: flex; align-items: center; gap: 0.4rem;
            border: 1px solid #D8D0C2; background: #FFFcf7; color: #5C6770;
            border-radius: 999px; padding: 0.28rem 0.7rem 0.28rem 0.45rem; font-size: 0.78rem;
        }
        .mda-step-index { font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; color: #7A868C; }
        .mda-step-current { border-color: #0F5C56; color: #0F5C56; background: #E7F3F1; font-weight: 600; }
        .mda-step-complete { border-color: #1B7A4A; color: #145C38; background: #E8F6EE; }
        .mda-step-attention { border-color: #A65B12; color: #8A4308; background: #FBF0E4; }
        .mda-step-state { font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.06em; color: inherit; }
        .mda-panel {
            background: #FFFcf7; border: 1px solid #D8D0C2; border-radius: 10px;
            padding: 1.05rem 1.15rem 1.2rem; margin-bottom: 0.85rem;
        }
        .mda-stepchip {
            font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem;
            letter-spacing: 0.12em; text-transform: uppercase; color: #0F5C56; margin: 0 0 0.35rem;
        }
        .mda-lede { color: #4B585E; margin: 0 0 0.85rem; }
        .mda-file {
            border: 1px dashed #C9C0B0; border-radius: 8px; padding: 0.75rem 0.9rem; background: #F8F4EB;
        }
        .mda-file strong { display: block; font-size: 0.95rem; word-break: break-word; overflow-wrap: anywhere; }
        .mda-meta { color: #5C6770; font-size: 0.82rem; margin-top: 0.2rem; }
        .mda-status { display: inline-block; margin-top: 0.45rem; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }
        .mda-ok { color: #145C38; }
        .mda-warn { color: #8A4308; }
        .mda-fail { color: #9B1C1C; }
        .mda-idle { color: #5C6770; }
        .mda-op-selected {
            border: 1px solid #0F5C56 !important; background: #E7F3F1 !important; color: #0F5C56 !important;
        }
        .mda-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.55rem; margin: 0.7rem 0 1rem; }
        .mda-metric { border: 1px solid #D8D0C2; border-radius: 8px; padding: 0.7rem 0.8rem; background: #FFFcf7; }
        .mda-metric span { display: block; font-size: 0.72rem; color: #5C6770; text-transform: uppercase; letter-spacing: 0.06em; }
        .mda-metric strong { font-family: 'IBM Plex Mono', monospace; font-size: 1.15rem; }
        .stButton>button { border-radius: 8px; font-weight: 600; white-space: normal; }
        div[data-testid="stFileUploader"] { max-width: 100%; }
        div[data-testid="stFileUploader"] section { background: #FFFcf7; border: 1px dashed #C9C0B0; }
        div[data-testid="stDataFrame"], div[data-testid="stDataFrame"] > div { max-width: 100%; overflow-x: auto; }
        div[data-testid="stMetric"] { min-width: 0; }
        div[data-testid="stMetricValue"] { overflow-wrap: anywhere; }
        .stDownloadButton button { white-space: normal; height: auto; min-height: 2.5rem; }
        @media (max-width: 800px) {
            .mda-hero { grid-template-columns: 1fr; }
            .mda-hero h1 { font-size: 1.35rem; }
            .mda-step { font-size: 0.72rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _save_upload(uploaded, suffix: str, previous_path: str | None = None) -> str:
    path = save_upload_stream(uploaded, suffix, uploaded.name, getattr(uploaded, "size", None))
    if previous_path and previous_path != path:
        remove_temp_file(previous_path)
    return path


def _upload_caption(accepted: str) -> None:
    st.caption(f"{upload_limit_caption()}. Accepted formats: {accepted}.")


def _init_state() -> None:
    defaults = {
        "step": 1,
        "template_path": None,
        "template_name": None,
        "template_size": None,
        "template_fp": None,
        "template_error": None,
        "template_error_detail": None,
        "target_sheet": None,
        "template_headers": [],
        "sheet_names": [],
        "ref_sheet_ok": False,
        "ref_category_count": 0,
        "operation_id": None,
        "hierarchy_path": None,
        "hierarchy_name": None,
        "hierarchy_size": None,
        "hierarchy_fp": None,
        "hierarchy_summary": None,
        "hierarchy_error": None,
        "hierarchy_error_detail": None,
        "hierarchy_warnings": [],
        "source_path": None,
        "source_name": None,
        "source_size": None,
        "source_fp": None,
        "source_sheet": None,
        "source_headers": [],
        "source_row_count": None,
        "source_key_column": None,
        "source_error": None,
        "source_error_detail": None,
        "source_sheets": [],
        "source_is_csv": False,
        "source_preview": None,
        "source_parsed_key": None,
        "source_dup_warning": None,
        "mapped_column_count": 0,
        "unmapped_source_count": 0,
        "template_parsed_key": None,
        "custom_map": {},
        "mapping_blockers": [],
        "pipeline_result": None,
        "output_bytes": None,
        "output_name": None,
        "audit_bytes": None,
        "audit_name": None,
        "error_bytes": None,
        "error_name": None,
        "mapping_confirmed": False,
        "processing": False,
        "run_stamp": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _clear_results() -> None:
    invalidate_processing_results(st.session_state)
    st.session_state.run_stamp = None


def _issue_expander(title: str, detail: str) -> None:
    with st.expander(title):
        st.code(detail)


def _nav(back: int | None, nxt: int | None, next_disabled: bool = False) -> None:
    cols = st.columns([1, 1, 6])
    busy = bool(st.session_state.processing)
    if back:
        if cols[0].button("Back", use_container_width=True, disabled=busy):
            st.session_state.step = back
            st.rerun()
    if nxt:
        if cols[1].button("Continue", use_container_width=True, disabled=next_disabled or busy, type="primary"):
            st.session_state.step = nxt
            st.rerun()


def _step_heading(index: int, title: str, lede: str) -> None:
    st.markdown(
        f'<div class="mda-stepchip">Step {index:02d} / 07 — {WORKFLOW_STEPS[index - 1][1]}</div>',
        unsafe_allow_html=True,
    )
    st.subheader(title)
    st.markdown(f'<p class="mda-lede">{lede}</p>', unsafe_allow_html=True)


def _file_card(name: str, size, kind: str, status: str, status_class: str, extra: str = "") -> None:
    extra_html = html.escape(extra) if extra else ""
    st.markdown(
        f"""
        <div class="mda-file">
          <strong>{html.escape(str(name or ""))}</strong>
          <div class="mda-meta">{html.escape(kind)} · {html.escape(format_file_size(size))}{f' · {extra_html}' if extra_html else ''}</div>
          <span class="mda-status {html.escape(status_class)}">{html.escape(status)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _preview_frame(df: pd.DataFrame, caption: str) -> None:
    if df is None or df.empty:
        st.caption("No rows to display.")
        return
    shown = df.head(MAX_TABLE_PREVIEW_ROWS)
    st.caption(f"{caption} Showing {len(shown)} of {len(df)} rows.")
    st.dataframe(shown, use_container_width=True, hide_index=True)


def step_template() -> None:
    _step_heading(
        1,
        "Upload the target template",
        "Upload the Excel workbook that defines the required output structure and reference values.",
    )
    uploaded = st.file_uploader("Target template (.xlsx or .xls)", type=["xlsx", "xls"], key="tpl")
    _upload_caption(".xlsx, .xls")
    if uploaded:
        fp = file_fingerprint(uploaded.name, uploaded.size)
        if st.session_state.template_fp != fp:
            try:
                validate_extension(uploaded.name, TEMPLATE_EXTENSIONS, "target template")
                path = _save_upload(uploaded, Path(uploaded.name).suffix, st.session_state.template_path)
                wb = load_excel_workbook(path)
                st.session_state.template_path = path
                st.session_state.template_name = uploaded.name
                st.session_state.template_size = uploaded.size
                st.session_state.template_fp = fp
                st.session_state.sheet_names = get_sheet_names(wb)
                st.session_state.ref_sheet_ok = REFERENCE_SHEET_NAME in wb.sheetnames
                detected = detect_target_sheet(wb)
                st.session_state.target_sheet = detected
                st.session_state.template_error = None
                st.session_state.template_error_detail = None
                st.session_state.mapping_confirmed = False
                st.session_state.custom_map = {}
                st.session_state.template_parsed_key = None
                _clear_results()
                wb.close()
            except Exception as exc:
                user_msg, detail = humanize_exception(exc, "template")
                remove_temp_file(st.session_state.get("template_path"))
                st.session_state.template_path = None
                st.session_state.template_fp = fp
                st.session_state.ref_sheet_ok = False
                st.session_state.template_error = user_msg
                st.session_state.template_error_detail = detail
                _clear_results()

    if st.session_state.template_error:
        st.error(st.session_state.template_error)
        _issue_expander("Technical details", st.session_state.template_error_detail or "")
        _nav(None, 2, next_disabled=True)
        return

    if not st.session_state.template_path:
        st.markdown('<p class="mda-status mda-idle">Waiting for upload</p>', unsafe_allow_html=True)
        _nav(None, 2, next_disabled=True)
        return

    options = [s for s in st.session_state.sheet_names if s != REFERENCE_SHEET_NAME]
    if not options:
        st.error("The template has no consumer-master worksheet besides the reference sheet. Upload a complete template.")
        _nav(None, 2, next_disabled=True)
        return

    current = st.session_state.target_sheet if st.session_state.target_sheet in options else options[0]
    selected = st.selectbox("Target worksheet", options, index=options.index(current))
    if selected != st.session_state.target_sheet:
        st.session_state.target_sheet = selected
        st.session_state.mapping_confirmed = False
        _clear_results()

    parsed_key = (st.session_state.template_fp, selected)
    try:
        if st.session_state.template_parsed_key != parsed_key:
            wb = load_excel_workbook(st.session_state.template_path)
            st.session_state.template_headers = get_sheet_headers(wb, selected)
            schema = detect_template_schema(wb, selected)
            st.session_state.ref_category_count = len(schema.reference_categories)
            st.session_state.ref_sheet_ok = REFERENCE_SHEET_NAME in wb.sheetnames
            st.session_state.template_parsed_key = parsed_key
            wb.close()
    except Exception as exc:
        user_msg, detail = humanize_exception(exc, "template")
        st.error(user_msg)
        _issue_expander("Technical details", detail)
        _nav(None, 2, next_disabled=True)
        return

    if st.session_state.ref_sheet_ok:
        _file_card(
            st.session_state.template_name,
            st.session_state.template_size,
            "Excel workbook",
            "File validated",
            "mda-ok",
            f"Target sheet: {selected}",
        )
        st.info(
            f"Required reference worksheet `{REFERENCE_SHEET_NAME}` identified. "
            f"{len(st.session_state.template_headers)} target columns detected."
        )
    else:
        _file_card(
            st.session_state.template_name,
            st.session_state.template_size,
            "Excel workbook",
            "File rejected",
            "mda-fail",
        )
        st.error(
            f"The uploaded template is missing `{REFERENCE_SHEET_NAME}`. "
            "This worksheet supplies reference UUIDs, including Main Meter. "
            "Upload a template that includes that sheet."
        )

    c1, c2, c3 = st.columns(3)
    c1.metric("Worksheets", len(st.session_state.sheet_names))
    c2.metric("Target columns", len(st.session_state.template_headers))
    c3.metric("Reference sheet", "Found" if st.session_state.ref_sheet_ok else "Missing")
    st.caption("Sheets: " + ", ".join(st.session_state.sheet_names))
    with st.expander("Target column order"):
        _preview_frame(
            pd.DataFrame({"column": st.session_state.template_headers}),
            "Template headers.",
        )
    _nav(None, 2, next_disabled=not (st.session_state.template_path and st.session_state.target_sheet and st.session_state.ref_sheet_ok))


def step_operation() -> None:
    _step_heading(
        2,
        "Select the processing operation",
        "Choose the source and destination meter categories for this entire run.",
    )
    current = st.session_state.operation_id
    left, right = st.columns(2)
    sections = list(UI_OPERATION_GROUPS.items())
    for col, (group_name, ids) in zip((left, right), sections):
        with col:
            st.markdown(f"**{group_name}**")
            for op_id in ids:
                op = OPERATIONS[op_id]
                selected = current == op_id
                label = f"{'●' if selected else '○'}  {op.label}"
                if st.button(label, key=f"op_{op_id}", use_container_width=True):
                    if st.session_state.operation_id != op_id:
                        _clear_results()
                    st.session_state.operation_id = op_id
                    st.rerun()

    op = OPERATIONS.get(st.session_state.operation_id)
    if op:
        st.success(f"Selected operation: {op.label}")
        st.caption(f"Source {op.source.value} → destination {op.destination.value}. {operation_explanation(op)}")
    else:
        st.markdown('<p class="mda-status mda-idle">No operation selected</p>', unsafe_allow_html=True)
    _nav(1, 3, next_disabled=st.session_state.operation_id is None)


def step_hierarchy() -> None:
    _step_heading(
        3,
        "Upload the network hierarchy report",
        "Upload the report used to resolve DISCOM through DT identifiers.",
    )
    uploaded = st.file_uploader("Hierarchy report (CSV or Excel)", type=["csv", "xlsx", "xls"], key="hier")
    _upload_caption(".csv, .xlsx, .xls — UTF-8 CSV recommended")
    if uploaded:
        fp = file_fingerprint(uploaded.name, uploaded.size)
        if st.session_state.hierarchy_fp != fp:
            try:
                validate_extension(uploaded.name, HIERARCHY_EXTENSIONS, "hierarchy report")
                path = _save_upload(uploaded, Path(uploaded.name).suffix, st.session_state.hierarchy_path)
                df = read_hierarchy_file(path)
                mapper = HierarchyMapper()
                summary = mapper.load_hierarchy(df)
                st.session_state.hierarchy_path = path
                st.session_state.hierarchy_name = uploaded.name
                st.session_state.hierarchy_size = uploaded.size
                st.session_state.hierarchy_fp = fp
                st.session_state.hierarchy_summary = summary
                st.session_state.hierarchy_warnings = mapper.validate_hierarchy_columns()
                st.session_state.hierarchy_error = None
                st.session_state.hierarchy_error_detail = None
                _clear_results()
            except Exception as exc:
                user_msg, detail = humanize_exception(exc, "hierarchy")
                remove_temp_file(st.session_state.get("hierarchy_path"))
                st.session_state.hierarchy_path = None
                st.session_state.hierarchy_summary = None
                st.session_state.hierarchy_fp = fp
                st.session_state.hierarchy_error = user_msg
                st.session_state.hierarchy_error_detail = detail
                _clear_results()

    if st.session_state.hierarchy_error:
        st.error(st.session_state.hierarchy_error)
        _issue_expander("Technical details", st.session_state.hierarchy_error_detail or "")
        _nav(2, 4, next_disabled=True)
        return

    if not st.session_state.hierarchy_path:
        st.markdown('<p class="mda-status mda-idle">Waiting for upload</p>', unsafe_allow_html=True)
        _nav(2, 4, next_disabled=True)
        return

    summary = st.session_state.hierarchy_summary or {}
    needs_review = bool(summary.get("duplicates") or summary.get("missing_levels"))
    status = "File requires review" if needs_review else "File validated"
    klass = "mda-warn" if needs_review else "mda-ok"
    _file_card(
        st.session_state.hierarchy_name,
        st.session_state.hierarchy_size,
        "Hierarchy CSV" if Path(st.session_state.hierarchy_name or "").suffix.lower() == ".csv" else "Hierarchy Excel",
        status,
        klass,
        f"{summary.get('total_rows', 0)} rows",
    )
    if not needs_review:
        st.info("Hierarchy columns detected. Duplicate codes will be flagged during processing, not guessed.")
    st.caption("Detected levels: " + (", ".join(summary.get("available_levels") or []) or "(none)"))
    if summary.get("missing_levels"):
        st.warning(
            "The hierarchy report is missing one or more network levels: "
            + ", ".join(summary["missing_levels"])
            + ". Records that depend on those identifiers may fail validation."
        )
    if summary.get("duplicates"):
        st.error(
            "Duplicate hierarchy keys were found. Ambiguous codes will be marked for review "
            "and will not be auto-selected."
        )
        st.json(summary["duplicates"])
    with st.expander("Detected hierarchy columns"):
        st.json(summary.get("detected_columns") or {})
    for msg in st.session_state.get("hierarchy_warnings") or []:
        st.warning(msg)
    _nav(2, 4, next_disabled=not st.session_state.hierarchy_path)


def _apply_source_inspection(inspection, selected_sheet: str | None) -> None:
    headers = list(inspection.headers)
    st.session_state.source_headers = headers
    st.session_state.source_row_count = inspection.row_count
    st.session_state.source_preview = inspection.preview
    key_col = find_source_key_column(headers)
    st.session_state.source_key_column = key_col
    mapping = create_column_mapping(headers, st.session_state.template_headers)
    st.session_state.mapped_column_count = len(mapping.mappings)
    st.session_state.unmapped_source_count = len(mapping.unmapped_source)
    st.session_state.source_parsed_key = (st.session_state.source_fp, selected_sheet)
    st.session_state.source_dup_warning = inspection.duplicate_key_count


def step_source() -> None:
    _step_heading(
        4,
        "Upload consumer source data",
        "Upload the Excel workbook or CSV file containing the consumer records to be transformed.",
    )
    uploaded = st.file_uploader(
        "Consumer source data (CSV or Excel)",
        type=["csv", "xlsx", "xls"],
        key="src",
    )
    _upload_caption(".csv, .xlsx, .xls — UTF-8 CSV recommended")
    if uploaded:
        fp = file_fingerprint(uploaded.name, uploaded.size)
        if st.session_state.source_fp != fp:
            try:
                validate_extension(uploaded.name, SOURCE_EXTENSIONS, "consumer source data")
                path = _save_upload(uploaded, Path(uploaded.name).suffix, st.session_state.source_path)
                is_csv = Path(uploaded.name).suffix.lower() == ".csv"
                st.session_state.source_path = path
                st.session_state.source_name = uploaded.name
                st.session_state.source_size = uploaded.size
                st.session_state.source_fp = fp
                st.session_state.source_is_csv = is_csv
                st.session_state.source_error = None
                st.session_state.source_error_detail = None
                st.session_state.mapping_confirmed = False
                st.session_state.custom_map = {}
                st.session_state.source_parsed_key = None
                if is_csv:
                    st.session_state.source_sheets = []
                    st.session_state.source_sheet = None
                else:
                    wb = load_excel_workbook(path)
                    sheets = get_sheet_names(wb)
                    detected = detect_source_sheet(wb)
                    wb.close()
                    st.session_state.source_sheets = sheets
                    st.session_state.source_sheet = detected if detected in sheets else (sheets[0] if sheets else None)
                _clear_results()
            except Exception as exc:
                user_msg, detail = humanize_exception(exc, "source")
                remove_temp_file(st.session_state.get("source_path"))
                st.session_state.source_path = None
                st.session_state.source_fp = fp
                st.session_state.source_is_csv = False
                st.session_state.source_error = user_msg
                st.session_state.source_error_detail = detail
                _clear_results()

    if st.session_state.source_error:
        st.error(st.session_state.source_error)
        _issue_expander("Technical details", st.session_state.source_error_detail or "")
        _nav(3, 5, next_disabled=True)
        return

    if not st.session_state.source_path:
        st.markdown('<p class="mda-status mda-idle">Waiting for upload</p>', unsafe_allow_html=True)
        _nav(3, 5, next_disabled=True)
        return

    selected = None
    if st.session_state.source_is_csv:
        st.info("CSV files contain a single table, so worksheet selection is not required.")
    else:
        sheets = st.session_state.get("source_sheets") or []
        if not sheets:
            st.error("No worksheets were found in the consumer source workbook.")
            _nav(3, 5, next_disabled=True)
            return
        current = st.session_state.source_sheet if st.session_state.source_sheet in sheets else sheets[0]
        selected = st.selectbox("Source worksheet", sheets, index=sheets.index(current))
        if selected != st.session_state.source_sheet:
            st.session_state.source_sheet = selected
            st.session_state.mapping_confirmed = False
            st.session_state.source_parsed_key = None
            _clear_results()
        selected = st.session_state.source_sheet

    parsed_key = (st.session_state.source_fp, selected)
    try:
        if st.session_state.source_parsed_key != parsed_key:
            if st.session_state.source_is_csv:
                inspection = inspect_csv_file(st.session_state.source_path)
            else:
                inspection = inspect_excel_sheet(st.session_state.source_path, selected)
            _apply_source_inspection(inspection, selected)
    except Exception as exc:
        user_msg, detail = humanize_exception(exc, "source")
        st.error(user_msg)
        _issue_expander("Technical details", detail)
        _nav(3, 5, next_disabled=True)
        return

    key_col = st.session_state.source_key_column
    kind = "CSV file" if st.session_state.source_is_csv else "Excel workbook"
    extra = f"{st.session_state.source_row_count} records"
    if selected:
        extra += f" · sheet {selected}"
    if key_col:
        _file_card(
            st.session_state.source_name,
            st.session_state.source_size,
            kind,
            "File validated",
            "mda-ok",
            extra,
        )
        st.info(f"Required consumer columns detected. Business key: `{key_col}`.")
    else:
        _file_card(
            st.session_state.source_name,
            st.session_state.source_size,
            kind,
            "File requires review",
            "mda-warn",
            extra,
        )
        st.error(
            "No consumer number or account number column was detected in the source file. "
            "Add one of those columns, then upload the file again."
        )

    c1, c2, c3 = st.columns(3)
    c1.metric("Source records", st.session_state.source_row_count or 0)
    c2.metric("Mapped columns", st.session_state.mapped_column_count or 0)
    c3.metric("Unmatched source columns", st.session_state.unmapped_source_count or 0)
    if st.session_state.unmapped_source_count:
        st.caption("Unmatched source columns are ignored unless required to derive a target value.")
    preview = st.session_state.source_preview
    if preview is not None and not getattr(preview, "empty", True):
        _preview_frame(preview, "Source preview.")
    if st.session_state.source_dup_warning:
        st.warning(
            f"{st.session_state.source_dup_warning} duplicate identifier(s) in `{key_col}`. "
            "Duplicate keys will be flagged during validation."
        )
    source_ready = bool(st.session_state.source_path) and (
        st.session_state.source_is_csv or bool(st.session_state.source_sheet)
    )
    _nav(3, 5, next_disabled=not source_ready)


def step_mappings() -> None:
    _step_heading(
        5,
        "Review source-to-target mappings",
        "Confirm how source columns map to the template. Hierarchy, reference, and business-rule fields are filled by the engine.",
    )
    if not (st.session_state.source_path and st.session_state.template_headers):
        st.warning("Complete the previous steps first.")
        _nav(4, None)
        return
    source_headers = st.session_state.source_headers or []
    if not source_headers:
        st.warning("Source columns could not be detected. Return to Consumer Data and re-upload the file.")
        _nav(4, None)
        return
    mapping = create_column_mapping(
        source_headers,
        st.session_state.template_headers,
        custom_map=st.session_state.custom_map or None,
    )
    rows = []
    from .config import REFERENCE_CATEGORY_MAP
    for m in mapping.mappings:
        tgt = m.target_column
        lookup = REFERENCE_CATEGORY_MAP.get(tgt.lower().strip(), "")
        if tgt.lower().strip() == "meter_make":
            op = OPERATIONS[st.session_state.operation_id]
            lookup = f"{op.destination.value} METER MAKE"
        if tgt.lower().strip() == "meter_category":
            lookup = "METER CATEGORY (always Main Meter)"
        rows.append({
            "Source column": m.source_column,
            "Target column": tgt,
            "Transformation": m.transformation,
            "Lookup category": lookup,
            "Confidence": m.confidence,
            "Status": "OK" if m.is_confirmed else "Needs confirmation",
        })
    _preview_frame(pd.DataFrame(rows), "Column mappings.")
    st.markdown("**Unmapped source columns**")
    st.write(mapping.unmapped_source or "(none)")
    st.markdown("**Target columns without a direct source mapping**")
    st.write(mapping.unmapped_target or "(none)")
    st.caption(
        "meter_category is always resolved to Main Meter from the template reference sheet. "
        "It is not copied from the source workbook."
    )

    with st.expander("Override a source → target mapping"):
        src = st.selectbox("Source column", source_headers)
        tgt = st.selectbox("Target column", ["(none)"] + st.session_state.template_headers)
        if st.button("Apply override"):
            cmap = dict(st.session_state.custom_map)
            if tgt == "(none)":
                cmap.pop(src, None)
            else:
                cmap[src] = tgt
            st.session_state.custom_map = cmap
            st.session_state.mapping_confirmed = False
            _clear_results()
            st.rerun()

    mandatory_unmapped = [
        t for t in mapping.unmapped_target
        if t.lower().strip() in ENGINE_MANDATORY_SOURCE_TARGETS
        and t.lower().strip() not in ENGINE_POPULATED_TARGETS
    ]
    st.session_state.mapping_blockers = mandatory_unmapped
    if mandatory_unmapped:
        st.error(
            "Mandatory target fields still lack a source mapping: "
            + ", ".join(mandatory_unmapped)
            + ". Map them before continuing."
        )
        st.session_state.mapping_confirmed = False
    else:
        st.session_state.mapping_confirmed = st.checkbox(
            "I confirm the mapping is correct for this run",
            value=st.session_state.mapping_confirmed,
        )
    _nav(4, 6, next_disabled=not st.session_state.mapping_confirmed)


def _run_summary() -> None:
    op = OPERATIONS.get(st.session_state.operation_id)
    rows = [
        ("Selected operation", op.label if op else "Not selected"),
        ("Template", st.session_state.template_name or "Not uploaded"),
        ("Target worksheet", st.session_state.target_sheet or "Not selected"),
        ("Hierarchy report", st.session_state.hierarchy_name or "Not uploaded"),
        ("Consumer source", st.session_state.source_name or "Not uploaded"),
        (
            "Source worksheet",
            "CSV (single table)" if st.session_state.source_is_csv else (st.session_state.source_sheet or "Not selected"),
        ),
    ]
    if st.session_state.source_row_count is not None:
        rows.append(("Detected source records", str(st.session_state.source_row_count)))
    mapping_state = "Confirmed" if st.session_state.mapping_confirmed else "Not confirmed"
    rows.append(("Mapping status", mapping_state))
    st.dataframe(pd.DataFrame(rows, columns=["Item", "Value"]), use_container_width=True, hide_index=True)


def step_dry_run() -> None:
    _step_heading(
        6,
        "Validate the transformation",
        "Review the run summary, then process records without writing the final master workbook until you continue to Export.",
    )
    op = OPERATIONS[st.session_state.operation_id]
    st.markdown("**Run summary**")
    _run_summary()

    busy = bool(st.session_state.processing)
    if st.button("Run validation", type="primary", disabled=busy):
        st.session_state.processing = True
        try:
            with st.status("Processing records…", expanded=True) as status:
                def _progress(message: str) -> None:
                    status.write(message)

                result = run_pipeline(
                    template_path=st.session_state.template_path,
                    target_sheet=st.session_state.target_sheet,
                    operation=op,
                    hierarchy_path=st.session_state.hierarchy_path,
                    source_path=st.session_state.source_path,
                    source_sheet=None if st.session_state.source_is_csv else st.session_state.source_sheet,
                    custom_map=st.session_state.custom_map or None,
                    progress=_progress,
                )
                _progress(PROCESSING_STAGES[-1])
                stamp = datetime.now()
                st.session_state.run_stamp = stamp
                st.session_state.pipeline_result = result
                audit_df = result.audit.to_dataframe()
                buf = io.BytesIO()
                audit_df.to_excel(buf, index=False)
                st.session_state.audit_bytes = buf.getvalue()
                st.session_state.audit_name = report_filename(op, "audit", stamp)
                err_df = result.audit.get_error_report()
                ebuf = io.BytesIO()
                err_df.to_excel(ebuf, index=False)
                st.session_state.error_bytes = ebuf.getvalue()
                st.session_state.error_name = report_filename(op, "errors", stamp)
                st.session_state.output_bytes = None
                st.session_state.output_name = None
                status.update(label="Validation finished", state="complete")
        except MemoryError as exc:
            st.error(
                "The current environment does not have enough memory to process this file. "
                "Reduce the file size or run on a machine with more RAM."
            )
            _issue_expander("Technical details", str(exc))
            _clear_results()
        except Exception as exc:
            user_msg, detail = humanize_exception(exc, "source")
            st.error(user_msg)
            _issue_expander("Technical details", detail)
            _clear_results()
        finally:
            st.session_state.processing = False

    result = st.session_state.pipeline_result
    if result:
        _render_results(result)
        if st.session_state.audit_bytes:
            st.download_button(
                "Download audit report",
                data=st.session_state.audit_bytes,
                file_name=st.session_state.audit_name or "audit_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Per-record status, lookups, and hierarchy outcomes for this run.",
            )
        if st.session_state.error_bytes:
            st.download_button(
                "Download error report",
                data=st.session_state.error_bytes,
                file_name=st.session_state.error_name or "error_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Failed, review, and warning records from this run.",
            )
    _nav(5, 7, next_disabled=st.session_state.pipeline_result is None or st.session_state.processing)


def _render_results(result) -> None:
    summary = result.audit.get_summary()
    counts = action_counts(result.audit.entries)
    status = results_status_label(result)
    if status == "Complete":
        st.success("Complete — all required validations passed.")
    elif status == "Complete with warnings":
        st.warning("Complete with warnings — output can be generated, but noncritical issues remain.")
    elif status == "Failed":
        st.error("Failed — processing could not complete successfully for the submitted records.")
    else:
        st.error("Action required — unresolved issues prevent treating this as a reliable master update.")

    metrics = [
        ("Input records", result.source_row_count),
        ("Successfully processed", summary["successful"]),
        ("Processed with warnings", summary["warnings"]),
        ("Requires review", summary["requires_review"]),
        ("Failed records", summary["failed"]),
    ]
    if counts["inserted"] or counts["updated"]:
        metrics.extend([
            ("Inserted", counts["inserted"]),
            ("Updated", counts["updated"]),
        ])
    cols = st.columns(len(metrics))
    for col, (label, value) in zip(cols, metrics):
        col.metric(label, value)

    if result.validation.errors:
        st.markdown("**Errors**")
        err_rows = [{
            "File / area": e.category,
            "Column": e.field,
            "Row": e.row if e.row and e.row > 0 else "",
            "Issue": humanize_validation_issue(e.category, e.message, e.field, e.row),
        } for e in result.validation.errors]
        _preview_frame(pd.DataFrame(err_rows), "Validation errors.")
    if result.validation.warnings:
        st.markdown("**Warnings**")
        warn_rows = [{
            "File / area": w.category,
            "Column": w.field,
            "Row": w.row if w.row and w.row > 0 else "",
            "Issue": humanize_validation_issue(w.category, w.message, w.field, w.row),
        } for w in result.validation.warnings]
        _preview_frame(pd.DataFrame(warn_rows), "Validation warnings.")
    infos = [i for i in result.validation.issues if i.severity == "INFO"]
    if infos:
        with st.expander("Informational messages"):
            for item in infos[:50]:
                st.caption(item.message)
    st.markdown("**Audit log**")
    _preview_frame(result.audit.to_dataframe(), "Record-level audit.")


def step_output() -> None:
    _step_heading(
        7,
        "Generate and download output",
        "Write a new workbook from the uploaded template. Previous-run files are not reused after inputs change.",
    )
    result = st.session_state.pipeline_result
    if not result:
        st.warning("Run validation first.")
        _nav(6, None)
        return
    op = OPERATIONS[st.session_state.operation_id]
    _render_results(result)
    if not result.ready_for_output:
        st.error(
            "A workbook can still be generated for review, but this run is not a successful master update. "
            "Failed and review records remain in the audit report."
        )
    include_failed = st.checkbox("Include FAILED / REQUIRES_REVIEW rows in the workbook", value=True)
    busy = bool(st.session_state.processing)
    if st.button("Generate output workbook", type="primary", disabled=busy):
        st.session_state.processing = True
        try:
            with st.status("Writing output workbook…", expanded=True) as status:
                status.write("Writing the output workbook")
                records = result.records
                if not include_failed:
                    records = [
                        rec for rec, entry in zip(result.records, result.audit.entries)
                        if entry.status not in {"FAILED", "REQUIRES_REVIEW"}
                    ]
                stamp = st.session_state.run_stamp or datetime.now()
                out_name = output_workbook_name(op, stamp)
                tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx").name
                try:
                    write_output_workbook(
                        template_path=st.session_state.template_path,
                        target_sheet=st.session_state.target_sheet,
                        output_records=records,
                        output_path=tmp_out,
                        target_headers=result.template_schema.headers,
                        preserve_type_hint_row=result.template_schema.has_type_hint_row,
                    )
                    st.session_state.output_bytes = Path(tmp_out).read_bytes()
                    st.session_state.output_name = out_name
                finally:
                    remove_temp_file(tmp_out)
                status.write("Preparing download")
                status.update(label="Workbook ready", state="complete")
                st.success(f"Created {out_name} with {len(records)} data rows.")
        except MemoryError as exc:
            st.error(
                "The current environment does not have enough memory to write the output workbook. "
                "Free memory and try again."
            )
            _issue_expander("Technical details", str(exc))
            st.session_state.output_bytes = None
            st.session_state.output_name = None
        except OSError as exc:
            user_msg, detail = humanize_exception(exc, "output")
            st.error(user_msg)
            _issue_expander("Technical details", detail)
            st.session_state.output_bytes = None
            st.session_state.output_name = None
        except Exception as exc:
            user_msg, detail = humanize_exception(exc, "output")
            st.error(user_msg)
            _issue_expander("Technical details", detail)
            st.session_state.output_bytes = None
            st.session_state.output_name = None
        finally:
            st.session_state.processing = False

    st.markdown("**Downloads for this run**")
    d1, d2, d3 = st.columns(3)
    with d1:
        if st.session_state.output_bytes:
            st.download_button(
                "Final Excel workbook",
                data=st.session_state.output_bytes,
                file_name=st.session_state.output_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Template-compliant consumer master workbook for the current run.",
                use_container_width=True,
            )
            st.caption(st.session_state.output_name)
        else:
            st.caption("Workbook is available after generation.")
    with d2:
        if st.session_state.audit_bytes:
            st.download_button(
                "Audit report",
                data=st.session_state.audit_bytes,
                file_name=st.session_state.audit_name or "audit_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Full per-record audit for the current validation run.",
                use_container_width=True,
                key="dl_audit2",
            )
            st.caption(st.session_state.audit_name or "")
    with d3:
        if st.session_state.error_bytes:
            st.download_button(
                "Error report",
                data=st.session_state.error_bytes,
                file_name=st.session_state.error_name or "error_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Unresolved issues from the current validation run.",
                use_container_width=True,
                key="dl_err2",
            )
            st.caption(st.session_state.error_name or "")
    _nav(6, None)


def main() -> None:
    st.set_page_config(
        page_title="Master Data Automation",
        page_icon="▦",
        layout="wide",
    )
    _inject_css()
    _init_state()
    st.markdown(
        """
        <div class="mda-hero">
          <div class="mda-mark">MDA</div>
          <div>
            <p class="mda-kicker">Consumer Master Update System</p>
            <h1>Master Data Automation</h1>
            <p>Transform consumer records, resolve network hierarchy, validate reference data, and generate template-compliant Excel output.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    statuses = compute_step_statuses(st.session_state, st.session_state.step)
    st.markdown(stepper_html(statuses), unsafe_allow_html=True)
    dispatch = {
        1: step_template,
        2: step_operation,
        3: step_hierarchy,
        4: step_source,
        5: step_mappings,
        6: step_dry_run,
        7: step_output,
    }
    dispatch[st.session_state.step]()


if __name__ == "__main__":
    main()
