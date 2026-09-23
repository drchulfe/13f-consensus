"""주가(yfinance): 청크 다운로드, 원시가격 복원·가격 검증, 표시 지표, 환율, 애널리스트 목표가."""
import datetime as dt
import json
import time

import numpy as np
import pandas as pd

from .dates import prev_quarter, quarter_start

FIELDS = ["Adj Close", "Close", "Volume", "Stock Splits"]


def _yf():
    import yfinance as yf
    return yf


def download(tickers, start, chunk=100, dl=None, sleep=time.sleep, log=print):
    """{티커: DataFrame(FIELDS)}를 청크마다 yield. Close=분할 반영, Adj Close=분할+배당 반영."""
    dl = dl or _yf().download
    tickers = sorted({t for t in tickers if t})
    for i in range(0, len(tickers), chunk):
        part, df = tickers[i:i + chunk], None
        for attempt in range(2):
            try:
                df = dl(part, start=start, auto_adjust=False, actions=True, group_by="ticker",
                        progress=False, threads=True)
                break
            except Exception as e:
                log(f"yfinance 실패({attempt + 1}/2): {e}")
                sleep(5)
        out = {}
        if df is not None and len(df):
            for t in part:
                try:
                    sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
                except KeyError:
                    continue
                sub = sub.reindex(columns=FIELDS)
                sub = sub[sub["Close"].notna()]
                if len(sub):
                    sub = sub.copy()
                    sub.index = pd.to_datetime(sub.index).tz_localize(None).normalize()
                    out[t] = sub.sort_index()
        yield out
        sleep(1)


def split_factor_after(frame, day):
    s = frame["Stock Splits"].fillna(0)
    s = s[(s.index > pd.Timestamp(day)) & (s > 0)]
    return float(np.prod(s.to_numpy())) if len(s) else 1.0


def raw_close_on(frame, date):
    """date 이전(포함) 마지막 거래일의 당시 원시 종가 = Close × 이후 분할 비율 곱."""
    c = frame["Close"].loc[:pd.Timestamp(date)].dropna()
    if c.empty or (pd.Timestamp(date) - c.index[-1]).days > 7:
        return None
    return float(c.iloc[-1]) * split_factor_after(frame, c.index[-1])


def validate(frame, period_end, implied):
    """13F 내재가격(평가액/주식수)과 분기말 원시가격 비율이 0.8~1.25면 True. 판단 불가면 None."""
    raw = raw_close_on(frame, period_end)
    if not raw or not implied or implied <= 0:
        return None
    return bool(0.8 <= implied / raw <= 1.25)


def split_factor_in(frame, p):
    """분기 (직전 분기말, p] 안에 일어난 분할 비율의 곱. 없으면 1.0."""
    s = frame["Stock Splits"].fillna(0)
    m = (s.index > pd.Timestamp(prev_quarter(p))) & (s.index <= pd.Timestamp(p)) & (s > 0)
    return float(np.prod(s[m].to_numpy())) if m.any() else 1.0


def had_split(frame, p):
    return split_factor_in(frame, p) != 1.0


def _r(x, n):
    return None if x is None else round(float(x), n)


def stock_metrics(frame, entry, period_end, implied, fx=None):
    close = frame["Close"].dropna()
    if close.empty:
        return None
    adj = frame["Adj Close"].dropna()
    last, idx = float(close.iloc[-1]), adj.index
    i0 = int(idx.searchsorted(pd.Timestamp(entry), side="right")) if entry else len(idx)
    lr = np.log(adj).diff().dropna().iloc[-252:]
    yr = close.iloc[-252:]
    q = frame.loc[pd.Timestamp(quarter_start(period_end)):pd.Timestamp(period_end)]
    q = q[q["Close"].notna()]
    qv = q["Volume"].fillna(0)
    vwap = (float((q["Close"] * qv).sum() / qv.sum()) if qv.sum() > 0 else float(q["Close"].mean())) if len(q) else None
    return {"last": round(last, 2), "d": close.index[-1].date().isoformat(),
            "el": max(0, len(idx) - 1 - i0) if i0 < len(idx) else 0,
            "since": _r(adj.iloc[-1] / adj.iloc[i0] - 1, 4) if i0 < len(idx) else None,
            "vol": _r(lr.std() * np.sqrt(252), 4) if len(lr) > 60 else None,
            "hi52": _r(yr.max(), 2), "lo52": _r(yr.min(), 2),
            "ok": validate(frame, period_end, implied),
            "vwap": _r(vwap, 2), "qlo": _r(q["Close"].min(), 2) if len(q) else None,
            "qhi": _r(q["Close"].max(), 2) if len(q) else None,
            "prem": _r(last / vwap - 1, 4) if vwap else None,
            "krw": round(last * fx["krw"]) if fx else None}


def fx_krw(dl=None):
    try:
        df = (dl or _yf().download)(["KRW=X"], period="10d", auto_adjust=False, group_by="ticker", progress=False)
        c = df["KRW=X"]["Close"].dropna()
        return {"krw": round(float(c.iloc[-1]), 2), "d": c.index[-1].date().isoformat()}
    except Exception:
        return None


def analyst_targets(tickers, cache_path, today, max_age=7, limit=250, ticker_cls=None, sleep=time.sleep, log=print):
    """yfinance info의 애널리스트 목표가. 7일 캐시, 실행당 최대 limit개, 연속 5회 실패 시 중단."""
    ticker_cls = ticker_cls or _yf().Ticker
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    def fresh(e):
        return bool(e) and (today - dt.date.fromisoformat(e["d"])).days < max_age

    fails = 0
    for t in [t for t in sorted(set(tickers)) if not fresh(cache.get(t))][:limit]:
        try:
            info = ticker_cls(t).info or {}
            cache[t] = {"mean": info.get("targetMeanPrice"), "median": info.get("targetMedianPrice"),
                        "n": info.get("numberOfAnalystOpinions"), "rec": info.get("recommendationKey"),
                        "d": today.isoformat()}
            fails = 0
        except Exception as e:
            fails += 1
            log(f"애널리스트 목표가 실패 {t}: {e}")
            if fails >= 5:
                log("애널리스트 목표가: 연속 실패로 중단")
                break
        sleep(0.4)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True))
    return {t: cache[t] for t in tickers if cache.get(t) and cache[t].get("mean")}
