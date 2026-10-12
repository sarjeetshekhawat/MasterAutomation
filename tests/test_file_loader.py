"""Tests for CSV/Excel loading, size limits, and inspection."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd
import pytest

from master_update_automation.config import MAX_UPLOAD_SIZE_BYTES, MAX_UPLOAD_SIZE_MIB
from master_update_automation.file_loader import (
    FileLoadError,
    inspect_csv_file,
    load_tabular_file,
    read_csv_data,
    read_hierarchy_file,
    save_upload_stream,
    validate_extension,
    validate_upload_size,
)
from tests.conftest import MAIN_METER_ID
from tests.test_pipeline_integration import (
    _base_source_row,
    _hierarchy_csv,
    _source_excel,
    _template_path,
    _tmpdir,
)
from master_update_automation.pipeline import run_pipeline
from tests.conftest import operation


def _write(path: str, text: str, encoding: str = "utf-8") -> str:
    Path(path).write_text(text, encoding=encoding)
    return path


def test_streamlit_and_app_limits_are_3_gib():
    assert MAX_UPLOAD_SIZE_MIB == 3072
    assert MAX_UPLOAD_SIZE_BYTES == 3072 * 1024 * 1024


def test_file_below_limit_is_accepted():
    validate_upload_size("ok.csv", 1024)


def test_file_above_limit_is_rejected_with_details():
    size = MAX_UPLOAD_SIZE_BYTES + 1
    with pytest.raises(FileLoadError) as exc:
        validate_upload_size("huge.csv", size)
    msg = str(exc.value)
    assert "huge.csv" in msg
    assert "3 GB" in msg
    assert "Split the file" in msg


def test_template_role_rejects_csv(tmp_path):
    csv_path = tmp_path / "template.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(FileLoadError) as exc:
        load_tabular_file(str(csv_path), "template")
    assert "target template" in str(exc.value)
    assert ".csv" in str(exc.value)


def test_hierarchy_csv_utf8_and_leading_zeros(tmp_path):
    path = tmp_path / "hier.csv"
    path.write_text("DT Code,DT Name\n00123,Alpha\n", encoding="utf-8")
    df = read_hierarchy_file(str(path))
    assert df.iloc[0]["DT Code"] == "00123"


def test_hierarchy_csv_utf8_bom(tmp_path):
    path = tmp_path / "hier_bom.csv"
    path.write_bytes("DT Code,DT Name\n1085140006,GOVINDAM\n".encode("utf-8-sig"))
    df = read_hierarchy_file(str(path))
    assert "DT Code" in df.columns
    assert df.iloc[0]["DT Code"] == "1085140006"


def test_csv_quoted_commas(tmp_path):
    path = tmp_path / "quoted.csv"
    path.write_text('Consumer Number,Consumer Address\nC001,"Street, Block 2"\n', encoding="utf-8")
    df = read_csv_data(str(path))
    assert df.iloc[0]["Consumer Address"] == "Street, Block 2"


def test_csv_semicolon_delimiter(tmp_path):
    path = tmp_path / "semi.csv"
    path.write_text("Consumer Number;Account Number\nC001;A001\n", encoding="utf-8")
    df = read_csv_data(str(path))
    assert list(df.columns) == ["Consumer Number", "Account Number"]
    assert df.iloc[0]["Consumer Number"] == "C001"


def test_csv_uuid_preserved_as_text(tmp_path):
    uuid = "ed1f2293-af64-4346-978b-324d5998f539"
    path = tmp_path / "uuid.csv"
    path.write_text(f"id,name\n{uuid},Main Meter\n", encoding="utf-8")
    df = read_csv_data(str(path))
    assert df.iloc[0]["id"] == uuid


def test_empty_csv_raises(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(FileLoadError) as exc:
        read_csv_data(str(path))
    assert "empty" in str(exc.value).lower()


def test_csv_missing_header_row(tmp_path):
    path = tmp_path / "no_header.csv"
    path.write_bytes(b"\n\n")
    with pytest.raises(FileLoadError):
        read_csv_data(str(path))


def test_inspect_csv_duplicate_identifiers(tmp_path):
    path = tmp_path / "dups.csv"
    path.write_text(
        "Consumer Number,Consumer Name\nC001,A\nC001,B\nC002,C\n",
        encoding="utf-8",
    )
    inspection = inspect_csv_file(str(path))
    assert inspection.row_count == 3
    assert inspection.duplicate_key_count == 1
    assert inspection.is_csv


def test_unsupported_source_extension(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("nope", encoding="utf-8")
    with pytest.raises(FileLoadError) as exc:
        validate_extension(str(path), (".csv", ".xlsx"), "consumer source data")
    assert ".txt" in str(exc.value)


def test_save_upload_stream_rejects_oversize():
    payload = io.BytesIO(b"abc")
    with pytest.raises(FileLoadError):
        save_upload_stream(payload, ".csv", "big.csv", size=MAX_UPLOAD_SIZE_BYTES + 10)


def test_consumer_csv_and_excel_produce_equivalent_pipeline_results():
    d = _tmpdir()
    tpl = _template_path(d)
    hier = _hierarchy_csv(d)
    rows = [_base_source_row()]
    xlsx = _source_excel(d, rows)
    csv_path = os.path.join(d, "source.csv")
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8")
    op = operation("WC", "HTCT")
    excel_result = run_pipeline(tpl, "HTCT Consumer Master", op, hier, xlsx, "Sheet1")
    csv_result = run_pipeline(tpl, "HTCT Consumer Master", op, hier, csv_path, None)
    assert excel_result.records[0]["meter_category"] == f"{{{MAIN_METER_ID}}}"
    assert csv_result.records[0]["meter_category"] == excel_result.records[0]["meter_category"]
    assert csv_result.records[0]["consumer_identy"] == excel_result.records[0]["consumer_identy"]
    assert csv_result.records[0]["consumer_number"] == excel_result.records[0]["consumer_number"]


def test_load_tabular_source_csv(tmp_path):
    path = tmp_path / "src.csv"
    path.write_text("Consumer Number,Account Number,Consumer Name\nC1,A1,Name\n", encoding="utf-8")
    df = load_tabular_file(str(path), "source")
    assert len(df) == 1
    assert df.iloc[0]["Consumer Number"] == "C1"
