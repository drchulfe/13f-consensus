#!/usr/bin/env python3
"""
13F 컨센서스 빌더
SEC EDGAR 13F → 변화 분류 → 주가·가격 검증 → 백테스트·수시 공시 → docs/index.html(데이터 내장)
환경변수:
  SEC_USER_AGENT   (필수) 예: "13F-Consensus yourname@example.com" — SEC 공정접근 정책상 연락처 필수
  OPENFIGI_API_KEY (선택) CUSIP→티커 변환 속도 향상
  FULL_BACKTEST=1  (선택) 백테스트 강제 전체 재계산
"""
import datetime as dt
import json
import math
import os
import sys

from radar import config as C
from radar import prices
from radar.backtest import make_events, run_backtest
from radar.classify import BUY, HOLD, buy_stocks, classify
from radar.edgar import investor_periods, investor_status, normalize_investor
from radar.filings import recent_filings
from radar.metrics import display_metrics
from radar.sec import SecClient
from radar.tickers import map_tickers, yf_sym


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def is_candidate(s, tier):
    """애널리스트 목표가 조회 대상: 매수 2명+ 또는 앵커(A) 매수 + 보유 2명+."""
    b = [a for a in s["actions"] if a["t"] in BUY]
    h = [a for a in s["actions"] if a["t"] in HOLD]
    return len(b) >= 2 or (any(tier.get(a["inv"]) == "A" for a in b) and len(h) >= 2)


def finite(o):
    """NaN·Infinity가 JSON에 들어가면 페이지 전체가 깨지므로 None으로 바꾼다."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: finite(v) for k, v in o.items()}
    if isinstance(o, list):
        return [finite(v) for v in o]
    return o


def render_html(tpl, data):
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return tpl.replace("/*__DATA__*/null", js.replace("</", "<\\/"))


def collect(sec, invs, today):
    raw, meta, inv_subs, own, errors = {}, [], [], {}, 0
    san = {"n": 0, "total_bad": 0, "count_bad": 0}
    for inv in invs:
        base = {k: inv[k] for k in ("id", "label", "fund", "tier")}
        try:
            r = investor_periods(sec, inv)
        except Exception as e:
            errors += 1
            log(f"[error] {inv['label']}: {e}")
            meta.append({**base, "ciks": inv["ciks"], "edgar_names": {}, "status": f"error: {e}",
                         "last_period": None, "notes": [], "followed": []})
            continue
        periods = r["periods"]
        if periods:
            raw[inv["id"]] = {"periods": periods}
        status = investor_status(periods, today) if periods else ("cik_mismatch" if r["bad"] else "no_filings")
        own[inv["id"]] = set(r["subs"])
        inv_subs += [(inv["id"], cik, rows) for cik, rows in r["subs"].items()]
        for k in san:
            san[k] += r["san"][k]
        meta.append({**base, "ciks": list(r["subs"]), "edgar_names": r["names"], "status": status,
                     "last_period": max(periods) if periods else None, "notes": r["notes"], "followed": r["followed"]})
        log(f"[{status}] {inv['label']}: 분기 {len(periods)}개 {'; '.join(r['notes'])}")
    return raw, meta, inv_subs, own, san, errors


def main(today=None):
    today = today or dt.date.today()
    sec = SecClient(os.environ.get("SEC_USER_AGENT", "").strip())
    invs = [normalize_investor(i) for i in json.loads(C.INVESTORS.read_text(encoding="utf-8"))["investors"]]
    tier = {i["id"]: i["tier"] for i in invs}

    raw, meta, inv_subs, own, san, errors = collect(sec, invs, today)
    if errors >= max(1, round(0.3 * len(invs))):
        sys.exit(f"투자자 {errors}명 수집 실패 — 기존 페이지를 유지합니다.")

    allp = classify(invs, raw)
    show = {p: buy_stocks(allp[p]) for p in sorted(allp, reverse=True)[:C.N_SHOW]}
    filings = recent_filings(sec, inv_subs, own, today)
    cusips = ({s["cusip"] for P in show.values() for s in P["stocks"]}
              | {e["c"] for e in make_events(allp, {})} | {f["cusip"] for f in filings if f["cusip"]})
    tick = map_tickers(cusips, log=log)
    for f in filings:
        f["tk"] = f["tk"] or tick.get(f["cusip"], "")

    fx = prices.fx_krw()
    dm = display_metrics(show, tick, prices.download, fx, today,
                         extra={yf_sym(f["tk"]) for f in filings if f["tk"]}, log=log)
    if not dm["price_date"]:
        sys.exit("SPY 주가를 받지 못했습니다 — 기존 페이지를 유지합니다.")
    for f in filings:
        f["now"] = dm["quotes"].get(yf_sym(f["tk"])) if f["tk"] else None
    for P in show.values():                                   # 분할 확인 후 최종 매수 종목
        P["stocks"] = [s for s in P["stocks"] if any(a["t"] in BUY for a in s["actions"])]
        for s in P["stocks"]:
            for a in s["actions"]:
                a.pop("t0", None)
    shown = sum(len(P["stocks"]) for P in show.values())
    if not shown:
        sys.exit("표시할 시그널 종목이 없습니다 — 기존 페이지를 유지합니다.")

    cand = sorted({yf_sym(s["tk"]) for P in show.values() for s in P["stocks"] if s.get("tk") and is_candidate(s, tier)})
    an = prices.analyst_targets(cand, C.ANALYST_FILE, today, log=log)
    for P in show.values():
        for s in P["stocks"]:
            s["an"] = an.get(yf_sym(s["tk"])) if s.get("tk") else None

    full = not C.BT_FILE.exists() or today.weekday() == 6 or os.environ.get("FULL_BACKTEST") == "1"
    try:
        bt = run_backtest(allp, tick, prices.download, today, [i["id"] for i in invs], full=full, log=log)
    except Exception as e:
        log(f"백테스트 실패: {e}")
        bt = json.loads(C.BT_FILE.read_text(encoding="utf-8")) if C.BT_FILE.exists() else None

    pxs = [s.get("px") for P in show.values() for s in P["stocks"] if s.get("tk")]
    san.update(validated=sum(1 for p in pxs if p and p["ok"]), unvalidated=sum(1 for p in pxs if p and p["ok"] is False),
               noprice=sum(1 for p in pxs if not p))
    data = finite({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "price_date": dm["price_date"], "fx": fx, "investors": meta, "periods": show,
                   "bt": bt, "filings": filings, "sanity": san})
    C.OUT.mkdir(exist_ok=True)
    (C.OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    html = render_html(C.TEMPLATE.read_text(encoding="utf-8"), data)
    (C.OUT / "index.html").write_text(html, encoding="utf-8")
    log(f"완료: 분기 {list(show)} · 표시 종목 {sum(len(P['stocks']) for P in show.values())} · "
        f"수시 공시 {len(filings)} · 페이지 {len(html) / 1e6:.1f}MB · 점검 {san}")


if __name__ == "__main__":
    main()
