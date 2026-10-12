"""Source-to-target column mapping with automatic detection and overrides."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .config import SOURCE_TO_TARGET_MAP, TARGET_FIELD_TYPES, FieldType

logger = logging.getLogger(__name__)


@dataclass
class ColumnMapping:
    source_column: str
    target_column: str
    transformation: str = "direct"
    lookup_category: str = ""
    is_confirmed: bool = False
    confidence: float = 1.0


@dataclass
class MappingResult:
    mappings: List[ColumnMapping]
    unmapped_source: List[str]
    unmapped_target: List[str]
    ambiguous_mappings: List[Tuple[str, List[str]]]

    @property
    def all_confirmed(self) -> bool:
        return all(m.is_confirmed for m in self.mappings)

    @property
    def mapped_target_columns(self) -> set:
        return {m.target_column for m in self.mappings}


def normalise_header(header: str) -> str:
    return (
        header.strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
        .replace("?", "")
        .replace("  ", " ")
    )


def _transformation_for(target_col: str) -> str:
    if target_col.startswith("_hierarchy_"):
        return "hierarchy"
    ft = TARGET_FIELD_TYPES.get(target_col, FieldType.TEXT)
    if ft == FieldType.REFERENCE_LOOKUP:
        return "reference_lookup"
    if ft == FieldType.BUSINESS_RULE:
        return "business_rule"
    if ft == FieldType.HIERARCHY_LOOKUP:
        return "hierarchy"
    return "direct"


def _actual_target(target_headers: List[str], logical_name: str) -> Optional[str]:
    for th in target_headers:
        if th and th.lower().strip() == logical_name.lower().strip():
            return th
    return None


def create_column_mapping(
    source_headers: List[str],
    target_headers: List[str],
    custom_map: Optional[Dict[str, str]] = None,
) -> MappingResult:
    mappings: List[ColumnMapping] = []
    mapped_sources: set = set()
    mapped_targets: set = set()
    ambiguous: List[Tuple[str, List[str]]] = []

    target_norm_map: Dict[str, str] = {}
    for th in target_headers:
        if th:
            target_norm_map[normalise_header(th)] = th

    if custom_map:
        for src, tgt in custom_map.items():
            if src in source_headers and tgt in target_headers:
                mappings.append(ColumnMapping(
                    source_column=src,
                    target_column=tgt,
                    transformation=_transformation_for(tgt.lower().strip()),
                    is_confirmed=True,
                    confidence=1.0,
                ))
                mapped_sources.add(src)
                mapped_targets.add(tgt)

    for src_header in source_headers:
        if src_header in mapped_sources:
            continue
        src_norm = normalise_header(src_header)
        if src_norm not in SOURCE_TO_TARGET_MAP:
            continue
        target_col = SOURCE_TO_TARGET_MAP[src_norm]
        transformation = _transformation_for(target_col)
        if target_col.startswith("_hierarchy_"):
            mappings.append(ColumnMapping(
                source_column=src_header,
                target_column=target_col,
                transformation="hierarchy",
                is_confirmed=True,
                confidence=0.9,
            ))
            mapped_sources.add(src_header)
            continue
        actual_target = _actual_target(target_headers, target_col)
        if actual_target and actual_target not in mapped_targets:
            mappings.append(ColumnMapping(
                source_column=src_header,
                target_column=actual_target,
                transformation=transformation,
                is_confirmed=True,
                confidence=0.9,
            ))
            mapped_sources.add(src_header)
            mapped_targets.add(actual_target)

    for src_header in source_headers:
        if src_header in mapped_sources:
            continue
        src_norm = normalise_header(src_header)
        if src_norm in target_norm_map and target_norm_map[src_norm] not in mapped_targets:
            actual_target = target_norm_map[src_norm]
            mappings.append(ColumnMapping(
                source_column=src_header,
                target_column=actual_target,
                transformation=_transformation_for(actual_target.lower().strip()),
                is_confirmed=True,
                confidence=0.8,
            ))
            mapped_sources.add(src_header)
            mapped_targets.add(actual_target)

    unmapped_source = [s for s in source_headers if s and s not in mapped_sources]
    unmapped_target = [
        t for t in target_headers
        if t and t not in mapped_targets and t.lower().strip() not in {"id"}
    ]
    result = MappingResult(
        mappings=mappings,
        unmapped_source=unmapped_source,
        unmapped_target=unmapped_target,
        ambiguous_mappings=ambiguous,
    )
    logger.info(
        "Column mapping: %s mapped, %s unmapped source, %s unmapped target",
        len(mappings),
        len(unmapped_source),
        len(unmapped_target),
    )
    return result


def get_mapping_dict(mapping_result: MappingResult) -> Dict[str, str]:
    return {
        m.source_column: m.target_column
        for m in mapping_result.mappings
        if not m.target_column.startswith("_")
    }


def get_hierarchy_mapping_dict(mapping_result: MappingResult) -> Dict[str, str]:
    return {
        m.source_column: m.target_column
        for m in mapping_result.mappings
        if m.target_column.startswith("_hierarchy_")
    }
