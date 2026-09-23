"""직전 분기 대비 변화 분류와 주식분할 판정."""
import statistics
from collections import defaultdict

from .dates import prev_quarter

BUY = ("new", "add")
HOLD = ("new", "first", "add", "hold", "reduce")
SPLIT_KS = (2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50)


def detect_split(actions):
    """보유 지속자 주식수 비율의 중앙값이 정수배(또는 역수)이고 그 배수와 정확히 맞는 보유자가 1명 이상이면 분할 후보.
    분할 분기에 매매까지 한 보유자가 섞여도 놓치지 않는다(전원 일치 조건은 대형주에서 거의 실패)."""
    ratios = [a["sh"] / a["psh"] for a in actions if a["psh"] > 0 and a["sh"] > 0]
    if not ratios:
        return None
    med = statistics.median(ratios)
    tol = 0.002 if len(ratios) == 1 else 0.01
    for k in SPLIT_KS:
        for kk in (k, 1 / k):
            if abs(med / kk - 1) < tol and any(abs(x / kk - 1) < 0.02 for x in ratios):
                return k if kk >= 1 else -k
    return None


def classify(invs, raw):
    all_periods = sorted({p for r in raw.values() for p in r["periods"]}, reverse=True)
    out = {}
    for p in all_periods:
        stocks = defaultdict(lambda: {"actions": []})
        filed = []
        for inv in invs:
            r = raw.get(inv["id"])
            if not r or p not in r["periods"]:
                continue
            cur = r["periods"][p]
            pp = prev_quarter(p)                                 # 정확히 직전 분기가 있어야 비교
            prev = r["periods"][pp]["holdings"] if pp in r["periods"] else None
            total = sum(v["value"] for v in cur["holdings"].values()) or 1
            filed.append({"inv": inv["id"], "cik": cur.get("cik"), "filed": cur["filed"], "last_filed": cur["last_filed"],
                          "accs": cur["accs"], "n": len(cur["holdings"]), "aum": round(total), "has_prev": prev is not None})
            for c in set(cur["holdings"]) | set(prev or {}):
                h, ph = cur["holdings"].get(c), (prev or {}).get(c)
                sh, psh = (h or {}).get("shares", 0), (ph or {}).get("shares", 0)
                if h and not ph:
                    t = "new" if prev is not None else "first"   # first = 직전 13F 없음
                elif h and ph:
                    t = "add" if sh > psh * 1.0001 else ("reduce" if sh < psh * 0.9999 else "hold")
                else:
                    t = "sold"
                s = stocks[c]
                src = h or ph
                s.setdefault("name", src["name"])
                s.setdefault("cls", src["cls"])
                v = (h or {}).get("value", 0)
                s["actions"].append({"inv": inv["id"], "t": t, "sh": round(sh), "psh": round(psh), "v": round(v),
                                     "w": round(v / total * 100, 3), "f": (h or {}).get("f", cur["last_filed"])})
        for s in stocks.values():
            s["split"] = detect_split(s["actions"])
            if s["split"]:                                        # 분할 후보: 원래 분류는 t0에 보관(주가로 확인)
                for a in s["actions"]:
                    if a["t"] in ("add", "reduce"):
                        a["t0"], a["t"] = a["t"], "hold"
        out[p] = {"filed": filed, "stocks": [{"cusip": c, **v} for c, v in stocks.items()]}
    return out


def entry_date(stock):
    """시그널이 완전히 공개된 날 = 매도 아닌 행 공시일 중 가장 늦은 날."""
    ds = [a["f"] for a in stock["actions"] if a["t"] != "sold"]
    return max(ds) if ds else None


def buy_stocks(P, use_t0=True):
    """매수(new/add) 1명 이상 종목만. use_t0면 분할 후보의 원래 분류도 매수로 본다."""
    def buy(a):
        return a["t"] in BUY or (use_t0 and a.get("t0") in BUY)
    return {**P, "stocks": [s for s in P["stocks"] if any(buy(a) for a in s["actions"])]}
