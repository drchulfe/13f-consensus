"""출원인 전수 유형 분류 초안(검토용). 사람이 확정하고, 2인 독립 분류로 κ를 산출하기 위한 시작점이다.

사용법:
    python paper1/actor_draft.py <G06Q4008.xlsx> <actors.csv> <out.xlsx>

규칙: ① actors.csv 확정분 → ② 이름 규칙(ecosystem.actor_type) → ③ '기타 기업'은 출원 제목 키워드로 유형 제안
출력 열: 출원인, 출원 수, 자동 유형, 제안 유형, 근거(키워드 적중률), 확신도, 대표 제목 3개, 검토자1, 검토자2
"""
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ecosystem as E  # noqa: E402

HINTS = {  # 제목 키워드 → 제안 유형
    "헬스케어·의료IT": r"의료|진료|병원|환자|치과|약국|처방|건강검진|의약",
    "모빌리티·제조": r"차량|자동차|운전|주행|운행|텔레매틱스|블랙박스|폐차|정비",
    "인슈어테크": r"보험|보장|손해사정|청구|언더라이팅|설계사|보험료",
}


def main():
    src, actors, out = sys.argv[1:4]
    df = pd.read_excel(src, sheet_name=0, dtype=str)
    override = pd.read_csv(actors).set_index("applicant")["type"].to_dict()
    rows = []
    ex = df.assign(a=df["출원인"].map(E.split_applicants)).explode("a")
    for name, g in ex.groupby("a"):
        canon = E.canon(name)
        auto = "보험사" if canon in E.FIRMS else E.actor_type(name, override)
        titles = g["발명의명칭"].astype(str).tolist()
        sugg, basis, conf = auto, "", "확정" if name in override else "규칙"
        if auto == "기타 기업":
            hits = {t: sum(bool(re.search(p, x)) for x in titles) / len(titles) for t, p in HINTS.items()}
            # 의료·모빌리티 신호가 보험 신호보다 우선(보험 출원은 대부분 '보험'을 포함하므로)
            for t in ("헬스케어·의료IT", "모빌리티·제조", "인슈어테크"):
                if hits[t] >= 0.5:
                    sugg, basis = t, f"{t} 키워드 {hits[t]:.0%}"
                    break
            conf = "중" if sugg != auto and len(titles) >= 3 else "하"
        rows.append({"출원인": name, "출원 수": len(titles), "자동 유형": auto, "제안 유형": sugg, "근거": basis,
                     "확신도": conf, "대표 제목": " / ".join(t[:40] for t in titles[:3]), "검토자1": "", "검토자2": ""})
    res = pd.DataFrame(rows).sort_values(["출원 수", "출원인"], ascending=[False, True])
    res.to_excel(out, index=False)
    print(res["자동 유형"].value_counts().to_string())
    print(res["제안 유형"].value_counts().to_string())
    print("검토 필요(규칙 외 제안):", int((res["자동 유형"] != res["제안 유형"]).sum()))


if __name__ == "__main__":
    main()
