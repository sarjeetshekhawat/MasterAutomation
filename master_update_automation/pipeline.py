"""Reusable transformation pipeline from source data to the target template."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from .audit_logger import AuditEntry, AuditLogger
from .column_mapper import (
    MappingResult,
    create_column_mapping,
    get_hierarchy_mapping_dict,
    get_mapping_dict,
)
from .config import (
    BUSINESS_KEY_SOURCE_CANDIDATES,
    BUSINESS_KEY_TARGET,
    CATEGORY_SOURCE_COLUMNS,
    FIXED_METER_CATEGORY_LOOKUP_NAME,
    HIERARCHY_LEVELS,
    MANDATORY_HIERARCHY_FIELDS,
    MANDATORY_HIERARCHY_LEVELS,
    MANDATORY_TARGET_FIELDS,
    OPTIONAL_LOOKUP_FIELDS,
    REFERENCE_CATEGORY_MAP,
    REQUIRED_SOURCE_COLUMNS,
    TARGET_FIELD_TYPES,
    TARGET_HIERARCHY_MAP,
    UUID_FIELDS,
    VALUE_ALIASES,
    AuditStatus,
    Category,
    FieldType,
    Operation,
)
from .consumer_rules import apply_consumer_identification_rules, apply_meter_make_rules
from .file_loader import (
    detect_target_sheet,
    load_excel_workbook,
    read_hierarchy_file,
    read_source_data,
)
from .hierarchy_mapper import HierarchyMapper, HierarchyRecord
from .record_matcher import detect_duplicate_keys, match_records
from .reference_lookup import LookupResult, ReferenceLookup
from .schema_detector import TemplateSchema, detect_template_schema
from .uuid_utils import is_valid_uuid, normalise_uuid
from .validator import ValidationReport, validate_output_dataset, validate_reference_categories, validate_source_data

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    records: List[Dict[str, str]]
    audit: AuditLogger
    validation: ValidationReport
    mapping: MappingResult
    hierarchy_summary: Dict
    template_schema: TemplateSchema
    ready_for_output: bool
    source_row_count: int
    duplicate_identifiers: Dict[str, List[int]] = field(default_factory=dict)


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def _alias_value(field: str, value: str) -> str:
    aliases = VALUE_ALIASES.get(field, {})
    return aliases.get(value.upper(), value) if value else value


def find_source_key_column(source_headers: List[str]) -> Optional[str]:
    lower_map = {h.strip().lower(): h for h in source_headers if h}
    for candidate in BUSINESS_KEY_SOURCE_CANDIDATES:
        if candidate in lower_map:
            return lower_map[candidate]
    return None


def extract_hierarchy_keys(
    row: pd.Series,
    hierarchy_map: Dict[str, str],
) -> Dict[str, str]:
    keys: Dict[str, str] = {}
    for src_col, internal in hierarchy_map.items():
        level_field = internal.replace("_hierarchy_", "")
        keys[level_field] = _clean(row.get(src_col, ""))
    for level in HIERARCHY_LEVELS:
        for kind in ("code", "name"):
            field = f"{level}_{kind}"
            if field in keys and keys[field]:
                continue
            for col in row.index:
                if str(col).strip().lower() == f"{level} {kind}":
                    keys[field] = _clean(row.get(col, ""))
    return keys


def _source_category_hint(row: pd.Series) -> str:
    for col in row.index:
        if str(col).strip().lower() in CATEGORY_SOURCE_COLUMNS:
            return _clean(row.get(col, "")).upper()
    return ""


def _ordered_record(headers: List[str], values: Dict[str, str]) -> Dict[str, str]:
    lookup = {k.lower().strip(): v for k, v in values.items()}
    ordered: Dict[str, str] = {}
    for header in headers:
        ordered[header] = lookup.get(header.lower().strip(), "")
    return ordered


def transform_record(
    row: pd.Series,
    source_row_number: int,
    operation: Operation,
    mapping_result: MappingResult,
    ref_lookup: ReferenceLookup,
    hierarchy_mapper: HierarchyMapper,
    target_headers: List[str],
    match_action: str,
    business_key: str,
) -> Tuple[Dict[str, str], AuditEntry]:
    entry = AuditEntry(
        source_row=source_row_number,
        business_key=business_key,
        operation=operation.label,
        status=AuditStatus.INSERTED.value if match_action == "INSERT" else AuditStatus.UPDATED.value,
        action=match_action,
    )
    values: Dict[str, str] = {h.lower().strip(): "" for h in target_headers}
    mapping_dict = get_mapping_dict(mapping_result)
    hierarchy_map = get_hierarchy_mapping_dict(mapping_result)

    hint = _source_category_hint(row)
    if hint and hint in {c.value for c in Category} and hint != operation.source.value:
        entry.warnings.append(
            f"Source meter category '{hint}' does not match selected source "
            f"'{operation.source.value}'"
        )

    for src_col, tgt_col in mapping_dict.items():
        tgt_lower = tgt_col.lower().strip()
        ft = TARGET_FIELD_TYPES.get(tgt_lower, FieldType.TEXT)
        if ft in (FieldType.REFERENCE_LOOKUP, FieldType.BUSINESS_RULE, FieldType.HIERARCHY_LOOKUP):
            continue
        raw = _clean(row.get(src_col, ""))
        raw = _alias_value(tgt_lower, raw)
        if tgt_lower in UUID_FIELDS and raw:
            if is_valid_uuid(raw):
                values[tgt_lower] = normalise_uuid(raw)
            else:
                values[tgt_lower] = raw
                entry.errors.append(f"Invalid UUID in source field '{src_col}': {raw}")
        else:
            values[tgt_lower] = raw

    hierarchy_keys = extract_hierarchy_keys(row, hierarchy_map)
    hierarchy: HierarchyRecord = hierarchy_mapper.match_consumer(dict(row), hierarchy_keys)
    entry.warnings.extend(hierarchy.warnings)
    if hierarchy.errors:
        entry.errors.extend(hierarchy.errors)
    if any(m.is_ambiguous for m in hierarchy.matches.values()):
        entry.hierarchy_status = "AMBIGUOUS"
        entry.status = AuditStatus.REQUIRES_REVIEW.value
    elif not any(m.success for m in hierarchy.matches.values()):
        entry.hierarchy_status = "MISSING"
    else:
        failed_required = [
            lvl for lvl in MANDATORY_HIERARCHY_LEVELS
            if not hierarchy.matches.get(lvl, None) or not hierarchy.matches[lvl].success
        ]
        entry.hierarchy_status = "OK" if not failed_required else "PARTIAL"

    for target_field, (level, _kind) in TARGET_HIERARCHY_MAP.items():
        match = hierarchy.matches.get(level)
        if match and match.success:
            values[target_field] = match.uuid
        elif target_field in MANDATORY_HIERARCHY_FIELDS:
            entry.errors.append(f"Required hierarchy field '{target_field}' could not be resolved")

    source_ident_col = None
    source_make_col = None
    for m in mapping_result.mappings:
        if m.target_column.lower().strip() == "consumer_identy" or m.target_column == "consumer_identy":
            source_ident_col = m.source_column
        if m.target_column.lower().strip() == "meter_make":
            source_make_col = m.source_column
    if source_ident_col is None:
        for col in row.index:
            if str(col).strip().lower() == "consumer identification":
                source_ident_col = col
    if source_make_col is None:
        for col in row.index:
            if str(col).strip().lower() == "meter make":
                source_make_col = col

    ident_value = _clean(row.get(source_ident_col, "")) if source_ident_col is not None else ""
    ident_result, ident_rule = apply_consumer_identification_rules(operation, ident_value, ref_lookup)
    entry.transformations.append(ident_rule)
    if ident_result.success:
        values["consumer_identy"] = ident_result.uuid
    else:
        entry.failed_lookups.append(f"consumer_identy={ident_value}")
        entry.errors.append(ident_result.error or "Consumer identification lookup failed")

    make_value = _clean(row.get(source_make_col, "")) if source_make_col is not None else ""
    if make_value:
        make_result, make_rule = apply_meter_make_rules(operation, make_value, ref_lookup)
        entry.transformations.append(make_rule)
        if make_result.success:
            values["meter_make"] = make_result.uuid
        else:
            entry.failed_lookups.append(f"meter_make={make_value}")
            entry.warnings.append(make_result.error or "Meter make lookup failed")
    else:
        entry.transformations.append("Meter make left blank (source empty)")

    lookup_source_by_target: Dict[str, str] = {}
    for m in mapping_result.mappings:
        if not m.target_column.startswith("_"):
            lookup_source_by_target[m.target_column.lower().strip()] = m.source_column

    for target_field, _category in REFERENCE_CATEGORY_MAP.items():
        if target_field in {"consumer_identy", "meter_make"}:
            continue
        if target_field == "meter_category":
            raw = FIXED_METER_CATEGORY_LOOKUP_NAME
        else:
            src_col = lookup_source_by_target.get(target_field)
            raw = _clean(row.get(src_col, "")) if src_col else ""
            raw = _alias_value(target_field, raw)
            if not raw:
                if target_field in MANDATORY_TARGET_FIELDS:
                    entry.warnings.append(f"Mandatory lookup field '{target_field}' has no source value")
                continue
        result: LookupResult = ref_lookup.lookup_for_target_field(
            target_field, raw, dest_category=operation.destination
        )
        if result.success:
            if target_field == "meter_category" and (
                not result.uuid or not is_valid_uuid(result.uuid)
            ):
                entry.failed_lookups.append(f"{target_field}={raw}")
                entry.errors.append(
                    f"Main Meter was found in category '{_category}' but its UUID "
                    "is missing or invalid. Cannot populate meter_category."
                )
                continue
            values[target_field] = result.uuid
            entry.transformations.append(f"{target_field}: '{raw}' → {result.uuid}")
        elif result.is_ambiguous:
            entry.failed_lookups.append(f"{target_field}={raw}")
            entry.errors.append(result.error)
            entry.status = AuditStatus.REQUIRES_REVIEW.value
        else:
            entry.failed_lookups.append(f"{target_field}={raw}")
            if target_field == "meter_category":
                entry.errors.append(
                    result.error
                    or (
                        f"Required meter category '{FIXED_METER_CATEGORY_LOOKUP_NAME}' "
                        f"could not be resolved from '{_category}' in "
                        "ref_project_masters_lov"
                    )
                )
            elif target_field in OPTIONAL_LOOKUP_FIELDS:
                entry.warnings.append(result.error)
            else:
                entry.errors.append(result.error)

    for field_name in UUID_FIELDS:
        current = values.get(field_name, "")
        if current:
            if is_valid_uuid(current):
                values[field_name] = normalise_uuid(current)
            else:
                entry.errors.append(f"Invalid UUID in '{field_name}': {current}")

    if match_action in {"FAILED", "DUPLICATE", "AMBIGUOUS"}:
        entry.status = (
            AuditStatus.REQUIRES_REVIEW.value
            if match_action == "AMBIGUOUS"
            else AuditStatus.FAILED.value
        )
        if match_action != "AMBIGUOUS":
            entry.errors.append(f"Record matching action: {match_action}")
    elif entry.errors:
        if entry.status != AuditStatus.REQUIRES_REVIEW.value:
            entry.status = AuditStatus.FAILED.value
    elif entry.warnings:
        if entry.status not in {AuditStatus.REQUIRES_REVIEW.value}:
            entry.status = AuditStatus.WARNING.value
    elif match_action == "UPDATE":
        entry.status = AuditStatus.UPDATED.value
    elif match_action == "INSERT":
        entry.status = AuditStatus.INSERTED.value

    return _ordered_record(target_headers, values), entry


def run_pipeline(
    template_path: str,
    target_sheet: str,
    operation: Operation,
    hierarchy_path: str,
    source_path: str,
    source_sheet: Optional[str] = None,
    custom_map: Optional[Dict[str, str]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> PipelineResult:
    def _progress(message: str) -> None:
        if progress:
            progress(message)

    try:
        return _run_pipeline(
            template_path=template_path,
            target_sheet=target_sheet,
            operation=operation,
            hierarchy_path=hierarchy_path,
            source_path=source_path,
            source_sheet=source_sheet,
            custom_map=custom_map,
            notify=_progress,
        )
    except MemoryError as exc:
        raise MemoryError(
            "The current environment does not have enough memory to process this file. "
            "Reduce the file size, close other applications, or run on a machine with more RAM."
        ) from exc


def _run_pipeline(
    template_path: str,
    target_sheet: str,
    operation: Operation,
    hierarchy_path: str,
    source_path: str,
    source_sheet: Optional[str],
    custom_map: Optional[Dict[str, str]],
    notify: Callable[[str], None],
) -> PipelineResult:
    notify("Reading input files")
    wb = load_excel_workbook(template_path)
    if not target_sheet:
        detected = detect_target_sheet(wb)
        if not detected:
            wb.close()
            raise ValueError("Target sheet could not be identified. Please select it explicitly.")
        target_sheet = detected
    notify("Validating workbook structure")
    schema = detect_template_schema(wb, target_sheet)
    ref_lookup = ReferenceLookup()
    ref_lookup.load_from_workbook(wb)
    wb.close()

    source_df = read_source_data(source_path, source_sheet, skip_type_hint_row=False)
    hierarchy_df = read_hierarchy_file(hierarchy_path)
    mapper = HierarchyMapper()
    hierarchy_summary = mapper.load_hierarchy(hierarchy_df)
    notify("Preparing reference lookups and hierarchy indexes")

    mapping = create_column_mapping(
        list(source_df.columns),
        schema.headers,
        custom_map=custom_map,
    )
    validation = ValidationReport()
    validation.merge(validate_reference_categories(ref_lookup, operation.destination))
    validation.merge(validate_source_data(source_df, REQUIRED_SOURCE_COLUMNS))
    for msg in mapper.validate_hierarchy_columns():
        validation.add_warning("hierarchy", msg)

    source_key = find_source_key_column(list(source_df.columns))
    if not source_key:
        validation.add_error("consumer", "Could not identify a consumer business key column")
        audit = AuditLogger(operation.label)
        return PipelineResult(
            records=[],
            audit=audit,
            validation=validation,
            mapping=mapping,
            hierarchy_summary=hierarchy_summary,
            template_schema=schema,
            ready_for_output=False,
            source_row_count=len(source_df),
        )

    duplicates = detect_duplicate_keys(source_df, source_key)
    match_results = match_records(source_df, None, source_key, BUSINESS_KEY_TARGET)
    match_by_index = {m.source_index: m for m in match_results}

    audit = AuditLogger(operation.label)
    records: List[Dict[str, str]] = []
    notify("Resolving reference UUIDs, matching hierarchy, and applying business rules")
    for idx, row in source_df.iterrows():
        match = match_by_index.get(idx)
        action = match.action if match else "INSERT"
        key = match.business_key if match else _clean(row.get(source_key, ""))
        excel_row = int(idx) + 2
        record, entry = transform_record(
            row=row,
            source_row_number=excel_row,
            operation=operation,
            mapping_result=mapping,
            ref_lookup=ref_lookup,
            hierarchy_mapper=mapper,
            target_headers=schema.headers,
            match_action=action,
            business_key=key,
        )
        if match and match.error:
            entry.errors.append(match.error)
            if action in {"FAILED", "DUPLICATE"}:
                entry.status = AuditStatus.FAILED.value
            elif action == "AMBIGUOUS":
                entry.status = AuditStatus.REQUIRES_REVIEW.value
        audit.add_entry(entry)
        records.append(record)

    notify("Validating transformed data")
    validation.merge(validate_output_dataset(records, schema.headers, BUSINESS_KEY_TARGET))
    failed_or_review = any(
        e.status in {AuditStatus.FAILED.value, AuditStatus.REQUIRES_REVIEW.value}
        for e in audit.entries
    )
    ready = (not failed_or_review) and validation.error_count == 0
    if not ready:
        validation.add_warning(
            "output",
            "Final master workbook should not be treated as successful while "
            "required lookups, hierarchy matches, or validations remain unresolved.",
        )
    return PipelineResult(
        records=records,
        audit=audit,
        validation=validation,
        mapping=mapping,
        hierarchy_summary=hierarchy_summary,
        template_schema=schema,
        ready_for_output=ready,
        source_row_count=len(source_df),
        duplicate_identifiers=duplicates,
    )
