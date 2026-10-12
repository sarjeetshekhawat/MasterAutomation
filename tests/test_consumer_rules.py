import pytest

from master_update_automation.consumer_rules import (
    apply_consumer_identification_rules,
    apply_meter_make_rules,
)
from master_update_automation.config import OPERATIONS
from tests.conftest import ESC_ID, GENUS_HTCT, GENUS_LTCT, GENUS_WC, LEC_ID, NSC_ID, TOD_ID, operation


def _ident(ref_lookup, src, dst, value):
    result, rule = apply_consumer_identification_rules(operation(src, dst), value, ref_lookup)
    return result, rule


@pytest.mark.parametrize("op_id", list(range(1, 10)))
def test_all_nine_operations_resolve_identification(ref_lookup, op_id):
    op = OPERATIONS[op_id]
    ident = "ESC"
    result, _ = apply_consumer_identification_rules(op, ident, ref_lookup)
    assert result.success
    if op.source.value == "WC" and op.destination.value in {"HTCT", "LTCT"}:
        assert result.uuid == f"{{{TOD_ID}}}"
    else:
        assert result.uuid == f"{{{ESC_ID}}}"


def test_rule_a_wc_to_htct_esc_becomes_tod(ref_lookup):
    result, rule = _ident(ref_lookup, "WC", "HTCT", "ESC")
    assert "Rule A" in rule
    assert result.uuid == f"{{{TOD_ID}}}"
    assert TOD_ID in result.uuid
    assert ESC_ID not in result.uuid


def test_rule_a_wc_to_ltct_esc_becomes_tod(ref_lookup):
    result, rule = _ident(ref_lookup, "WC", "LTCT", "ESC")
    assert "Rule A" in rule
    assert result.uuid == f"{{{TOD_ID}}}"


def test_rule_a_not_applied_when_not_esc(ref_lookup):
    result, rule = _ident(ref_lookup, "WC", "HTCT", "NSC")
    assert "Rule A" not in rule
    assert result.uuid == f"{{{NSC_ID}}}"


def test_rule_b_htct_to_wc_uses_source_ident(ref_lookup):
    result, rule = _ident(ref_lookup, "HTCT", "WC", "LEC")
    assert "Rule B" in rule
    assert result.uuid == f"{{{LEC_ID}}}"


def test_rule_b_ltct_to_wc_uses_source_ident(ref_lookup):
    result, rule = _ident(ref_lookup, "LTCT", "WC", "NSC")
    assert "Rule B" in rule
    assert result.uuid == f"{{{NSC_ID}}}"
    assert result.uuid != f"{{{TOD_ID}}}"


def test_same_category_does_not_apply_esc_to_tod(ref_lookup):
    result, rule = _ident(ref_lookup, "WC", "WC", "ESC")
    assert "Rule C" in rule
    assert result.uuid == f"{{{ESC_ID}}}"


def test_ltct_to_htct_standard_lookup(ref_lookup):
    result, rule = _ident(ref_lookup, "LTCT", "HTCT", "ESC")
    assert "Rule D" in rule
    assert result.uuid == f"{{{ESC_ID}}}"


def test_htct_to_ltct_standard_lookup(ref_lookup):
    result, rule = _ident(ref_lookup, "HTCT", "LTCT", "TOD")
    assert result.uuid == f"{{{TOD_ID}}}"


def test_meter_make_uses_destination_category(ref_lookup):
    htct, _ = apply_meter_make_rules(operation("WC", "HTCT"), "Genus", ref_lookup)
    ltct, _ = apply_meter_make_rules(operation("HTCT", "LTCT"), "Genus", ref_lookup)
    wc, _ = apply_meter_make_rules(operation("HTCT", "WC"), "Genus", ref_lookup)
    assert htct.uuid == f"{{{GENUS_HTCT}}}"
    assert ltct.uuid == f"{{{GENUS_LTCT}}}"
    assert wc.uuid == f"{{{GENUS_WC}}}"
    assert htct.uuid != ltct.uuid != wc.uuid
