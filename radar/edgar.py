"""13F 공시 목록·파싱·캐시와 분기 확정(수정신고 병합, 다중 CIK, 13F-NT 추적)."""
import json
import re
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict

from .config import CACHE, CACHE_VERSION, HIST_START
from .dates import latest_due_quarter, prev_quarter

FORMS_13F = ("13F-HR", "13F-HR/A", "13F-NT", "13F-NT/A")
HR = ("13F-HR", "13F-HR/A")


def strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def txt(el, path, default=""):
    x = el.find(path) if el is not None else None
    return (x.text or "").strip() if x is not None and x.text else default


def num(s):
    try:
        return float(str(s).replace(",", "").replace("%", "").strip() or 0)
    except ValueError:
        return None


# ---------- XML 파싱 ----------
def parse_info_table(xml_bytes):
    root = strip_ns(ET.fromstring(xml_bytes))
    rows = []
    for it in root.iter("infoTable"):
        shares, value = num(txt(it, "shrsOrPrnAmt/sshPrnamt", "0")), num(txt(it, "value", "0"))
        if shares is None or value is None:
            continue
        rows.append({"name": txt(it, "nameOfIssuer"), "cls": txt(it, "titleOfClass"),
                     "cusip": txt(it, "cusip").upper(), "value": value, "shares": shares,
                     "sh_type": txt(it, "shrsOrPrnAmt/sshPrnamtType", "SH").upper(),
                     "put_call": txt(it, "putCall")})
    return rows


def parse_primary_doc(xml_bytes):
    root = strip_ns(ET.fromstring(xml_bytes))
    others = [{"cik": txt(om, "cik").zfill(10), "name": txt(om, "name")}
              for om in root.iter("otherManager") if txt(om, "cik")]
    return {"amendment_type": txt(root, ".//amendmentInfo/amendmentType").upper(),
            "report_type": txt(root, ".//reportType").upper(),
            "table_total": num(txt(root, ".//tableValueTotal", "0")) or 0.0,
            "entry_total": int(num(txt(root, ".//tableEntryTotal", "0")) or 0),
            "other_managers": others}


def aggregate(rows):
    """같은 CUSIP 여러 행 합산(보고 단위 그대로). 옵션(Put/Call)·PRN 제외."""
    agg = {}
    for r in rows:
        if r["put_call"] or (r["sh_type"] and r["sh_type"] != "SH") or not r["cusip"]:
            continue
        a = agg.setdefault(r["cusip"], {"name": r["name"], "cls": r["cls"], "value": 0.0, "shares": 0.0})
        a["value"] += r["value"]
        a["shares"] += r["shares"]
    return agg


def detect_thousands(holdings, filed):
    """value/주식수 중앙값이 1 미만이면 천달러 단위. 유효 행 3개 미만이면 제출일 규칙(2023-01-03 이전)."""
    px = [h["value"] / h["shares"] for h in holdings.values() if h["shares"] > 0 and h["value"] > 0]
    if len(px) >= 3:
        return statistics.median(px) < 1.0
    return filed < "2023-01-03"


def sanity(rows, meta):
    tot = sum(r["value"] for r in rows)
    tt, et = meta.get("table_total") or 0, meta.get("entry_total") or 0
    return {"rows": len(rows), "sum": tot,
            "total_ok": (not tt) or abs(tot - tt) <= max(1.0, 0.01 * tt),
            "count_ok": (not et) or len(rows) == et}


def pick_files(items):
    """index.json 항목 → (표지, 정보표). 정보표: 이름에 info/table 우선, 없으면 가장 큰 XML."""
    xmls = [i for i in items if i["name"].lower().endswith(".xml")]
    primary = next((i["name"] for i in xmls if i["name"].lower() == "primary_doc.xml"), None)
    others = [i for i in xmls if i["name"] != primary]
    pool = [i for i in others if re.search(r"info|table", i["name"], re.I)] or others
    info = max(pool, key=lambda i: int(i.get("size") or 0))["name"] if pool else None
    return primary, info


# ---------- EDGAR 수집 ----------
def submissions(sec, cik):
    """(등록명, 제출 행 리스트). 행: acc, form, filed, period, doc(primaryDocument)"""
    sub = sec.get_json(f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json")
    if not sub:
        return "", []
    pages = [sub["filings"]["recent"]]
    for extra in sub["filings"].get("files", []):          # 오래된 공시는 별도 페이지
        if extra.get("filingTo", "9999") >= HIST_START:
            pages.append(sec.get_json("https://data.sec.gov/submissions/" + extra["name"]) or {})
    rows, seen = [], set()
    for rec in pages:
        forms = rec.get("form", [])
        rd = rec.get("reportDate") or [""] * len(forms)
        pdoc = rec.get("primaryDocument") or [""] * len(forms)
        for i, form in enumerate(forms):
            acc = rec["accessionNumber"][i]
            if acc in seen:
                continue
            seen.add(acc)
            rows.append({"acc": acc, "form": form, "filed": rec["filingDate"][i], "period": rd[i] or "", "doc": pdoc[i] or ""})
    return sub.get("name", ""), rows


def load_filing(sec, cik, f):
    """접수번호 단위 파싱 결과(캐시). holdings는 보고 단위 그대로, 13F-NT·정보표 없음은 None."""
    cp = CACHE / f"{f['acc']}.json"
    if cp.exists():
        d = json.loads(cp.read_text(encoding="utf-8"))
        if d.get("v") == CACHE_VERSION:
            return d
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{f['acc'].replace('-', '')}/"
    idx = sec.get_json(base + "index.json") or {}
    primary, info = pick_files(idx.get("directory", {}).get("item", []))
    holdings = san = None
    try:
        pb = sec.get(base + primary) if primary else None
        meta = parse_primary_doc(pb) if pb else {}
        if info and f["form"] in HR:
            ib = sec.get(base + info)
            if ib:
                rows = parse_info_table(ib)
                holdings, san = aggregate(rows), sanity(rows, meta)
    except ET.ParseError:                                   # 깨진 XML → 이번엔 건너뛰고 캐시하지 않음
        return {"v": CACHE_VERSION, **f, "amendment_type": "", "report_type": "", "other_managers": [],
                "holdings": None, "sanity": None}
    d = {"v": CACHE_VERSION, "acc": f["acc"], "form": f["form"], "filed": f["filed"], "period": f["period"],
         "amendment_type": meta.get("amendment_type", ""), "report_type": meta.get("report_type", ""),
         "other_managers": meta.get("other_managers", []), "holdings": holdings, "sanity": san}
    CACHE.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return d


def cik_periods(filings, loader, cik, san=None):
    """한 CIK의 13F-HR(/A) → 분기별 확정 보유(달러 환산, 행별 공개일 f)."""
    by_p = defaultdict(list)
    for f in filings:
        if f["form"] in HR and f["period"] >= HIST_START:
            by_p[f["period"]].append(f)
    out = {}
    for p, fs in by_p.items():
        hold, first_filed, last_filed, accs = None, None, None, []
        for f in sorted(fs, key=lambda x: (x["filed"], x["acc"])):
            d = loader(f)
            if d.get("holdings") is None:
                continue
            k = 1000.0 if detect_thousands(d["holdings"], f["filed"]) else 1.0
            cur = {c: {**v, "value": v["value"] * k, "f": f["filed"]} for c, v in d["holdings"].items()}
            at = (d.get("amendment_type") or "").upper()
            if hold is None or f["form"] == "13F-HR" or at == "RESTATEMENT":
                if hold is not None:                        # 재작성: 주식수가 같은 행은 기존 공개일 유지
                    for c, v in cur.items():
                        old = hold.get(c)
                        if old and abs(old["shares"] - v["shares"]) <= 1e-4 * max(1.0, old["shares"]):
                            v["f"] = old["f"]
                hold = cur
                first_filed = first_filed or f["filed"]
            elif at == "NEW HOLDINGS":                      # 비공개 승인 후 추가 공개분
                for c, v in cur.items():
                    if c in hold:
                        hold[c]["value"] += v["value"]
                        hold[c]["shares"] += v["shares"]
                    else:
                        hold[c] = v
            else:
                continue
            last_filed = f["filed"]
            accs.append(f["acc"])
            if san is not None and d.get("sanity"):
                san["n"] += 1
                san["total_bad"] += not d["sanity"]["total_ok"]
                san["count_bad"] += not d["sanity"]["count_ok"]
        if hold is not None:
            out[p] = {"holdings": hold, "filed": first_filed, "last_filed": last_filed, "accs": accs,
                      "cik": cik, "aum": sum(v["value"] for v in hold.values())}
    return out


def merge_periods(per_cik):
    """같은 분기에 여러 CIK가 보고하면 평가액 합계가 가장 큰 쪽(주 보고자)."""
    out = {}
    for periods in per_cik.values():
        for p, P in periods.items():
            if p not in out or P["aum"] > out[p]["aum"]:
                out[p] = P
    return out


def nt_successors(loader, filings):
    """가장 최근 13F류 공시가 13F-NT면 그 표지의 '대신 보고하는 매니저' 목록."""
    f13 = sorted((f for f in filings if f["form"] in FORMS_13F), key=lambda x: (x["filed"], x["acc"]))
    if not f13 or not f13[-1]["form"].startswith("13F-NT"):
        return []
    return loader(f13[-1]).get("other_managers") or []


def name_ok(name, expect):
    return any(e.upper() in (name or "").upper() for e in expect)


def normalize_investor(inv):
    ciks = inv.get("ciks") or [inv["cik"]]
    exp = inv.get("expect") or []
    return {**inv, "ciks": [str(c).zfill(10) for c in ciks], "expect": [exp] if isinstance(exp, str) else list(exp)}


def investor_periods(sec, inv):
    inv = normalize_investor(inv)
    queue, done = list(inv["ciks"]), set()
    per_cik, subs, names, notes, followed, bad = {}, {}, {}, [], [], []
    san = {"n": 0, "total_bad": 0, "count_bad": 0}
    while queue:
        cik = queue.pop(0)
        if cik in done:
            continue
        done.add(cik)
        name, rows = submissions(sec, cik)
        names[cik] = name
        if not name_ok(name, inv["expect"]):
            bad.append(cik)
            notes.append(f"CIK {cik} 등록명 불일치: {name or '없음'}")
            continue
        subs[cik] = rows
        loader = lambda f, _c=cik: load_filing(sec, _c, f)
        f13 = [r for r in rows if r["form"] in FORMS_13F and r["period"] >= HIST_START]
        sec.map(loader, [r for r in f13 if r["form"] in HR])      # 병렬 프리패치(캐시에 저장)
        per_cik[cik] = cik_periods(f13, loader, cik, san)
        for om in nt_successors(loader, f13):
            if om["cik"] in done or om["cik"] in queue:
                continue
            if name_ok(om["name"], inv["expect"]):
                queue.append(om["cik"])
                followed.append(om["cik"])
                notes.append(f"13F-NT 자동 추적: {om['name']} ({om['cik']})")
            else:
                notes.append(f"13F-NT: 보고 주체 {om['name']} ({om['cik']}) — investors.json 추가 검토")
    return {"periods": merge_periods(per_cik), "subs": subs, "names": names, "notes": notes,
            "followed": followed, "bad": bad, "san": san}


def investor_status(periods, today):
    if not periods:
        return "no_filings"
    return "ok" if max(periods) >= prev_quarter(latest_due_quarter(today)) else "inactive"
