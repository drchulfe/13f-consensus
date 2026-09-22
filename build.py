#!/usr/bin/env python3
"""
13F 컨센서스 빌더
- SEC EDGAR에서 지정 투자자들의 13F-HR(및 /A)을 받아 보유내역을 파싱
- 직전 분기 대비 신규/추가/축소/전량매도를 분류
- docs/data.json 과 docs/index.html(데이터 내장)을 생성
환경변수:
  SEC_USER_AGENT   (필수) 예: "13F-Consensus yourname@example.com"  — SEC 공정접근 정책상 연락처 필수
  OPENFIGI_API_KEY (선택) CUSIP→티커 변환 속도 향상
"""
import json, os, re, sys, time, datetime as dt
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "cache"          # 접수번호별 파싱 결과 (한 번 받으면 재다운로드 안 함)
FIGI_CACHE = ROOT / "data" / "cusip_map.json"
OUT = ROOT / "docs"
HIST_START = "2013-06-30"                # XML 정보표가 나오기 시작한 분기(백테스트 시작점)
N_SHOW = 2                               # 화면에 보여줄 최근 보고분기 수
BT_FILE = ROOT / "data" / "backtest.json"
K_GRID = [0, 21, 63, 126]                # 공시 후 경과 거래일 격자(현재 시점 매수 보정용)
HORIZONS = {"1w": 5, "1m": 21, "1y": 252, "3y": 756, "5y": 1260}
OFFSETS = sorted({k + h for k in K_GRID for h in HORIZONS.values()} | set(K_GRID))
SEC_SLEEP = 0.15                         # SEC 한도 10req/s 이하

UA = os.environ.get("SEC_USER_AGENT", "").strip()
SESSION = requests.Session()


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def sec_get(url, as_json=False, tries=4):
    if not UA or "@" not in UA:
        sys.exit("SEC_USER_AGENT 환경변수에 이름과 이메일을 넣어주세요 (예: '13F-Consensus me@example.com').")
    for i in range(tries):
        time.sleep(SEC_SLEEP)
        r = SESSION.get(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}, timeout=30)
        if r.status_code == 200:
            return r.json() if as_json else r.content
        if r.status_code in (429, 403, 500, 502, 503):
            time.sleep(2 ** i * 2)
            continue
        r.raise_for_status()
    raise RuntimeError(f"SEC 요청 실패: {url}")


# ---------- XML 파싱 ----------
def _strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _txt(el, path, default=""):
    x = el.find(path)
    return (x.text or "").strip() if x is not None and x.text else default


def parse_info_table(xml_bytes):
    root = _strip_ns(ET.fromstring(xml_bytes))
    rows = []
    for it in root.iter("infoTable"):
        try:
            shares = float(_txt(it, "shrsOrPrnAmt/sshPrnamt", "0").replace(",", "") or 0)
            value = float(_txt(it, "value", "0").replace(",", "") or 0)
        except ValueError:
            continue
        rows.append({
            "name": _txt(it, "nameOfIssuer"),
            "cls": _txt(it, "titleOfClass"),
            "cusip": _txt(it, "cusip").upper(),
            "value": value,
            "shares": shares,
            "sh_type": _txt(it, "shrsOrPrnAmt/sshPrnamtType", "SH"),
            "put_call": _txt(it, "putCall"),
        })
    return rows


def parse_primary_doc(xml_bytes):
    root = _strip_ns(ET.fromstring(xml_bytes))
    return {
        "period": _txt(root, ".//periodOfReport"),
        "amendment_type": _txt(root, ".//amendmentInfo/amendmentType").upper(),
        "report_type": _txt(root, ".//reportType").upper(),
        "table_total": _txt(root, ".//tableValueTotal"),
    }


def aggregate(rows, value_in_thousands):
    """같은 CUSIP의 복수 행(운용역별 분할 보고)을 합산. 옵션(Put/Call)은 별도 제외."""
    agg = {}
    for r in rows:
        if r["put_call"]:
            continue
        if r["sh_type"] and r["sh_type"] != "SH":   # PRN(채권 원금) 제외
            continue
        k = r["cusip"]
        if not k:
            continue
        v = r["value"] * (1000 if value_in_thousands else 1)
        if k not in agg:
            agg[k] = {"name": r["name"], "cls": r["cls"], "value": 0.0, "shares": 0.0}
        agg[k]["value"] += v
        agg[k]["shares"] += r["shares"]
    return agg


# ---------- EDGAR 수집 ----------
def filing_files(cik, acc):
    acc_nd = acc.replace("-", "")
    idx = sec_get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nd}/index.json", as_json=True)
    names = [i["name"] for i in idx.get("directory", {}).get("item", [])]
    xmls = [n for n in names if n.lower().endswith(".xml")]
    primary = next((n for n in xmls if n.lower() == "primary_doc.xml"), None)
    others = [n for n in xmls if n != primary]
    # 정보표 파일명은 제각각 → 'info'/'table'이 들어간 것을 우선, 없으면 가장 큰 후보
    info = next((n for n in others if re.search(r"info|table|13f", n, re.I)), others[0] if others else None)
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nd}/"
    return (base + primary if primary else None), (base + info if info else None)


def load_filing(cik, f):
    """접수번호 단위로 파싱 결과를 캐시."""
    cp = CACHE / f"{f['acc']}.json"
    if cp.exists():
        return json.loads(cp.read_text())
    prim_url, info_url = filing_files(cik, f["acc"])
    meta = parse_primary_doc(sec_get(prim_url)) if prim_url else {}
    rows = parse_info_table(sec_get(info_url)) if info_url else None
    # 2023-01-03 이후 제출분부터 value 단위가 달러(이전은 천달러)
    in_thousands = f["filed"] < "2023-01-03"
    # 정보표 XML이 없는 옛 텍스트 공시는 None → 해당 분기 제외(빈 보유로 오판 방지)
    data = {**f, **meta, "holdings": aggregate(rows, in_thousands) if rows is not None else None}
    CACHE.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(data, ensure_ascii=False))
    return data


def investor_periods(inv):
    """투자자별 최근 N개 보고분기의 확정 보유내역(원본 + 수정신고 반영)."""
    sub = sec_get(f"https://data.sec.gov/submissions/CIK{inv['cik'].zfill(10)}.json", as_json=True)
    edgar_name = sub.get("name", "")
    pages = [sub["filings"]["recent"]]
    for extra in sub["filings"].get("files", []):     # 오래된 공시는 별도 페이지
        if extra.get("filingTo", "9999") >= HIST_START:
            pages.append(sec_get("https://data.sec.gov/submissions/" + extra["name"], as_json=True))
    fl, seen = [], set()
    for rec in pages:
        for i, form in enumerate(rec["form"]):
            acc = rec["accessionNumber"][i]
            if form in ("13F-HR", "13F-HR/A") and acc not in seen and rec["reportDate"][i] >= HIST_START:
                seen.add(acc)
                fl.append({"acc": acc, "form": form,
                           "filed": rec["filingDate"][i], "period": rec["reportDate"][i]})
    by_p = defaultdict(list)
    for f in fl:
        by_p[f["period"]].append(f)
    periods = sorted(by_p, reverse=True)
    out = {}
    for p in periods:
        fs = sorted(by_p[p], key=lambda x: (x["filed"], x["acc"]))
        hold, first_filed, last_filed, accs = None, None, None, []
        for f in fs:
            d = load_filing(inv["cik"], f)
            if d.get("holdings") is None:
                continue
            at = d.get("amendment_type", "")
            stamp = lambda h: {k: {**v, "f": f["filed"]} for k, v in h.items()}
            if hold is None or f["form"] == "13F-HR" or at == "RESTATEMENT":
                hold = stamp(d["holdings"])                 # 원본 또는 전면 재작성
                first_filed = first_filed or f["filed"]
            elif at == "NEW HOLDINGS":                      # 비공개 승인 후 추가 공개분 등
                for k, v in stamp(d["holdings"]).items():
                    if k in hold:
                        hold[k]["value"] += v["value"]; hold[k]["shares"] += v["shares"]
                    else:
                        hold[k] = v
            else:
                continue
            last_filed = f["filed"]; accs.append(f["acc"])
        if hold is None:
            continue
        out[p] = {"holdings": hold, "filed": first_filed, "last_filed": last_filed, "accs": accs}
    return edgar_name, out


# ---------- CUSIP → 티커 ----------
def map_tickers(cusips):
    m = json.loads(FIGI_CACHE.read_text()) if FIGI_CACHE.exists() else {}
    todo = [c for c in cusips if c not in m]
    key = os.environ.get("OPENFIGI_API_KEY", "").strip()
    batch, sleep = (100, 0.3) if key else (10, 2.6)   # 무키: 25req/분, 요청당 10건
    hdr = {"Content-Type": "application/json"}
    if key:
        hdr["X-OPENFIGI-APIKEY"] = key
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        body = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in chunk]
        try:
            r = requests.post("https://api.openfigi.com/v3/mapping", json=body, headers=hdr, timeout=30)
            if r.status_code == 429:
                time.sleep(60); r = requests.post("https://api.openfigi.com/v3/mapping", json=body, headers=hdr, timeout=30)
            r.raise_for_status()
            for c, res in zip(chunk, r.json()):
                d = (res.get("data") or [{}])[0]
                m[c] = d.get("ticker") or ""
        except Exception as e:   # 티커는 부가정보 → 실패해도 빌드는 계속
            log("OpenFIGI 실패:", e)
            break
        time.sleep(sleep)
    FIGI_CACHE.parent.mkdir(parents=True, exist_ok=True)
    FIGI_CACHE.write_text(json.dumps(m, ensure_ascii=False, indent=0, sort_keys=True))
    return m


# ---------- 변화 분류 ----------
SPLIT_KS = (2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50)


def prev_quarter(p):
    y, m = int(p[:4]), int(p[5:7])
    y, m = (y - 1, 12) if m <= 3 else (y, (m - 1) // 3 * 3)
    return f"{y}-{m:02d}-{[31, 30, 30, 31][m // 3 - 1]:02d}"


def build(invs, raw):
    all_periods = sorted({p for r in raw.values() for p in r["periods"]}, reverse=True)
    periods_out = {}
    for p in all_periods:
        stocks = defaultdict(lambda: {"actions": []})
        filed = []
        for inv in invs:
            r = raw.get(inv["id"])
            if not r or p not in r["periods"]:
                continue
            cur = r["periods"][p]
            pp = prev_quarter(p)                         # 정확히 직전 분기가 있어야 비교
            prev = r["periods"][pp]["holdings"] if pp in r["periods"] else None
            total = sum(v["value"] for v in cur["holdings"].values()) or 1
            filed.append({"inv": inv["id"], "filed": cur["filed"], "last_filed": cur["last_filed"],
                          "accs": cur["accs"], "n": len(cur["holdings"]), "aum": total, "has_prev": bool(prev)})
            keys = set(cur["holdings"]) | (set(prev) if prev else set())
            for c in keys:
                h, ph = cur["holdings"].get(c), (prev or {}).get(c)
                sh, psh = (h or {}).get("shares", 0), (ph or {}).get("shares", 0)
                if h and not ph:
                    t = "new" if prev is not None else "first"   # first = 직전 13F 없음(신규 제출자)
                elif h and ph:
                    t = "add" if sh > psh * 1.0001 else ("reduce" if sh < psh * 0.9999 else "hold")
                elif ph:
                    t = "sold"
                else:
                    continue
                s = stocks[c]
                src = h or ph
                s.setdefault("name", src["name"]); s.setdefault("cls", src["cls"])
                s["actions"].append({"inv": inv["id"], "t": t, "sh": sh, "psh": psh,
                                     "v": (h or {}).get("value", 0),
                                     "w": round((h or {}).get("value", 0) / total * 100, 3),
                                     "f": (h or {}).get("f", cur["last_filed"])})
        # 주식분할 추정: 보유 지속 투자자의 주식수 비율이 모두 같은 정수배면 '추가'가 아니라 분할로 간주
        for c, s in stocks.items():
            ratios = [a["sh"] / a["psh"] for a in s["actions"] if a["psh"] > 0 and a["sh"] > 0]
            s["split"] = None
            for k in SPLIT_KS:
                for kk in (k, 1 / k):
                    if ratios and all(abs(x / kk - 1) < 0.02 for x in ratios) and (len(ratios) >= 2 or abs(ratios[0] / kk - 1) < 0.002):
                        s["split"] = k if kk >= 1 else -k
                if s["split"]:
                    break
            if s["split"]:
                for a in s["actions"]:
                    if a["t"] in ("add", "reduce"):
                        a["t"] = "hold"
        periods_out[p] = {"filed": filed,
                          "stocks": [{"cusip": c, **v} for c, v in stocks.items()]}
    return periods_out


# ---------- 주가 · 백테스트 ----------
def yf_sym(tk):
    return tk.replace("/", "-").replace(".", "-").strip().upper()


def fetch_prices(tickers, start):
    """yfinance 수정주가(배당·분할 반영) 종가. 실패한 티커는 빠짐 → 생존편향 원인, 화면에 건수 표시."""
    import pandas as pd
    import yfinance as yf
    tickers = sorted({t for t in tickers if t})
    cols = {}
    for i in range(0, len(tickers), 150):
        chunk = tickers[i:i + 150]
        try:
            df = yf.download(chunk, start=start, auto_adjust=True, progress=False,
                             group_by="ticker", threads=True)
        except Exception as e:
            log("yfinance 실패:", e); continue
        for t in chunk:
            try:
                ser = df[t]["Close"] if isinstance(df.columns, pd.MultiIndex) else df["Close"]
                ser = ser.dropna()
                if len(ser):
                    ser.index = pd.to_datetime(ser.index).tz_localize(None).normalize()
                    cols[t] = ser
            except Exception:
                pass
        time.sleep(1)
    return pd.DataFrame(cols).sort_index()


def entry_date(stock):
    ds = [a["f"] for a in stock["actions"] if a["t"] != "sold"]
    return max(ds) if ds else None


def make_events(periods, tier):
    """백테스트 표본: 같은 분기 매수자 2명+ 또는 (레전드군 매수 + 보유자 2명+)."""
    ev = []
    for p, P in periods.items():
        for s in P["stocks"]:
            if s.get("split"):
                continue
            b = [a for a in s["actions"] if a["t"] in ("new", "add")]
            h = [a for a in s["actions"] if a["t"] in ("new", "add", "hold", "reduce")]
            if len(b) >= 2 or (len(h) >= 2 and any(tier.get(a["inv"]) == "A" for a in b)):
                ev.append({"p": p, "c": s["cusip"], "e": entry_date(s), "hn": len(h),
                           "b": [[a["inv"], "n" if a["t"] == "new" else "a"] for a in b]})
    return ev


def forward_returns(ev, px):
    """공시 다음 거래일 종가 매수 기준, OFFSETS 거래일 후 누적수익률(종목·SPY)."""
    import numpy as np, pandas as pd
    spy = px["SPY"].dropna(); cal = spy.index
    stats = {"total": len(ev), "nopx": 0}
    for e in ev:
        e["R"] = e["S"] = None
        sym = yf_sym(e.get("tk") or "")
        i0 = cal.searchsorted(pd.Timestamp(e["e"]), side="right")
        if not sym or sym not in px or i0 >= len(cal):
            stats["nopx"] += bool(i0 < len(cal)); continue
        ser = px[sym].reindex(cal).ffill(limit=5).to_numpy()
        p0 = ser[i0]
        if not np.isfinite(p0):
            stats["nopx"] += 1; continue
        sv = spy.to_numpy(); s0 = sv[i0]
        R, S = [], []
        for o in OFFSETS:
            j = i0 + o
            ok = j < len(cal) and np.isfinite(ser[j])
            R.append(round(float(ser[j] / p0 - 1), 3) if ok else None)
            S.append(round(float(sv[j] / s0 - 1), 3) if j < len(cal) else None)
        e["R"], e["S"] = R, S
    return stats


def current_metrics(periods_show):
    """표시 분기 매수 종목의 현재가, 공시 후 경과 거래일, 공시 후 수익률, 최근 1년 변동성."""
    import numpy as np, pandas as pd
    stocks = [s for P in periods_show.values() for s in P["stocks"]
              if s.get("tk") and any(a["t"] in ("new", "add") for a in s["actions"])]
    start = (dt.date.today() - dt.timedelta(days=560)).isoformat()
    px = fetch_prices([yf_sym(s["tk"]) for s in stocks] + ["SPY"], start)
    if "SPY" not in px:
        return None
    cal = px["SPY"].dropna().index
    for s in stocks:
        sym = yf_sym(s["tk"]); s["px"] = None
        if sym not in px:
            continue
        ser = px[sym].reindex(cal).ffill(limit=5)
        last = ser.dropna()
        if last.empty:
            continue
        i0 = cal.searchsorted(pd.Timestamp(entry_date(s)), side="right")
        p0 = ser.iloc[i0] if i0 < len(cal) else np.nan
        lr = np.log(last).diff().dropna().iloc[-252:]
        s["px"] = {"last": round(float(last.iloc[-1]), 2), "d": last.index[-1].date().isoformat(),
                   "el": int(max(0, len(cal) - 1 - i0)) if i0 < len(cal) else 0,
                   "since": round(float(last.iloc[-1] / p0 - 1), 4) if np.isfinite(p0) else None,
                   "vol": round(float(lr.std() * np.sqrt(252)), 4) if len(lr) > 60 else None}
    return cal[-1].date().isoformat()


def backtest(periods, tier, tick):
    """주 1회(일요일 UTC) 또는 캐시 없음/FULL_BACKTEST=1 일 때 전체 재계산, 그 외에는 캐시 사용."""
    full = (not BT_FILE.exists() or dt.date.today().weekday() == 6
            or os.environ.get("FULL_BACKTEST") == "1")
    if not full:
        return json.loads(BT_FILE.read_text())
    ev = make_events(periods, tier)
    for e in ev:
        e["tk"] = tick.get(e["c"], "")
    first = min((e["e"] for e in ev), default="2013-08-01")
    px = fetch_prices([yf_sym(e["tk"]) for e in ev if e["tk"]] + ["SPY"], first)
    if "SPY" not in px:
        log("SPY 가격을 못 받아 백테스트 생략")
        return json.loads(BT_FILE.read_text()) if BT_FILE.exists() else None
    stats = forward_returns(ev, px)
    bt = {"built": dt.date.today().isoformat(), "K": K_GRID, "H": HORIZONS, "O": OFFSETS,
          "stats": stats, "ev": [[e["p"], e["tk"], e["b"], e["hn"], e["R"], e["S"]] for e in ev if e["R"]]}
    BT_FILE.write_text(json.dumps(bt, separators=(",", ":")))
    log(f"백테스트: 표본 {stats['total']} / 가격없음 {stats['nopx']} / 사용 {len(bt['ev'])}")
    return bt


def main():
    cfg = json.loads((ROOT / "investors.json").read_text())
    invs = cfg["investors"]
    tier = {i["id"]: i["tier"] for i in invs}
    raw, meta = {}, []
    for inv in invs:
        try:
            name, periods = investor_periods(inv)
            ok = inv["expect"].upper() in name.upper()
            status = "ok" if ok else "cik_mismatch"
            if not periods:
                status = "no_filings"
            if ok and periods:
                raw[inv["id"]] = {"periods": periods}
            log(f"[{status}] {inv['label']} → {name} ({len(periods)}개 분기)")
        except Exception as e:
            name, status = "", f"error: {e}"
            log(f"[error] {inv['label']}: {e}")
        meta.append({**{k: inv[k] for k in ("id", "label", "fund", "cik", "tier")},
                     "edgar_name": name, "status": status})

    allp = build(invs, raw)
    show = {p: allp[p] for p in sorted(allp, reverse=True)[:N_SHOW]}
    ev_cusips = {e["c"] for e in make_events(allp, tier)}
    cusips = sorted({s["cusip"] for p in show.values() for s in p["stocks"]} | ev_cusips)
    tick = map_tickers(cusips)
    for p in show.values():
        for s in p["stocks"]:
            s["tk"] = tick.get(s["cusip"], "")

    price_date = None
    try:
        price_date = current_metrics(show)
    except Exception as e:
        log("현재가 수집 실패:", e)
    bt = None
    try:
        bt = backtest(allp, tier, tick)
    except Exception as e:
        log("백테스트 실패:", e)

    data = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "price_date": price_date, "investors": meta, "periods": show, "bt": bt}
    OUT.mkdir(exist_ok=True)
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (OUT / "data.json").write_text(js)
    tpl = (ROOT / "template.html").read_text()
    (OUT / "index.html").write_text(tpl.replace("/*__DATA__*/null", js.replace("</", "<\\/")))
    log(f"완료: 분기 {list(show)} / 종목 {len(cusips)}개")


if __name__ == "__main__":
    main()
