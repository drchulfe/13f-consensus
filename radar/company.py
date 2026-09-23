"""종목 설명: 한국어 한 줄 설명(content/company_ko.json)과 야후 섹터·산업의 한국어 표기."""
import json
import re

from .config import COMPANY_KO, INDUSTRY_KO


def load_ko(path=COMPANY_KO):
    d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {k: v for k, v in d.items() if not k.startswith("_")}


def load_industry(path=INDUSTRY_KO):
    d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return d.get("sector", {}), d.get("industry", {})


def describe(tk, info, ko, sec_ko, ind_ko):
    """{ko: 한국어 한 줄|None, sec: 섹터, ind: 산업, en: 영문 요약 첫 문장}. 아무 정보도 없으면 None."""
    if info is None and tk not in ko:
        return None
    info = info or {}
    en = (info.get("summary") or "").strip()
    if en:
        cut, i = -1, 0
        while True:                                            # "Inc./Corp./이니셜" 뒤 마침표는 문장 끝이 아님
            c = en.find(". ", i)
            if c < 0:
                break
            word = re.sub(r"[^A-Za-z]", "", en[:c].rsplit(" ", 1)[-1])
            nxt = en[c + 2:c + 3]
            if len(word) > 4 and (not nxt or nxt.isupper()):
                cut = c
                break
            i = c + 2
        en = (en[:cut + 1] if 0 < cut < 200 else en[:200]).strip()
    sec, ind = info.get("sector"), info.get("industry")
    out = {"ko": ko.get(tk), "sec": sec_ko.get(sec, sec), "ind": ind_ko.get(ind, ind), "en": en or None}
    return out if any(out.values()) else None
