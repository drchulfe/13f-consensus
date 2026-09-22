from pathlib import Path

from radar.edgar import aggregate, detect_thousands, parse_info_table, parse_primary_doc, pick_files, sanity

FX = Path(__file__).parent / "fixtures"


def test_parse_info_table_reads_all_rows():
    rows = parse_info_table((FX / "infotable.xml").read_bytes())
    assert len(rows) == 5
    assert rows[0] == {"name": "APPLE INC", "cls": "COM", "cusip": "037833100", "value": 2000000.0,
                       "shares": 10000.0, "sh_type": "SH", "put_call": ""}
    assert rows[2]["put_call"] == "Put" and rows[3]["sh_type"] == "PRN"


def test_aggregate_sums_cusip_and_drops_options_and_prn():
    agg = aggregate(parse_info_table((FX / "infotable.xml").read_bytes()))
    assert set(agg) == {"037833100", "191216100"}
    assert agg["037833100"]["value"] == 3000000.0 and agg["037833100"]["shares"] == 15000.0


def test_parse_primary_doc_totals_and_amendment():
    m = parse_primary_doc((FX / "primary_doc.xml").read_bytes())
    assert m["table_total"] == 4000000.0 and m["entry_total"] == 5 and m["amendment_type"] == ""
    assert parse_primary_doc((FX / "primary_doc_amend.xml").read_bytes())["amendment_type"] == "NEW HOLDINGS"


def test_parse_primary_doc_nt_other_managers():
    m = parse_primary_doc((FX / "primary_doc_nt.xml").read_bytes())
    assert m["report_type"] == "13F NOTICE"
    assert m["other_managers"] == [{"cik": "0002026053", "name": "PERSHING SQUARE INC."}]
    assert m["table_total"] == 0.0 and m["entry_total"] == 0


def test_detect_thousands_by_implied_price():
    dollars = {"a": {"value": 20000.0, "shares": 100}, "b": {"value": 650.0, "shares": 10}, "c": {"value": 30.0, "shares": 1}}
    thousands = {k: {**v, "value": v["value"] / 1000} for k, v in dollars.items()}
    assert detect_thousands(dollars, "2020-01-01") is False        # 제출일 규칙과 달라도 가격으로 판정
    assert detect_thousands(thousands, "2024-01-01") is True
    assert detect_thousands({"a": dollars["a"]}, "2020-01-01") is True   # 표본 부족 → 제출일 규칙


def test_sanity_flags_total_and_count():
    rows = parse_info_table((FX / "infotable.xml").read_bytes())
    ok = sanity(rows, {"table_total": 4000000.0, "entry_total": 5})
    assert ok["total_ok"] and ok["count_ok"] and ok["rows"] == 5
    bad = sanity(rows, {"table_total": 4000.0, "entry_total": 4})
    assert not bad["total_ok"] and not bad["count_ok"]


def test_pick_files_prefers_named_then_largest():
    items = [{"name": "primary_doc.xml", "size": "5555"}, {"name": "56757.xml", "size": "44724"},
             {"name": "0001-index.html", "size": ""}]
    assert pick_files(items) == ("primary_doc.xml", "56757.xml")
    assert pick_files(items + [{"name": "form13fInfoTable.xml", "size": "100"}]) == ("primary_doc.xml", "form13fInfoTable.xml")
    assert pick_files([{"name": "primary_doc.xml", "size": "1"}]) == ("primary_doc.xml", None)
