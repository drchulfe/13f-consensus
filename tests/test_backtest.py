import datetime as dt

import numpy as np
import pandas as pd

from radar.backtest import forward_returns, make_events, permille, run_backtest
from radar.config import OFFSETS


def test_make_events_requires_buyer_and_two_holders():
    periods = {"2026-03-31": {"stocks": [
        {"cusip": "A", "split": None, "actions": [
            {"inv": "buffett", "t": "new", "sh": 10, "psh": 0, "v": 1000, "f": "2026-05-15"},
            {"inv": "gates", "t": "hold", "sh": 30, "psh": 30, "v": 3000, "f": "2026-05-10"}]},
        {"cusip": "B", "split": None, "actions": [{"inv": "buffett", "t": "add", "sh": 10, "psh": 5, "v": 1000, "f": "2026-05-15"}]},
        {"cusip": "C", "split": 2, "actions": [
            {"inv": "buffett", "t": "hold", "sh": 10, "psh": 5, "v": 1000, "f": "2026-05-15"},
            {"inv": "gates", "t": "hold", "sh": 10, "psh": 5, "v": 1000, "f": "2026-05-15"}]}]}}
    ev = make_events(periods, {"A": "AAA"})
    assert len(ev) == 1
    e = ev[0]
    assert (e["tk"], e["e"], e["hn"], e["b"], e["imp"]) == ("AAA", "2026-05-15", 2, [["buffett", "n"]], 100.0)


def _frame(cal, px):
    return pd.DataFrame({"Adj Close": px, "Close": px, "Volume": 1.0, "Stock Splits": 0.0}, index=cal)


def test_forward_returns_next_day_entry_and_validation():
    cal = pd.bdate_range("2026-03-02", periods=400)
    spy = pd.Series(np.linspace(100, 140, len(cal)), index=cal)
    px = np.linspace(10, 30, len(cal))
    good = _frame(cal, px)
    imp = float(good.loc["2026-03-31", "Close"])
    e_ok = {"p": "2026-03-31", "tk": "AAA", "e": "2026-05-15", "imp": imp}
    e_bad = {"p": "2026-03-31", "tk": "BBB", "e": "2026-05-15", "imp": 999.0}
    e_none = {"p": "2026-03-31", "tk": "CCC", "e": "2026-05-15", "imp": 10.0}
    spy_rows = forward_returns([e_ok, e_bad, e_none], iter([{"AAA": good, "BBB": good}]), spy)
    assert (e_ok["st"], e_bad["st"], e_none["st"]) == ("ok", "mismatch", "nopx")
    i0, j = int(cal.searchsorted(pd.Timestamp("2026-05-15"), side="right")), OFFSETS.index(21)
    assert e_ok["R"][0] == 0.0 and e_ok["R"][j] == round(px[i0 + 21] / px[i0] - 1, 3)
    assert spy_rows[e_ok["si"]][j] == round(spy.iloc[i0 + 21] / spy.iloc[i0] - 1, 3)
    assert e_ok["R"][OFFSETS.index(1260)] is None


def test_forward_returns_skips_zero_entry_price():
    cal = pd.bdate_range("2026-03-02", periods=300)
    spy = pd.Series(np.linspace(100, 140, len(cal)), index=cal)
    px = np.linspace(10, 30, len(cal))
    px[int(cal.searchsorted(pd.Timestamp("2026-05-15"), side="right"))] = 0.0     # 진입일 가격 0
    fr = _frame(cal, px)
    e = {"p": "2026-03-31", "tk": "AAA", "e": "2026-05-15", "imp": float(fr.loc["2026-03-31", "Close"])}
    forward_returns([e], iter([{"AAA": fr}]), spy)
    assert e["st"] == "nopx" and e["R"] is None


def test_permille_trims_trailing_nulls():
    assert permille([0.0, 0.1234, None, -0.05, None, None]) == [0, 123, None, -50]


def test_run_backtest_compact_encoding(tmp_path):
    cal = pd.bdate_range("2026-03-02", periods=400)
    fr = _frame(cal, np.linspace(10, 30, len(cal)))
    v = float(fr.loc["2026-03-31", "Close"]) * 10
    periods = {"2026-03-31": {"stocks": [{"cusip": "A", "split": None, "actions": [
        {"inv": "buffett", "t": "new", "sh": 10, "psh": 0, "v": v, "f": "2026-05-15"},
        {"inv": "gates", "t": "hold", "sh": 10, "psh": 10, "v": v, "f": "2026-05-10"}]}]}}

    def dl(tickers, start):
        yield {t: fr for t in tickers}

    bt = run_backtest(periods, {"A": "AAA"}, dl, dt.date(2026, 9, 23), ["buffett", "gates"], full=True,
                      bt_file=tmp_path / "bt.json")
    assert bt["P"] == ["2026-03-31"] and bt["I"] == ["buffett", "gates"]
    e = bt["ev"][0]
    assert e[:4] == [0, "AAA", [1], 2] and e[4][0] == 0 and e[5] == 0
    assert bt["stats"] == {"total": 1, "nopx": 0, "mismatch": 0, "split": 0, "used": 1}
    assert (tmp_path / "bt.json").exists()
