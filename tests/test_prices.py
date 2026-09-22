import datetime as dt

import numpy as np
import pandas as pd

from radar.prices import analyst_targets, download, fx_krw, had_split, raw_close_on, stock_metrics, validate


def frame(dates, close, vol=None, splits=None):
    idx = pd.to_datetime(list(dates))
    n = len(idx)
    return pd.DataFrame({"Adj Close": close, "Close": close, "Volume": vol if vol is not None else [100.0] * n,
                         "Stock Splits": splits if splits is not None else [0.0] * n}, index=idx)


def test_raw_close_reverses_later_splits():
    f = frame(["2024-06-07", "2024-06-10", "2024-06-11"], [120.888, 121.79, 120.91], splits=[0, 10.0, 0])
    assert round(raw_close_on(f, "2024-06-07"), 2) == 1208.88
    assert round(raw_close_on(f, "2024-06-09"), 2) == 1208.88      # 주말 → 직전 거래일
    assert round(raw_close_on(f, "2024-06-11"), 2) == 120.91


def test_validate_ranges():
    f = frame(["2026-06-29", "2026-06-30"], [99.0, 100.0])
    assert validate(f, "2026-06-30", 120.0) is True
    assert validate(f, "2026-06-30", 130.0) is False
    assert validate(f, "2026-06-30", None) is None
    assert validate(f, "2025-01-01", 100.0) is None                  # 해당 시점 가격 없음


def test_had_split_within_quarter():
    f = frame(["2026-03-31", "2026-05-01", "2026-07-01"], [1.0, 1.0, 1.0], splits=[0, 4.0, 0])
    assert had_split(f, "2026-06-30") is True
    assert had_split(f, "2026-09-30") is False


def test_stock_metrics_vwap_premium_and_elapsed():
    dates = pd.bdate_range("2026-01-02", "2026-09-22")
    close = np.linspace(50, 100, len(dates))
    f = frame(dates, close, vol=[1000.0] * len(dates))
    imp = float(f.loc["2026-06-30", "Close"])
    m = stock_metrics(f, "2026-08-14", "2026-06-30", imp, {"krw": 1400.0, "d": "2026-09-22"})
    q = f.loc["2026-04-01":"2026-06-30", "Close"]
    assert m["last"] == round(close[-1], 2) and m["d"] == "2026-09-22"
    assert abs(m["vwap"] - q.mean()) < 0.01 and m["qlo"] == round(q.min(), 2) and m["qhi"] == round(q.max(), 2)
    assert abs(m["prem"] - (close[-1] / q.mean() - 1)) < 1e-3
    assert m["el"] == int((dates > pd.Timestamp("2026-08-14")).sum()) - 1
    assert m["ok"] is True and m["krw"] == round(close[-1] * 1400)
    assert m["hi52"] == round(close[-1], 2) and m["vol"] is not None


def test_download_yields_per_ticker_frames():
    idx = pd.to_datetime(["2026-09-21", "2026-09-22"])
    cols = pd.MultiIndex.from_product([["AAA", "BBB"], ["Adj Close", "Close", "Dividends", "High", "Low", "Open", "Stock Splits", "Volume"]])
    df = pd.DataFrame(np.ones((2, len(cols))), index=idx, columns=cols)
    df[("BBB", "Close")] = np.nan
    chunks = list(download(["AAA", "BBB"], "2026-01-01", dl=lambda *a, **k: df, sleep=lambda s: None))
    assert list(chunks[0]) == ["AAA"]
    assert list(chunks[0]["AAA"].columns) == ["Adj Close", "Close", "Volume", "Stock Splits"]


def test_fx_krw_reads_last_close():
    idx = pd.to_datetime(["2026-09-21", "2026-09-22"])
    df = pd.DataFrame({("KRW=X", "Close"): [1384.86, 1358.88]}, index=idx)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    assert fx_krw(dl=lambda *a, **k: df) == {"krw": 1358.88, "d": "2026-09-22"}
    assert fx_krw(dl=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))) is None


def test_analyst_targets_uses_7day_cache(tmp_path):
    class T:
        n = 0

        def __init__(self, t):
            T.n += 1
            self.info = {"targetMeanPrice": 80.0, "targetMedianPrice": 75.0, "numberOfAnalystOpinions": 13,
                         "recommendationKey": "hold"}

    cp, today = tmp_path / "an.json", dt.date(2026, 9, 22)
    a = analyst_targets(["LEN"], cp, today, ticker_cls=T, sleep=lambda s: None)
    assert a["LEN"]["mean"] == 80.0 and a["LEN"]["n"] == 13 and T.n == 1
    analyst_targets(["LEN"], cp, today + dt.timedelta(days=3), ticker_cls=T, sleep=lambda s: None)
    assert T.n == 1
