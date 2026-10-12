"""Processing logs and downloadable audit/error reports."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List

import pandas as pd

from .config import AuditStatus

logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    source_row: int
    business_key: str
    operation: str
    status: str
    action: str = ""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    transformations: List[str] = field(default_factory=list)
    failed_lookups: List[str] = field(default_factory=list)
    hierarchy_status: str = ""

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


class AuditLogger:
    def __init__(self, operation_label: str) -> None:
        self.operation_label = operation_label
        self.entries: List[AuditEntry] = []
        self._start_time = datetime.now()

    def add_entry(self, entry: AuditEntry) -> None:
        self.entries.append(entry)

    def create_entry(
        self,
        source_row: int,
        business_key: str,
        status: AuditStatus,
        action: str = "",
    ) -> AuditEntry:
        entry = AuditEntry(
            source_row=source_row,
            business_key=business_key,
            operation=self.operation_label,
            status=status.value,
            action=action,
        )
        self.entries.append(entry)
        return entry

    @property
    def total_records(self) -> int:
        return len(self.entries)

    @property
    def success_count(self) -> int:
        return sum(
            1 for e in self.entries
            if e.status in (
                AuditStatus.SUCCESS.value,
                AuditStatus.INSERTED.value,
                AuditStatus.UPDATED.value,
            )
        )

    @property
    def warning_count(self) -> int:
        return sum(1 for e in self.entries if e.status == AuditStatus.WARNING.value)

    @property
    def failed_count(self) -> int:
        return sum(1 for e in self.entries if e.status == AuditStatus.FAILED.value)

    @property
    def review_count(self) -> int:
        return sum(1 for e in self.entries if e.status == AuditStatus.REQUIRES_REVIEW.value)

    def get_summary(self) -> Dict:
        status_counts: Dict[str, int] = {}
        for entry in self.entries:
            status_counts[entry.status] = status_counts.get(entry.status, 0) + 1
        return {
            "total_records": self.total_records,
            "successful": self.success_count,
            "warnings": self.warning_count,
            "failed": self.failed_count,
            "requires_review": self.review_count,
            "status_breakdown": status_counts,
        }

    def to_dataframe(self) -> pd.DataFrame:
        records = []
        for entry in self.entries:
            records.append({
                "Source Row": entry.source_row,
                "Business Key": entry.business_key,
                "Operation": entry.operation,
                "Status": entry.status,
                "Action": entry.action,
                "Errors": "; ".join(entry.errors) if entry.errors else "",
                "Warnings": "; ".join(entry.warnings) if entry.warnings else "",
                "Transformations": "; ".join(entry.transformations) if entry.transformations else "",
                "Failed Lookups": "; ".join(entry.failed_lookups) if entry.failed_lookups else "",
                "Hierarchy Status": entry.hierarchy_status,
            })
        return pd.DataFrame(records)

    def export_csv(self, filepath: str) -> str:
        df = self.to_dataframe()
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        logger.info("Audit report exported to: %s", filepath)
        return filepath

    def export_excel(self, filepath: str) -> str:
        df = self.to_dataframe()
        df.to_excel(filepath, index=False, engine="openpyxl")
        logger.info("Audit report exported to: %s", filepath)
        return filepath

    def get_error_report(self) -> pd.DataFrame:
        df = self.to_dataframe()
        if df.empty:
            return df
        return df[df["Status"].isin([
            AuditStatus.FAILED.value,
            AuditStatus.REQUIRES_REVIEW.value,
            AuditStatus.WARNING.value,
        ])]
