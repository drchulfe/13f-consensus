"""과거 시그널 이벤트 → 공시 다음 거래일 매수 기준 선행수익률(가격 검증 통과분만)."""
import json
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from .classify import BUY, HOLD, entry_date
from .config import BT_FILE, HORIZONS, K_GRID, OFFSETS
from .prices import validate
from .tickers import yf_sym


def make_events(periods, tick):
    """표본: 분할 아닌 종목 중 매수 1명+ 이고 보유자(매수 포함) 2명+."""
    ev = []
    for p, P in periods.items():
        for s in P["stocks"]:
            if s.get("split"):
                continue
            b = [a for a in s["actions"] if a["t"] in BUY]
            h = [a for a in s["actions"] if a["t"] in HOLD]
            if not b or len(h) < 2:
                continue
            held = [a for a in s["actions"] if a["sh"] > 0]
            sh = sum(a["sh"] for a in held)
            ev.append({"p": p, "c": s["cusip"], "tk": tick.get(s["cusip"], ""), "e": entry_date(s), "hn": len(h),
                       "imp": sum(a["v"] for a in held) / sh if sh else None,
                       "b": [[a["inv"], "n" if a["t"] == "new" else "a"] for a in b]})
    return ev


def forward_returns(events, frames_iter, spy):
    """이벤트마다 R(OFFSETS 거래일 누적수익률), si(SPY 행 번호), st(ok/mismatch/nopx) 설정."""
    cal = spy.index
    sv = spy.to_numpy(dtype=float)
    spy_rows, spy_idx, by_sym = [], {}, defaultdict(list)
    for e in events:
        e.update(R=None, si=None, st="nopx")
        if e["tk"]:
            by_sym[yf_sym(e["tk"])].append(e)
    for chunk in frames_iter:
        for sym, fr in chunk.items():
            evs = by_sym.get(sym)
            if not evs:
                continue
            adj = fr["Adj Close"].reindex(cal).ffill(limit=5).to_numpy(dtype=float)
            for e in evs:
                ok = validate(fr, e["p"], e["imp"])
                if ok is not True:
                    e["st"] = "mismatch" if ok is False else "nopx"
                    continue
                i0 = int(cal.searchsorted(pd.Timestamp(e["e"]), side="right"))
                if i0 >= len(cal) or not np.isfinite(adj[i0]):
                    continue
                e["R"] = [round(float(adj[i0 + o] / adj[i0] - 1), 3)
                          if i0 + o < len(cal) and np.isfinite(adj[i0 + o]) else None for o in OFFSETS]
                if i0 not in spy_idx:
                    spy_idx[i0] = len(spy_rows)
                    spy_rows.append([round(float(sv[i0 + o] / sv[i0] - 1), 3) if i0 + o < len(cal) else None
                                     for o in OFFSETS])
                e["si"], e["st"] = spy_idx[i0], "ok"
    return spy_rows


def permille(xs):
    out = [None if x is None else int(round(x * 1000)) for x in xs]
    while out and out[-1] is None:
        out.pop()
    return out


def run_backtest(periods, tick, download_fn, today, inv_ids, full=False, bt_file=BT_FILE, log=print):
    if not full and bt_file.exists():
        return json.loads(bt_file.read_text(encoding="utf-8"))
    ev = make_events(periods, tick)
    first = min((e["e"] for e in ev if e["e"]), default="2013-08-01")
    spy_fr = {}
    for chunk in download_fn(["SPY"], first):
        spy_fr.update(chunk)
    if "SPY" not in spy_fr:
        log("SPY 가격을 못 받아 백테스트 생략")
        return json.loads(bt_file.read_text(encoding="utf-8")) if bt_file.exists() else None
    spy = spy_fr["SPY"]["Adj Close"].dropna()
    spy_rows = forward_returns(ev, download_fn(sorted({yf_sym(e["tk"]) for e in ev if e["tk"]}), first), spy)
    st = Counter(e["st"] for e in ev)
    ii = {x: i for i, x in enumerate(inv_ids)}
    ok = [e for e in ev if e["st"] == "ok" and all(i in ii for i, _ in e["b"])]
    P = sorted({e["p"] for e in ok})
    pi = {p: i for i, p in enumerate(P)}
    bt = {"built": today.isoformat(), "K": K_GRID, "H": HORIZONS, "O": OFFSETS, "P": P, "I": list(inv_ids),
          "stats": {"total": len(ev), "nopx": st["nopx"], "mismatch": st["mismatch"], "used": len(ok)},
          "ev": [[pi[e["p"]], e["tk"], [ii[i] * 2 + (t == "n") for i, t in e["b"]], e["hn"], permille(e["R"]), e["si"]]
                 for e in ok],
          "spy": [permille(r) for r in spy_rows]}
    bt_file.parent.mkdir(parents=True, exist_ok=True)
    bt_file.write_text(json.dumps(bt, separators=(",", ":")), encoding="utf-8")
    log(f"백테스트: {bt['stats']}")
    return bt
