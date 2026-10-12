"""Match consumer records to the network hierarchy report."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .config import HIERARCHY_CSV_COLUMN_MAP, HIERARCHY_LEVELS
from .uuid_utils import normalise_uuid

logger = logging.getLogger(__name__)


@dataclass
class HierarchyMatch:
    success: bool
    level: str = ""
    uuid: str = ""
    name: str = ""
    code: str = ""
    error: str = ""
    is_ambiguous: bool = False
    match_count: int = 0


@dataclass
class HierarchyRecord:
    matches: Dict[str, HierarchyMatch]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    matched_row_index: Optional[int] = None

    @property
    def all_matched(self) -> bool:
        return all(m.success for m in self.matches.values())

    @property
    def failed_levels(self) -> List[str]:
        return [level for level, m in self.matches.items() if not m.success]


class HierarchyMapper:
    def __init__(self) -> None:
        self._df: Optional[pd.DataFrame] = None
        self._column_map: Dict[str, Dict[str, str]] = {}
        self._available_levels: List[str] = []
        self._code_indices: Dict[str, Dict[str, List[int]]] = {}
        self._duplicates: Dict[str, List[str]] = {}

    def load_hierarchy(self, df: pd.DataFrame) -> Dict[str, Any]:
        self._df = df.copy()
        self._detect_columns()
        self._build_indices()
        return {
            "total_rows": len(df),
            "available_levels": self._available_levels,
            "detected_columns": self._column_map,
            "missing_levels": [lvl for lvl in HIERARCHY_LEVELS if lvl not in self._available_levels],
            "duplicates": self._duplicates,
        }

    def _detect_columns(self) -> None:
        if self._df is None:
            return
        df_cols_lower = {c.strip().lower(): c for c in self._df.columns}
        self._column_map.clear()
        self._available_levels = []
        for level in HIERARCHY_LEVELS:
            expected = HIERARCHY_CSV_COLUMN_MAP.get(level, {})
            detected: Dict[str, str] = {}
            for field_type in ("name", "code", "id"):
                expected_col = expected.get(field_type, "")
                if not expected_col:
                    continue
                if expected_col in self._df.columns:
                    detected[field_type] = expected_col
                else:
                    exp_lower = expected_col.strip().lower()
                    if exp_lower in df_cols_lower:
                        detected[field_type] = df_cols_lower[exp_lower]
            if detected:
                self._column_map[level] = detected
                self._available_levels.append(level)

    def _build_indices(self) -> None:
        if self._df is None:
            return
        self._code_indices.clear()
        self._duplicates.clear()
        for level in self._available_levels:
            cols = self._column_map.get(level, {})
            code_col = cols.get("code")
            id_col = cols.get("id")
            if not code_col or code_col not in self._df.columns:
                continue
            index: Dict[str, List[int]] = {}
            for idx, code_val in self._df[code_col].items():
                if pd.isna(code_val):
                    continue
                code_str = str(code_val).strip()
                if not code_str:
                    continue
                index.setdefault(code_str, []).append(idx)
            if id_col and id_col in self._df.columns:
                for code_str, idxs in index.items():
                    ids = {
                        str(self._df.at[i, id_col]).strip().lower()
                        for i in idxs
                        if pd.notna(self._df.at[i, id_col])
                    }
                    ids.discard("nan")
                    ids.discard("")
                    if len(ids) > 1:
                        self._duplicates.setdefault(level, []).append(code_str)
            self._code_indices[level] = index

    def match_consumer(
        self,
        source_record: Dict[str, str],
        hierarchy_keys: Dict[str, str],
    ) -> HierarchyRecord:
        errors: List[str] = []
        warnings: List[str] = []
        matched_idx: Optional[int] = None
        used_level = ""

        search_order = ["dt", "feeder", "substation", "subdivision", "division", "circle", "zone", "discom"]
        for level in search_order:
            result = self._match_level(level, hierarchy_keys)
            if result is None:
                continue
            status, idxs = result
            if status == "missing":
                continue
            if status == "ambiguous":
                warnings.append(
                    f"Ambiguous match for {level} using available identifiers "
                    f"({len(idxs)} candidates). Record flagged for review."
                )
                return self._empty_record(
                    errors + [f"Ambiguous hierarchy match at {level}"],
                    warnings,
                    ambiguous_level=level,
                    match_count=len(idxs),
                )
            matched_idx = idxs[0]
            used_level = level
            break

        if matched_idx is None:
            errors.append("No matching hierarchy row found using codes or parent-qualified names")
            return self._empty_record(errors, warnings)

        assert self._df is not None
        matched_row = self._df.loc[matched_idx]
        matches: Dict[str, HierarchyMatch] = {}
        for level in HIERARCHY_LEVELS:
            if level not in self._available_levels:
                matches[level] = HierarchyMatch(
                    success=False,
                    level=level,
                    error=f"Level '{level}' not available in hierarchy report",
                )
                continue
            cols = self._column_map[level]
            uuid_val = self._cell(matched_row, cols.get("id"))
            name_val = self._cell(matched_row, cols.get("name"))
            code_val = self._cell(matched_row, cols.get("code"))
            requested_code = hierarchy_keys.get(f"{level}_code", "").strip()
            if requested_code and code_val and requested_code != code_val:
                if level in ("dt", "feeder") and used_level != level:
                    matches[level] = HierarchyMatch(
                        success=False,
                        level=level,
                        error=(
                            f"Source {level} code '{requested_code}' does not match "
                            f"hierarchy row code '{code_val}'"
                        ),
                    )
                    continue
            if uuid_val:
                matches[level] = HierarchyMatch(
                    success=True,
                    level=level,
                    uuid=normalise_uuid(uuid_val),
                    name=name_val,
                    code=code_val,
                    match_count=1,
                )
            else:
                matches[level] = HierarchyMatch(
                    success=False,
                    level=level,
                    error=f"UUID not available for level '{level}' in matched row",
                )

        parent_issues = self._validate_parents(hierarchy_keys, matches)
        warnings.extend(parent_issues)
        return HierarchyRecord(
            matches=matches,
            errors=errors,
            warnings=warnings,
            matched_row_index=matched_idx,
        )

    def _match_level(
        self,
        level: str,
        hierarchy_keys: Dict[str, str],
    ) -> Optional[Tuple[str, List[int]]]:
        source_code = hierarchy_keys.get(f"{level}_code", "").strip()
        source_name = hierarchy_keys.get(f"{level}_name", "").strip()
        if not source_code and not source_name:
            return None
        if source_code and level in self._code_indices:
            idxs = self._code_indices[level].get(source_code, [])
            if not idxs:
                return ("missing", [])
            unique = self._unique_indices(level, idxs)
            if len(unique) == 1:
                return ("unique", unique)
            narrowed = self._narrow_indices(idxs, hierarchy_keys, level)
            unique_n = self._unique_indices(level, narrowed)
            if len(unique_n) == 1:
                return ("unique", unique_n)
            if len(unique_n) > 1:
                return ("ambiguous", unique_n)
            return ("missing", [])
        if source_name and level in self._available_levels and self._df is not None:
            name_col = self._column_map[level].get("name")
            if not name_col:
                return None
            mask = self._df[name_col].astype(str).str.strip().str.upper() == source_name.upper()
            idxs = list(self._df.index[mask])
            if not idxs:
                return ("missing", [])
            narrowed = self._narrow_indices(idxs, hierarchy_keys, level)
            unique_n = self._unique_indices(level, narrowed)
            if len(unique_n) == 1:
                return ("unique", unique_n)
            if len(unique_n) > 1:
                return ("ambiguous", unique_n)
        return None

    def _unique_indices(self, level: str, idxs: List[int]) -> List[int]:
        if self._df is None or not idxs:
            return idxs
        id_col = self._column_map.get(level, {}).get("id")
        if not id_col or id_col not in self._df.columns:
            return idxs
        seen: Dict[str, int] = {}
        for i in idxs:
            uid = str(self._df.at[i, id_col]).strip().lower()
            if uid and uid not in seen:
                seen[uid] = i
        return list(seen.values())

    def _narrow_indices(
        self,
        idxs: List[int],
        hierarchy_keys: Dict[str, str],
        current_level: str,
    ) -> List[int]:
        if self._df is None or current_level not in HIERARCHY_LEVELS:
            return idxs
        current_idx = HIERARCHY_LEVELS.index(current_level)
        remaining = list(idxs)
        for parent_level in HIERARCHY_LEVELS[:current_idx]:
            parent_code = hierarchy_keys.get(f"{parent_level}_code", "").strip()
            parent_name = hierarchy_keys.get(f"{parent_level}_name", "").strip()
            if parent_level not in self._column_map:
                continue
            parent_code_col = self._column_map[parent_level].get("code")
            parent_name_col = self._column_map[parent_level].get("name")
            filtered = remaining
            if parent_code and parent_code_col:
                filtered = [
                    i for i in remaining
                    if str(self._df.at[i, parent_code_col]).strip() == parent_code
                ]
            elif parent_name and parent_name_col:
                filtered = [
                    i for i in remaining
                    if str(self._df.at[i, parent_name_col]).strip().upper() == parent_name.upper()
                ]
            if filtered:
                remaining = filtered
        return remaining

    def _validate_parents(
        self,
        hierarchy_keys: Dict[str, str],
        matches: Dict[str, HierarchyMatch],
    ) -> List[str]:
        issues: List[str] = []
        for level, match in matches.items():
            if not match.success:
                continue
            src_code = hierarchy_keys.get(f"{level}_code", "").strip()
            if src_code and match.code and src_code != match.code:
                issues.append(
                    f"Parent/child check: source {level} code '{src_code}' "
                    f"differs from matched '{match.code}'"
                )
        return issues

    def _cell(self, row: pd.Series, col: Optional[str]) -> str:
        if not col or col not in row.index:
            return ""
        val = row[col]
        if pd.isna(val):
            return ""
        return str(val).strip()

    def _empty_record(
        self,
        errors: List[str],
        warnings: List[str],
        ambiguous_level: str = "",
        match_count: int = 0,
    ) -> HierarchyRecord:
        matches = {}
        for level in HIERARCHY_LEVELS:
            matches[level] = HierarchyMatch(
                success=False,
                level=level,
                error=errors[0] if errors else "Hierarchy not resolved",
                is_ambiguous=bool(ambiguous_level),
                match_count=match_count,
            )
        return HierarchyRecord(matches=matches, errors=errors, warnings=warnings)

    def get_available_levels(self) -> List[str]:
        return self._available_levels.copy()

    def get_duplicate_report(self) -> Dict[str, List[str]]:
        return self._duplicates.copy()

    def validate_hierarchy_columns(self) -> List[str]:
        warnings = []
        required_with_id = ["zone", "circle", "division", "subdivision"]
        for level in required_with_id:
            if level not in self._available_levels:
                warnings.append(f"Hierarchy level '{level}' not detected in report")
            elif "id" not in self._column_map.get(level, {}):
                warnings.append(
                    f"Hierarchy level '{level}' found but UUID/ID column not detected"
                )
        return warnings
