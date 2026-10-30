"""B안 파이프라인 동작 확인용 가상(DUMMY) 데이터. 실제 특허가 아님 — 결과 해석 금지.

A안 가상 보험사 데이터에 비보험 주체(가상 이름)를 더한다. 비보험 주체는 텔레매틱스·헬스케어·챗봇에서 빠르게 성장하도록 심어
'성장×DB 열위' 사분면과 주체 구성 변화가 복원되는지 확인한다.
"""
import random

import pandas as pd

from make_dummy_industry import TOPICS

OTHERS = {  # 이름: (유형 힌트, 토픽 가중치, 연간 기본량, 성장률)
    "가상플랫폼주식회사": ({"chat": 4, "health": 2, "sales": 3, "fraud": 1}, 6, 0.30),
    "가상모빌리티주식회사": ({"telem": 6, "claim_img": 2}, 4, 0.35),
    "주식회사 보험테크랩": ({"claim_img": 3, "uw_data": 2, "fraud": 2}, 3, 0.25),
    "헬스온 주식회사": ({"health": 6, "uw_data": 1}, 3, 0.40),
    "한빛대학교 산학협력단": ({"fraud": 2, "health": 2, "telem": 1}, 2, 0.10),
    "Acme Insurtech Inc.": ({"uw_data": 2, "claim_img": 2, "chat": 1}, 1, 0.20),
    "김민준": ({"sales": 1, "health": 1}, 1, 0.0),
    "이서연": ({"telem": 1, "sales": 1}, 1, 0.0),
}


def main():
    random.seed(2)
    ins = pd.read_excel("dummy_industry.xlsx")  # make_dummy_industry.py 먼저 실행
    rows = ins.to_dict("records")
    i = len(rows)
    for name, (w, base, g) in OTHERS.items():
        for y in range(2016, 2026):
            for _ in range(max(0, round(random.gauss(base * (1 + g) ** (y - 2016), 1)))):
                t = random.choices(list(w), weights=list(w.values()))[0]
                title = random.choice(TOPICS[t][0])
                ipc = "|".join(random.sample(TOPICS[t][1].split("|")[1:], k=random.randint(1, 2)) + ["G06Q 40/08"])
                app = name + ("|김민준" if name == "가상모빌리티주식회사" and random.random() < 0.1 else "")
                rows.append({"출원번호": f"10-{y}-9{i:06d}", "출원일자": f"{y}.{random.randint(1,12):02d}.{random.randint(1,28):02d}",
                             "발명의명칭": title + " 시스템 및 방법", "요약": f"본 발명은 {title}에 관한 것이다.",
                             "IPC분류": ipc, "출원인": app, "등록번호": ""})
                i += 1
    # 생태계 밖(G06Q 40/08 미포함) 노이즈 — 필터가 걸러내는지 확인용
    for j in range(40):
        rows.append({"출원번호": f"10-2020-8{j:06d}", "출원일자": "2020.05.01", "발명의명칭": "물류 배송 경로 최적화",
                     "요약": "배송 경로", "IPC분류": "G06Q 10/08", "출원인": "가상물류주식회사", "등록번호": ""})
    pd.DataFrame(rows).to_excel("dummy_ecosystem.xlsx", index=False)
    pd.DataFrame({"applicant": ["가상플랫폼주식회사", "가상모빌리티주식회사", "주식회사 보험테크랩", "헬스온 주식회사"],
                  "type": ["IT·플랫폼", "모빌리티·제조", "기타 기업", "기타 기업"]}).to_csv("actors_dummy.csv", index=False)
    print("dummy rows:", len(rows))


if __name__ == "__main__":
    main()
