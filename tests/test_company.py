import json

from radar.company import describe, load_industry, load_ko


def test_load_ko_drops_note_keys(tmp_path):
    p = tmp_path / "ko.json"
    p.write_text(json.dumps({"_note": "설명", "AAPL": "아이폰 회사"}), encoding="utf-8")
    assert load_ko(p) == {"AAPL": "아이폰 회사"}


def test_load_industry_returns_both_maps(tmp_path):
    p = tmp_path / "ind.json"
    p.write_text(json.dumps({"sector": {"Technology": "기술"}, "industry": {"Semiconductors": "반도체"}}), encoding="utf-8")
    sec, ind = load_industry(p)
    assert sec["Technology"] == "기술" and ind["Semiconductors"] == "반도체"


def test_describe_prefers_korean_line_and_falls_back_to_sector():
    info = {"sector": "Technology", "industry": "Semiconductors",
            "summary": "Acme Inc. designs chips. It also sells software for fabs."}
    sec_ko, ind_ko = {"Technology": "기술"}, {"Semiconductors": "반도체"}
    a = describe("ACME", info, {"ACME": "칩 설계 회사"}, sec_ko, ind_ko)
    assert a == {"ko": "칩 설계 회사", "sec": "기술", "ind": "반도체", "en": "Acme Inc. designs chips."}
    b = describe("OTHER", info, {}, sec_ko, ind_ko)
    assert b["ko"] is None and b["sec"] == "기술" and b["ind"] == "반도체"
    assert describe("X", {"sector": "Unmapped", "industry": None, "summary": ""}, {}, sec_ko, ind_ko) == {
        "ko": None, "sec": "Unmapped", "ind": None, "en": None}
    assert describe("X", None, {}, sec_ko, ind_ko) is None
