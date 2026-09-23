"""화면 표시 종목: 현재가·경과일·변동성·52주·추정 매입가·가격 검증 + 분할 후보를 주가로 확인."""
import datetime as dt
from collections import defaultdict

from .classify import entry_date
from .prices import had_split, split_factor_in, stock_metrics
from .tickers import yf_sym


def implied_price(s):
    held = [a for a in s["actions"] if a["sh"] > 0]
    sh = sum(a["sh"] for a in held)
    return sum(a["v"] for a in held) / sh if sh else None


def display_metrics(show, tick, download_fn, fx, today, extra=(), log=print):
    by_sym = defaultdict(list)
    for p, P in show.items():
        for s in P["stocks"]:
            s["tk"], s["px"] = tick.get(s["cusip"], ""), None
            if s["tk"]:
                by_sym[yf_sym(s["tk"])].append((p, s))
    syms = sorted(set(by_sym) | set(extra) | {"SPY"})
    start = (today - dt.timedelta(days=560)).isoformat()
    price_date, quotes = None, {}
    for chunk in download_fn(syms, start):
        for sym, fr in chunk.items():
            close = fr["Close"].dropna()
            if close.empty:
                continue
            quotes[sym] = round(float(close.iloc[-1]), 2)
            if sym == "SPY":
                price_date = close.index[-1].date().isoformat()
            for p, s in by_sym.get(sym, []):
                k = split_factor_in(fr, p)
                if k != 1.0:                                    # 실제 분할 → 직전 주식수를 환산해 다시 분류
                    s["split"], s["splitk"] = None, k
                    for a in s["actions"]:
                        a.pop("t0", None)
                        if a["psh"] > 0 and a["sh"] > 0:
                            a["psh"] = round(a["psh"] * k)
                            a["t"] = ("add" if a["sh"] > a["psh"] * 1.0001
                                      else "reduce" if a["sh"] < a["psh"] * 0.9999 else "hold")
                elif s.get("split"):                            # 주가에 분할 없음 → 원래 분류 복원
                    for a in s["actions"]:
                        if "t0" in a:
                            a["t"] = a.pop("t0")
                    s["split"] = None
                s["px"] = stock_metrics(fr, entry_date(s), p, implied_price(s), fx)
    log(f"현재가: {len(quotes)}/{len(syms)}개 심볼")
    return {"price_date": price_date, "quotes": quotes}
