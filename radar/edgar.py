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
