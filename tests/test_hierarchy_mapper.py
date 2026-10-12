from master_update_automation.hierarchy_mapper import HierarchyMapper
from tests.conftest import DT_ID


def test_unique_dt_code_match(hierarchy_df):
    mapper = HierarchyMapper()
    mapper.load_hierarchy(hierarchy_df)
    rec = mapper.match_consumer({}, {"dt_code": "1085140006"})
    assert rec.matches["dt"].success
    assert rec.matches["dt"].uuid == f"{{{DT_ID}}}"
    assert rec.matches["subdivision"].success


def test_missing_hierarchy_match(hierarchy_df):
    mapper = HierarchyMapper()
    mapper.load_hierarchy(hierarchy_df)
    rec = mapper.match_consumer({}, {"dt_code": "DOES-NOT-EXIST"})
    assert not rec.matches["dt"].success
    assert rec.errors or not rec.matches["dt"].success


def test_ambiguous_hierarchy_match_not_guessed(hierarchy_df):
    mapper = HierarchyMapper()
    mapper.load_hierarchy(hierarchy_df)
    rec = mapper.match_consumer({}, {"dt_code": "DUPCODE"})
    assert rec.matches["dt"].is_ambiguous or any("Ambiguous" in e for e in rec.errors)
    assert not rec.matches["dt"].success
    assert rec.matches["dt"].uuid == ""
