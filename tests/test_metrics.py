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


def test_implied_price_ignores_sold():
    s = {"actions": [{"sh": 10, "v": 1000}, {"sh": 30, "v": 3000}, {"sh": 0, "v": 0}]}
    assert implied_price(s) == 100.0
    assert implied_price({"actions": [{"sh": 0, "v": 0}]}) is None
