import datetime as dt
from pathlib import Path

from fakes import FakeSec
from radar import filings
from radar.filings import parse_form4, parse_schedule13, pick_symbol, recent_filings, summarize_form4

FX = Path(__file__).parent / "fixtures"


def test_parse_and_summarize_form4():
    d = parse_form4((FX / "form4.xml").read_bytes())
    assert d["issuer_cik"] == "0000920760" and d["symbols"] == "LEN, LEN.B" and len(d["tx"]) == 3
    s = summarize_form4(d)
    assert len(s) == 1 and s[0]["kind"] == "buy" and s[0]["sh"] == 367585
    assert abs(s[0]["px"] - (267585 * 78.41 + 100000 * 80.0) / 367585) < 1e-3
    assert s[0]["post"] == 21418186 and s[0]["date"] == "2026-09-18"
    assert pick_symbol(d["symbols"], "Class A Common Stock") == "LEN"
    assert pick_symbol(d["symbols"], "Class B Common Stock") == "LEN.B"


def test_parse_schedule13g_and_13d():
    g = parse_schedule13((FX / "schedule13g.xml").read_bytes())
    assert g == {"issuer_cik": "0000920760", "name": "LENNAR CORPORATION", "cusip": "526057104", "form": "SCHEDULE 13G",
                 "amend": "", "event": "06/30/2026", "sh": 13111741.0, "pct": 6.2}
    d = parse_schedule13((FX / "schedule13d.xml").read_bytes())
    assert (d["issuer_cik"], d["amend"], d["pct"], d["sh"]) == ("0001067983", "81", 38.2, 188290.0)


def test_recent_filings_filters_window_forms_and_self_issuer(tmp_path, monkeypatch):
    monkeypatch.setattr(filings, "CACHE", tmp_path)
    cik = "0001067983"

    def url(acc, name):
        return f"https://www.sec.gov/Archives/edgar/data/1067983/{acc.replace('-', '')}/{name}"

    routes = {url("0001-26-000010", "ownership.xml"): (FX / "form4.xml").read_bytes(),
              url("0001-26-000011", "primary_doc.xml"): (FX / "schedule13g.xml").read_bytes(),
              url("0001-26-000012", "primary_doc.xml"): (FX / "schedule13d.xml").read_bytes()}
    rows = [{"acc": "0001-26-000010", "form": "4", "filed": "2026-09-21", "period": "", "doc": "xslF345X06/ownership.xml"},
            {"acc": "0001-26-000011", "form": "SCHEDULE 13G", "filed": "2026-08-14", "period": "", "doc": "xslSCHEDULE_13G_X02/primary_doc.xml"},
            {"acc": "0001-26-000012", "form": "SCHEDULE 13D/A", "filed": "2026-07-15", "period": "", "doc": "xslSCHEDULE_13D_X02/primary_doc.xml"},
            {"acc": "0001-26-000013", "form": "4", "filed": "2026-01-02", "period": "", "doc": "x/ownership.xml"},
            {"acc": "0001-26-000014", "form": "8-K", "filed": "2026-09-01", "period": "", "doc": "d.htm"}]
    out = recent_filings(FakeSec(routes), [("buffett", cik, rows)], {"buffett": {cik}}, dt.date(2026, 9, 23))
    assert [(o["form"], o["kind"]) for o in out] == [("4", "buy"), ("SCHEDULE 13G", "stake")]
    assert out[0]["tk"] == "LEN" and out[0]["sh"] == 367585 and out[0]["val"] == round(367585 * out[0]["px"])
    assert out[1]["cusip"] == "526057104" and out[1]["pct"] == 6.2
    assert (tmp_path / "f_0001-26-000010.json").exists()
