"""Operation-specific consumer identification and meter-make rules."""

from __future__ import annotations

import logging
from typing import Tuple

from .config import Category, METER_MAKE_REFERENCE, Operation
from .reference_lookup import LookupResult, ReferenceLookup

logger = logging.getLogger(__name__)


def apply_consumer_identification_rules(
    operation: Operation,
    source_consumer_identification: str,
    ref_lookup: ReferenceLookup,
) -> Tuple[LookupResult, str]:
    """
    Rule A: WC → HTCT/LTCT with ESC → TOD UUID
    Rule B: LTCT/HTCT → WC → source identification UUID
    Rule C: same-category → standard lookup
    Rule D: LTCT ↔ HTCT → standard lookup
    """
    src = operation.source
    dst = operation.destination
    src_ident = (
        str(source_consumer_identification).strip().upper()
        if source_consumer_identification
        else ""
    )

    if (
        src == Category.WC
        and dst in (Category.HTCT, Category.LTCT)
        and src_ident == "ESC"
    ):
        logger.info("Rule A: WC → %s, ESC → TOD", dst.value)
        result = ref_lookup.lookup_by_name("CONSUMER IDENTIFICATION", "TOD")
        return result, f"Rule A: ESC → TOD (WC → {dst.value})"

    if src in (Category.HTCT, Category.LTCT) and dst == Category.WC:
        logger.info("Rule B: %s → WC, using '%s'", src.value, src_ident)
        result = ref_lookup.lookup_by_name("CONSUMER IDENTIFICATION", src_ident)
        return result, f"Rule B: Use source identification '{src_ident}' ({src.value} → WC)"

    if operation.is_same_category:
        logger.info("Rule C: %s → %s lookup '%s'", src.value, dst.value, src_ident)
        result = ref_lookup.lookup_by_name("CONSUMER IDENTIFICATION", src_ident)
        return result, f"Rule C: Standard lookup '{src_ident}' ({src.value} → {dst.value})"

    if src in (Category.LTCT, Category.HTCT) and dst in (Category.LTCT, Category.HTCT):
        logger.info("Rule D: %s → %s lookup '%s'", src.value, dst.value, src_ident)
        result = ref_lookup.lookup_by_name("CONSUMER IDENTIFICATION", src_ident)
        return result, f"Rule D: Standard lookup '{src_ident}' ({src.value} → {dst.value})"

    if src == Category.WC and dst in (Category.HTCT, Category.LTCT):
        result = ref_lookup.lookup_by_name("CONSUMER IDENTIFICATION", src_ident)
        return result, f"Standard lookup '{src_ident}' (WC → {dst.value}, not ESC)"

    result = ref_lookup.lookup_by_name("CONSUMER IDENTIFICATION", src_ident)
    return result, f"Default lookup '{src_ident}'"


def apply_meter_make_rules(
    operation: Operation,
    source_meter_make: str,
    ref_lookup: ReferenceLookup,
) -> Tuple[LookupResult, str]:
    dst = operation.destination
    make_name = str(source_meter_make).strip() if source_meter_make else ""
    if not make_name:
        return LookupResult(
            success=False,
            error="Empty meter make value",
            category=METER_MAKE_REFERENCE.get(dst, ""),
            search_value="",
        ), "Empty meter make"
    result = ref_lookup.lookup_meter_make(dst, make_name)
    return result, f"Meter make lookup in {dst.value} category for '{make_name}'"


def apply_metering_mode_rules(
    operation: Operation,
    source_metering_mode: str,
    ref_lookup: ReferenceLookup,
) -> Tuple[LookupResult, str]:
    mode = str(source_metering_mode).strip() if source_metering_mode else ""
    if not mode:
        return LookupResult(
            success=True,
            uuid="",
            category="METERING MODE",
            search_value="",
        ), "Empty metering mode (allowed)"
    result = ref_lookup.lookup_by_name("METERING MODE", mode)
    return result, f"Metering mode lookup for '{mode}'"
