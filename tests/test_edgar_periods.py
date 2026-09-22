import datetime as dt
from pathlib import Path

from fakes import PRIMARY, FakeSec, add_filing, info_xml, subs_json
from radar import edgar
from radar.edgar import cik_periods, investor_periods, investor_status, merge_periods, normalize_investor

FX = Path(__file__).parent / "fixtures"


def H(**kw):
    return {k: {"name": k, "cls": "COM", "value": v[0], "shares": v[1]} for k, v in kw.items()}


def test_cik_periods_restatement_keeps_dates_and_new_holdings_merge():
    fl = [{"acc": "a1", "form": "13F-HR", "filed": "2026-05-15", "period": "2026-03-31"},
          {"acc": "a2", "form": "13F-HR/A", "filed": "2026-08-01", "period": "2026-03-31"},
          {"acc": "a3", "form": "13F-HR/A", "filed": "2027-01-10", "period": "2026-03-31"}]
    docs = {"a1": {"holdings": H(AAA=(2000.0, 10), BBB=(5000.0, 50), CCC=(3000.0, 30)), "amendment_type": ""},
            "a2": {"holdings": H(DDD=(1000.0, 10), EEE=(400.0, 4), FFF=(900.0, 9)), "amendment_type": "NEW HOLDINGS"},
            "a3": {"holdings": H(AAA=(2000.0, 10), BBB=(6000.0, 60), CCC=(3000.0, 30), DDD=(1000.0, 10)),
                   "amendment_type": "RESTATEMENT"}}
    P = cik_periods(fl, lambda f: docs[f["acc"]], "0000000001")["2026-03-31"]
    assert P["filed"] == "2026-05-15" and P["last_filed"] == "2027-01-10" and P["accs"] == ["a1", "a2", "a3"]
    h = P["holdings"]
    assert h["AAA"]["f"] == "2026-05-15"            # 주식수 같음 → 원공시일 유지
    assert h["DDD"]["f"] == "2026-08-01"            # NEW HOLDINGS 공개일 유지
    assert h["BBB"]["f"] == "2027-01-10" and h["BBB"]["shares"] == 60
    assert "EEE" not in h and P["cik"] == "0000000001"


def test_cik_periods_converts_thousands():
    fl = [{"acc": "b1", "form": "13F-HR", "filed": "2020-02-14", "period": "2019-12-31"}]
    doc = {"holdings": H(A=(20.0, 100), B=(0.65, 10), C=(0.03, 1)), "amendment_type": ""}
    P = cik_periods(fl, lambda f: doc, "C")["2019-12-31"]
    assert P["holdings"]["A"]["value"] == 20000.0 and P["aum"] == 20000.0 + 650.0 + 30.0


def test_merge_periods_prefers_largest_aum():
    a = {"2026-03-31": {"aum": 100, "cik": "A"}, "2025-12-31": {"aum": 50, "cik": "A"}}
    b = {"2026-03-31": {"aum": 300, "cik": "B"}, "2026-06-30": {"aum": 310, "cik": "B"}}
    m = merge_periods({"A": a, "B": b})
    assert (m["2026-03-31"]["cik"], m["2025-12-31"]["cik"], m["2026-06-30"]["cik"]) == ("B", "A", "B")


def test_investor_periods_follows_13f_nt_to_parent(tmp_path, monkeypatch):
    monkeypatch.setattr(edgar, "CACHE", tmp_path)
    old, new = "0001336528", "0002026053"
    routes = {
        f"https://data.sec.gov/submissions/CIK{old}.json": subs_json("Pershing Square Capital Management, L.P.", [
            ("0000000001-26-000002", "13F-NT", "2026-08-14", "2026-06-30"),
            ("0000000001-26-000001", "13F-HR", "2026-05-15", "2026-03-31")]),
        f"https://data.sec.gov/submissions/CIK{new}.json": subs_json("PERSHING SQUARE INC.", [
            ("0000000002-26-000002", "13F-HR", "2026-08-14", "2026-06-30")])}
    rows3 = [("111111111", "AAA", 2000, 10), ("222222222", "BBB", 3000, 30), ("333333333", "CCC", 500, 5)]
    add_filing(routes, old, "0000000001-26-000001", PRIMARY, info_xml(rows3))
    add_filing(routes, old, "0000000001-26-000002", (FX / "primary_doc_nt.xml").read_bytes())
    add_filing(routes, new, "0000000002-26-000002", PRIMARY, info_xml([("111111111", "AAA", 4000, 20)] + rows3[1:]))
    r = investor_periods(FakeSec(routes), {"id": "ackman", "ciks": [old], "expect": ["PERSHING"]})
    assert set(r["periods"]) == {"2026-03-31", "2026-06-30"}
    assert r["periods"]["2026-06-30"]["cik"] == new and r["followed"] == [new]
    assert set(r["subs"]) == {old, new} and r["san"]["n"] == 2
    assert (tmp_path / "0000000001-26-000001.json").exists()      # 캐시 저장


def test_investor_periods_rejects_name_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(edgar, "CACHE", tmp_path)
    routes = {"https://data.sec.gov/submissions/CIK0000000009.json": subs_json("SOMEONE ELSE LLC", [])}
    r = investor_periods(FakeSec(routes), {"id": "x", "ciks": ["9"], "expect": ["PERSHING"]})
    assert r["periods"] == {} and r["bad"] == ["0000000009"]


def test_investor_status():
    today = dt.date(2026, 9, 23)
    assert investor_status({"2026-06-30": {}}, today) == "ok"
    assert investor_status({"2026-03-31": {}}, today) == "ok"
    assert investor_status({"2025-09-30": {}}, today) == "inactive"
    assert investor_status({}, today) == "no_filings"


def test_normalize_investor_accepts_legacy_fields():
    n = normalize_investor({"id": "b", "cik": "1067983", "expect": "BERKSHIRE"})
    assert n["ciks"] == ["0001067983"] and n["expect"] == ["BERKSHIRE"]
