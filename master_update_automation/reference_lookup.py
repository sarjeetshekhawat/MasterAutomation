"""Resolve business values to UUIDs from ref_project_masters_lov."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .config import (
    Category,
    METER_MAKE_REFERENCE,
    REFERENCE_CATEGORY_ALIASES,
    REFERENCE_CATEGORY_MAP,
    REFERENCE_SHEET_NAME,
)
from .uuid_utils import normalise_uuid

logger = logging.getLogger(__name__)


@dataclass
class ReferenceEntry:
    id: str
    name: str
    code: str
    master_name: str


@dataclass
class LookupResult:
    success: bool
    uuid: str = ""
    name: str = ""
    error: str = ""
    category: str = ""
    search_value: str = ""
    is_ambiguous: bool = False


class ReferenceLookup:
    def __init__(self) -> None:
        self._entries: List[ReferenceEntry] = []
        self._by_category: Dict[str, List[ReferenceEntry]] = {}
        self._by_name: Dict[Tuple[str, str], List[ReferenceEntry]] = {}
        self._by_code: Dict[Tuple[str, str], List[ReferenceEntry]] = {}
        self._duplicate_keys: List[str] = []

    def load_from_workbook(self, wb) -> None:
        if REFERENCE_SHEET_NAME not in wb.sheetnames:
            raise ValueError(
                f"Reference sheet '{REFERENCE_SHEET_NAME}' not found in workbook. "
                f"Available sheets: {wb.sheetnames}"
            )
        ws = wb[REFERENCE_SHEET_NAME]
        rows = []
        headers = [c.value for c in next(ws.iter_rows(max_row=1))]
        col_index = {
            str(h).strip().lower(): i
            for i, h in enumerate(headers) if h
        }
        id_i = col_index.get("id", 0)
        name_i = col_index.get("name", 1)
        code_i = col_index.get("code", 2)
        master_i = col_index.get("master_name", 3)
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row is None:
                continue
            values = list(row)
            def _cell(i: int) -> str:
                if i >= len(values) or values[i] is None:
                    return ""
                return str(values[i]).strip()
            rows.append({
                "id": _cell(id_i),
                "name": _cell(name_i),
                "code": _cell(code_i),
                "master_name": _cell(master_i),
            })
        self._load_rows(rows)

    def load_from_dataframe(self, df: pd.DataFrame) -> None:
        rows = []
        for _, row in df.iterrows():
            rows.append({
                "id": str(row.get("id", "") or "").strip(),
                "name": str(row.get("name", "") or "").strip(),
                "code": str(row.get("code", "") or "").strip(),
                "master_name": str(row.get("master_name", "") or "").strip(),
            })
        self._load_rows(rows)

    def _load_rows(self, rows: List[dict]) -> None:
        self._entries.clear()
        self._by_category.clear()
        self._by_name.clear()
        self._by_code.clear()
        self._duplicate_keys.clear()

        for row in rows:
            entry_id = row.get("id", "")
            master_name = row.get("master_name", "")
            if not master_name or not entry_id:
                continue
            entry = ReferenceEntry(
                id=entry_id,
                name=row.get("name", ""),
                code=row.get("code", ""),
                master_name=master_name,
            )
            self._entries.append(entry)
            cat_key = entry.master_name.upper()
            self._by_category.setdefault(cat_key, []).append(entry)
            if entry.name:
                self._by_name.setdefault((cat_key, entry.name.upper()), []).append(entry)
            if entry.code:
                for cp in [c.strip().upper() for c in entry.code.split(",")]:
                    if cp:
                        self._by_code.setdefault((cat_key, cp), []).append(entry)

        for key, entries in self._by_name.items():
            ids = {e.id.lower() for e in entries}
            if len(ids) > 1:
                self._duplicate_keys.append(f"{key[0]} / name '{key[1]}'")
        for key, entries in self._by_code.items():
            ids = {e.id.lower() for e in entries}
            if len(ids) > 1:
                self._duplicate_keys.append(f"{key[0]} / code '{key[1]}'")

        logger.info(
            "Loaded %s reference entries across %s categories",
            len(self._entries),
            len(self._by_category),
        )

    def get_categories(self) -> List[str]:
        return sorted(self._by_category.keys())

    def get_duplicate_report(self) -> List[str]:
        return list(self._duplicate_keys)

    def get_entries_for_category(self, category: str) -> List[ReferenceEntry]:
        return self._by_category.get(category.upper(), [])

    def _unique_entry(self, entries: List[ReferenceEntry], category: str, value: str) -> LookupResult:
        ids = {e.id.lower() for e in entries}
        if len(ids) > 1:
            return LookupResult(
                success=False,
                is_ambiguous=True,
                error=(
                    f"Ambiguous reference for '{value}' in category '{category}': "
                    f"{len(ids)} distinct UUIDs"
                ),
                category=category,
                search_value=value,
            )
        entry = entries[0]
        return LookupResult(
            success=True,
            uuid=normalise_uuid(entry.id),
            name=entry.name,
            category=category,
            search_value=value,
        )

    def lookup_by_name(self, category: str, name: str) -> LookupResult:
        if not name or not category:
            return LookupResult(
                success=False,
                error=f"Empty lookup: category='{category}', name='{name}'",
                category=category,
                search_value=name or "",
            )
        cat_upper = category.upper()
        name_upper = str(name).strip().upper()
        categories_to_try = [cat_upper]
        for alias in REFERENCE_CATEGORY_ALIASES.get(cat_upper, []):
            categories_to_try.append(alias.upper())

        for cat in categories_to_try:
            name_entries = self._by_name.get((cat, name_upper), [])
            if name_entries:
                return self._unique_entry(name_entries, category, name)
            code_entries = self._by_code.get((cat, name_upper), [])
            if code_entries:
                return self._unique_entry(code_entries, category, name)

        return LookupResult(
            success=False,
            error=f"Value '{name}' not found in category '{category}'",
            category=category,
            search_value=name,
        )

    def lookup_by_code(self, category: str, code: str) -> LookupResult:
        if not code or not category:
            return LookupResult(
                success=False,
                error=f"Empty lookup: category='{category}', code='{code}'",
                category=category,
                search_value=code or "",
            )
        cat_upper = category.upper()
        code_upper = str(code).strip().upper()
        entries = self._by_code.get((cat_upper, code_upper), [])
        if entries:
            return self._unique_entry(entries, category, code)
        return LookupResult(
            success=False,
            error=f"Code '{code}' not found in category '{category}'",
            category=category,
            search_value=code,
        )

    def lookup_meter_make(self, dest_category: Category, meter_make_name: str) -> LookupResult:
        ref_category = METER_MAKE_REFERENCE.get(dest_category)
        if not ref_category:
            return LookupResult(
                success=False,
                error=f"No meter make reference defined for category '{dest_category.value}'",
                category="METER MAKE",
                search_value=meter_make_name,
            )
        return self.lookup_by_name(ref_category, meter_make_name)

    def lookup_for_target_field(
        self,
        target_field: str,
        value: str,
        dest_category: Optional[Category] = None,
    ) -> LookupResult:
        target_lower = target_field.lower().strip()
        if target_lower == "meter_make":
            if dest_category is None:
                return LookupResult(
                    success=False,
                    error="Destination category required for meter_make lookup",
                    category="METER MAKE",
                    search_value=value,
                )
            return self.lookup_meter_make(dest_category, value)
        ref_category = REFERENCE_CATEGORY_MAP.get(target_lower)
        if not ref_category:
            return LookupResult(
                success=False,
                error=f"No reference category configured for field '{target_field}'",
                category="",
                search_value=value,
            )
        return self.lookup_by_name(ref_category, value)

    def category_exists(self, category: str) -> bool:
        if category.upper() in self._by_category:
            return True
        for alias in REFERENCE_CATEGORY_ALIASES.get(category.upper(), []):
            if alias.upper() in self._by_category:
                return True
        return False

    def validate_categories(self, required_categories: List[str]) -> List[str]:
        return [cat for cat in required_categories if not self.category_exists(cat)]
