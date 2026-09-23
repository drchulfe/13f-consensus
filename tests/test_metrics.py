import datetime as dt

import numpy as np
import pandas as pd

from radar.metrics import display_metrics, implied_price


def test_display_metrics_fills_px_and_reverts_unconfirmed_split():
    cal = pd.bdate_range("2026-01-02", "2026-09-22")
    px = np.linspace(50, 100, len(cal))
    fr = pd.DataFrame({"Adj Close": px, "Close": px, "Volume": 1000.0, "Stock Splits": 0.0}, index=cal)
    imp = float(fr.loc["2026-06-30", "Close"])
    show = {"2026-06-30": {"filed": [], "stocks": [
        {"cusip": "A", "name": "A", "cls": "COM", "split": 2, "actions": [
            {"inv": "buffett", "t": "hold", "t0": "add", "sh": 20, "psh": 10, "v": imp * 20, "f": "2026-08-14"}]}]}}

    def dl(tickers, start):
        yield {t: fr for t in tickers}

    res = display_metrics(show, {"A": "AAA"}, dl, {"krw": 1400.0, "d": "2026-09-22"}, dt.date(2026, 9, 23),
                          extra={"LEN"}, log=lambda *a: None)
    s = show["2026-06-30"]["stocks"][0]
    assert s["split"] is None and s["actions"][0]["t"] == "add" and "t0" not in s["actions"][0]
    assert s["tk"] == "AAA" and s["px"]["ok"] is True
    assert res["price_date"] == "2026-09-22" and res["quotes"]["AAA"] == 100.0 and "LEN" in res["quotes"]


def test_display_metrics_rescales_previous_shares_on_a_real_split():
    cal = pd.bdate_range("2026-01-02", "2026-09-22")
    px = np.linspace(50, 100, len(cal))
    splits = [4.0 if d == pd.Timestamp("2026-05-01") else 0.0 for d in cal]
    fr = pd.DataFrame({"Adj Close": px, "Close": px, "Volume": 1000.0, "Stock Splits": splits}, index=cal)
    imp = float(fr.loc["2026-06-30", "Close"])
    show = {"2026-06-30": {"filed": [], "stocks": [
        {"cusip": "A", "name": "A", "cls": "COM", "split": 4, "actions": [
            {"inv": "buffett", "t": "hold", "t0": "add", "sh": 44, "psh": 10, "v": imp * 44, "f": "2026-08-14"},
            {"inv": "gates", "t": "hold", "t0": "add", "sh": 40, "psh": 10, "v": imp * 40, "f": "2026-08-14"}]}]}}

    def dl(tickers, start):
        yield {t: fr for t in tickers}

    display_metrics(show, {"A": "AAA"}, dl, None, dt.date(2026, 9, 23), log=lambda *a: None)
    s = show["2026-06-30"]["stocks"][0]
    assert s["split"] is None and s["splitk"] == 4.0
    assert [(a["t"], a["psh"]) for a in s["actions"]] == [("add", 40), ("hold", 40)]
    assert all("t0" not in a for a in s["actions"])


def test_implied_price_ignores_sold():
    s = {"actions": [{"sh": 10, "v": 1000}, {"sh": 30, "v": 3000}, {"sh": 0, "v": 0}]}
    assert implied_price(s) == 100.0
    assert implied_price({"actions": [{"sh": 0, "v": 0}]}) is None
