"""OpenDART에서 DB손해보험(구 동부화재, 종목코드 005830) 사업보고서 원문을 내려받는다.

    DART_API_KEY=... python fetch_dart.py --from 2016 --to 2025 --out raw

사업연도 t의 사업보고서는 t+1년 3월경 제출된다. 같은 사업연도에 정정보고서가 있으면
가장 늦게 접수된 것(정정본 = 전체 대체본)을 쓴다.
"""
import argparse, io, json, os, re, sys, zipfile
import xml.etree.ElementTree as ET

import requests

API = "https://opendart.fss.or.kr/api"
STOCK_CODE = "005830"


def corp_code(key, stock=STOCK_CODE):
    r = requests.get(f"{API}/corpCode.xml", params={"crtfc_key": key}, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        root = ET.fromstring(z.read(z.namelist()[0]))
    for item in root.iter("list"):
        if (item.findtext("stock_code") or "").strip() == stock:
            return item.findtext("corp_code").strip()
    raise SystemExit(f"stock_code {stock} not found in corpCode.xml")


def list_annual_reports(key, corp, fy_from, fy_to):
    """사업연도 -> 최신 rcept_no."""
    out, page = {}, 1
    while True:
        r = requests.get(f"{API}/list.json", params={
            "crtfc_key": key, "corp_code": corp, "pblntf_detail_ty": "A001",
            "bgn_de": f"{fy_from + 1}0101", "end_de": f"{fy_to + 1}1231",
            "page_no": page, "page_count": 100}, timeout=60)
        js = r.json()
        if js.get("status") == "013":          # 조회된 데이터 없음
            break
        if js.get("status") != "000":
            raise SystemExit(f"OpenDART error: {js}")
        for it in js["list"]:
            m = re.search(r"\((\d{4})\.\d{2}\)", it["report_nm"])
            if "사업보고서" not in it["report_nm"] or not m:
                continue
            fy = int(m.group(1))
            if fy_from <= fy <= fy_to and it["rcept_no"] > out.get(fy, {}).get("rcept_no", ""):
                out[fy] = {"rcept_no": it["rcept_no"], "report_nm": it["report_nm"], "rcept_dt": it["rcept_dt"]}
        if page >= js["total_page"]:
            break
        page += 1
    return dict(sorted(out.items()))


def download(key, rcept_no, path):
    r = requests.get(f"{API}/document.xml", params={"crtfc_key": key, "rcept_no": rcept_no}, timeout=120)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        main = f"{rcept_no}.xml" if f"{rcept_no}.xml" in names else max(names, key=lambda n: z.getinfo(n).file_size)
        with open(path, "wb") as f:
            f.write(z.read(main))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="fy_from", type=int, default=2016)
    ap.add_argument("--to", dest="fy_to", type=int, default=2025)
    ap.add_argument("--out", default="raw")
    a = ap.parse_args()
    key = os.environ.get("DART_API_KEY") or sys.exit("DART_API_KEY 환경변수가 필요하다 (opendart.fss.or.kr 에서 발급)")
    os.makedirs(a.out, exist_ok=True)
    corp = corp_code(key)
    reports = list_annual_reports(key, corp, a.fy_from, a.fy_to)
    for fy, it in reports.items():
        path = os.path.join(a.out, f"{fy}.xml")
        download(key, it["rcept_no"], path)
        print(fy, it["rcept_no"], it["report_nm"], "->", path)
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"corp_code": corp, "reports": reports}, f, ensure_ascii=False, indent=1)
    missing = [y for y in range(a.fy_from, a.fy_to + 1) if y not in reports]
    if missing:
        print("누락 사업연도:", missing)


if __name__ == "__main__":
    main()
