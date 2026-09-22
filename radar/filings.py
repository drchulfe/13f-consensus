"""추적 투자자의 최근 Form 4(장내 매수·매도)와 Schedule 13D/13G(5%+ 지분) 공시."""
import datetime as dt
import json
import re
import xml.etree.ElementTree as ET

from .config import CACHE, FILINGS_DAYS
from .edgar import num, strip_ns, txt

F4 = ("4", "4/A")
SCHED = ("SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A")   # 2024-12 이후 XML 형식


def raw_doc_name(doc):
    """'xslF345X06/ownership.xml' → 'ownership.xml' (XSL 렌더링 경로 제거)."""
    return doc.split("/")[-1]


def pick_symbol(symbols, title):
    syms = [s for s in re.split(r"[,;\s]+", symbols or "") if s]
    if not syms:
        return ""
    if re.search(r"\bclass\s*b\b", title or "", re.I):
        b = [s for s in syms if s.upper().endswith((".B", "-B", "/B"))]
        if b:
            return b[0]
    return syms[0]


def parse_form4(xml_bytes):
    root = strip_ns(ET.fromstring(xml_bytes))
    iss = root.find("issuer")
    tx = [{"code": txt(t, "transactionCoding/transactionCode"), "date": txt(t, "transactionDate/value"),
           "title": txt(t, "securityTitle/value"),
           "sh": num(txt(t, "transactionAmounts/transactionShares/value", "0")) or 0.0,
           "px": num(txt(t, "transactionAmounts/transactionPricePerShare/value", "0")) or 0.0,
           "post": num(txt(t, "postTransactionAmounts/sharesOwnedFollowingTransaction/value", "0")) or 0.0}
          for t in root.iter("nonDerivativeTransaction")]
    return {"issuer_cik": txt(iss, "issuerCik").zfill(10), "name": txt(iss, "issuerName"),
            "symbols": txt(iss, "issuerTradingSymbol"), "tx": tx}


def summarize_form4(d):
    """P(장내매수)·S(장내매도)를 코드별로 합산(가중평균가, 마지막 거래 후 보유)."""
    res = []
    for code, kind in (("P", "buy"), ("S", "sell")):
        tx = [t for t in d["tx"] if t["code"] == code and t["sh"] > 0]
        if not tx:
            continue
        sh = sum(t["sh"] for t in tx)
        last = max(tx, key=lambda t: t["date"])
        res.append({"kind": kind, "sh": sh, "px": round(sum(t["sh"] * t["px"] for t in tx) / sh, 4),
                    "post": last["post"], "date": last["date"], "title": last["title"]})
    return res


def parse_schedule13(xml_bytes):
    root = strip_ns(ET.fromstring(xml_bytes))

    def first(*tags):
        for tg in tags:
            for el in root.iter(tg):
                if el.text and el.text.strip():
                    return el.text.strip()
        return ""

    def nums(*tags):
        return [num(el.text) or 0.0 for tg in tags for el in root.iter(tg) if el.text and el.text.strip()]

    sh = nums("reportingPersonBeneficiallyOwnedAggregateNumberOfShares", "aggregateAmountOwned")
    pct = nums("classPercent", "percentOfClass")
    return {"issuer_cik": first("issuerCik", "issuerCIK").zfill(10), "name": first("issuerName"),
            "cusip": first("issuerCusipNumber").upper(), "form": first("submissionType"),
            "amend": first("amendmentNo"), "event": first("dateOfEvent", "eventDateRequiresFilingThisStatement"),
            "sh": max(sh) if sh else 0.0, "pct": max(pct) if pct else 0.0}


def recent_filings(sec, inv_subs, own, today, days=FILINGS_DAYS, limit=300):
    """inv_subs: [(투자자 id, CIK, 제출 행)], own: {투자자 id: 자기 CIK 집합} → 최신순 리스트."""
    since = (today - dt.timedelta(days=days)).isoformat()
    jobs = [(inv, cik, r) for inv, cik, rows in inv_subs for r in rows
            if r["filed"] >= since and r["form"] in F4 + SCHED and r["doc"].lower().endswith(".xml")]

    def load(job):
        inv, cik, r = job
        cp = CACHE / f"f_{r['acc']}.json"
        if cp.exists():
            return job, json.loads(cp.read_text(encoding="utf-8"))
        b = sec.get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{r['acc'].replace('-', '')}/{raw_doc_name(r['doc'])}")
        if not b:
            return job, None
        try:
            d = parse_form4(b) if r["form"] in F4 else parse_schedule13(b)
        except ET.ParseError:
            return job, None
        CACHE.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return job, d

    out, seen = [], set()
    for (inv, cik, r), d in sec.map(load, jobs):
        if not d or r["acc"] in seen or d["issuer_cik"] in own.get(inv, set()):   # 투자자 자신이 발행사면 제외
            continue
        seen.add(r["acc"])
        base = {"d": r["filed"], "inv": inv, "form": r["form"], "acc": r["acc"], "cik": cik, "name": d["name"]}
        if r["form"] in F4:
            for x in summarize_form4(d):
                out.append({**base, "kind": x["kind"], "tk": pick_symbol(d["symbols"], x["title"]), "cusip": "",
                            "sh": x["sh"], "px": x["px"], "val": round(x["sh"] * x["px"]), "post": x["post"],
                            "pct": None, "td": x["date"]})
        else:
            out.append({**base, "kind": "stake", "tk": "", "cusip": d["cusip"], "sh": d["sh"], "px": None,
                        "val": None, "post": d["sh"], "pct": d["pct"], "td": d["event"]})
    out.sort(key=lambda x: (x["d"], x["acc"]), reverse=True)
    return out[:limit]
