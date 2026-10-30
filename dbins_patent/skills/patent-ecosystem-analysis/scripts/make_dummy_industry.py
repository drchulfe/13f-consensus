"""A안 파이프라인 동작 확인용 가상(DUMMY) 데이터. 실제 보험사 특허가 아님 — 결과 해석 금지.

기업마다 기술 프로파일을 다르게 심어, RTA·군집이 그 차이를 복원하는지 확인한다.
"""
import random

import pandas as pd

random.seed(1)
TOPICS = {
    "claim_img": (["블랙박스 영상 기반 자동차 사고 과실비율 판정", "차량 파손 사진 이미지 인식을 이용한 수리비 견적 산출",
                   "보험금 청구 서류 OCR 자동 심사"], "G06Q 40/08|G06T 7/00|G06V 20/40|G06N 3/08"),
    "uw_data": (["빅데이터 기반 가입설계 및 인수심사 자동화", "고지사항 분석을 통한 언더라이팅 위험 등급 산정",
                 "인수심사 규칙 엔진 운영"], "G06Q 40/08|G06Q 10/06|G06F 16/24"),
    "health": (["웨어러블 센서 걸음 수 기반 건강 증진형 보험료 할인", "질병 예측 모델을 이용한 건강관리 서비스",
                "진료 기록 연계 실손 보험금 간편 청구"], "G06Q 40/08|G16H 50/30|A61B 5/11|G16H 10/60"),
    "telem": (["텔레매틱스 주행 데이터 기반 운전습관 점수 산출", "GPS 위치 정보 이용 주행거리 연동 자동차 보험료",
               "운전 행태 센서 데이터 분석"], "G06Q 40/08|G07C 5/08|B60W 40/09"),
    "chat": (["챗봇을 이용한 보험 상담 자동 응대", "음성 인식 기반 콜센터 상담 내용 분석",
              "자연어 처리 기반 민원 분류"], "G06Q 40/08|G06F 40/30|G10L 15/22|H04L 51/02"),
    "fraud": (["보험사기 의심 청구 탐지 머신러닝 모델", "이상 거래 탐지 네트워크 분석", "보험사기 조직 연결망 분석"],
              "G06Q 40/08|G06N 20/00|G06Q 50/26"),
    "sales": (["모바일 기반 설계사 영업 지원 플랫폼", "고객 성향 분석 기반 보험 상품 추천", "대리점 판매 실적 관리"],
              "G06Q 30/02|G06Q 50/10|G06Q 10/06"),
}
PROFILE = {  # 기업별 토픽 가중치, 연간 기본 출원량
    "삼성화재해상보험주식회사": ({"claim_img": 4, "uw_data": 3, "chat": 3, "telem": 2, "fraud": 2, "health": 1, "sales": 1}, 22),
    "DB손해보험주식회사": ({"claim_img": 5, "uw_data": 3, "telem": 2, "health": 1, "chat": 1, "fraud": 1, "sales": 1}, 10),
    "현대해상화재보험주식회사": ({"health": 4, "telem": 2, "claim_img": 2, "chat": 2, "uw_data": 1, "fraud": 1, "sales": 1}, 12),
    "KB손해보험주식회사": ({"fraud": 3, "claim_img": 2, "uw_data": 2, "sales": 2, "health": 1, "chat": 1, "telem": 1}, 8),
    "메리츠화재해상보험주식회사": ({"sales": 4, "uw_data": 3, "chat": 1, "claim_img": 1, "fraud": 1, "health": 1, "telem": 1}, 5),
    "삼성생명보험주식회사": ({"health": 4, "uw_data": 3, "sales": 2, "chat": 2, "fraud": 1, "claim_img": 1, "telem": 0}, 14),
    "한화생명보험주식회사": ({"health": 3, "chat": 3, "sales": 3, "uw_data": 2, "fraud": 1, "claim_img": 1, "telem": 0}, 10),
    "교보생명보험주식회사": ({"chat": 3, "uw_data": 3, "health": 2, "sales": 2, "fraud": 1, "claim_img": 1, "telem": 0}, 7),
}
def main():
    random.seed(1)
    rows, i = [], 0
    for name, (w, base) in PROFILE.items():
        for y in range(2016, 2026):
            growth = 0.5 + (y - 2016) * 0.12
            for _ in range(max(0, round(random.gauss(base * growth, 2)))):
                t = random.choices(list(w), weights=list(w.values()))[0]
                title = random.choice(TOPICS[t][0])
                ipc = "|".join(random.sample(TOPICS[t][1].split("|")[1:], k=random.randint(1, 2)) + ["G06Q 40/08"])
                app = name if not (name.startswith("DB") and y < 2018) else "동부화재해상보험주식회사"
                rows.append({"출원번호": f"10-{y}-{i:07d}", "출원일자": f"{y}.{random.randint(1,12):02d}.{random.randint(1,28):02d}",
                             "발명의명칭": title + " 시스템 및 방법", "요약": f"본 발명은 {title}에 관한 것이다.",
                             "IPC분류": ipc, "출원인": app, "등록번호": ""})
                i += 1
    pd.DataFrame(rows).to_excel("dummy_industry.xlsx", index=False)
    print("dummy rows:", len(rows))


if __name__ == "__main__":
    main()
