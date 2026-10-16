"""파이프라인 동작 확인용 가상(DUMMY) 데이터. 실제 DB손해보험 특허가 아님 — 결과 해석 금지."""
import random

import pandas as pd

random.seed(0)
TEMPLATES = [
    ("블랙박스 영상을 이용한 인공지능 기반 자동차 사고 과실 판정 시스템", "G06Q 40/08|G06T 7/00|G06N 3/08"),
    ("빅데이터 기반 고객 맞춤형 가입설계 및 인수심사 시스템", "G06Q 40/08|G06Q 30/02"),
    ("보험금 청구 서류 이미지의 OCR 처리 방법", "G06Q 40/08|G06V 30/10"),
    ("웨어러블 센서를 활용한 건강 관리 보험료 할인 서비스 제공 방법", "G06Q 40/08|G16H 20/30|A61B 5/00"),
    ("챗봇을 이용한 보험 상담 서비스 제공 장치", "G06Q 40/08|G06F 40/30"),
    ("텔레매틱스 주행 데이터 기반 자동차 보험 요율 산출 방법", "G06Q 40/08|G07C 5/08"),
    ("보험사기 의심 청구 탐지를 위한 머신러닝 모델 학습 방법", "G06Q 40/08|G06N 20/00"),
    ("모바일 어플리케이션 기반 설계사 영업 지원 플랫폼", "G06Q 30/02|G06Q 50/10"),
    ("블록체인을 이용한 보험 계약관리 및 전자서명 방법", "G06Q 40/08|H04L 9/32"),
]
rows = []
for i in range(110):
    y = random.choices(range(2016, 2026), weights=[4, 5, 6, 8, 10, 12, 13, 15, 16, 8])[0]
    t, ipc = random.choice(TEMPLATES[:6] if y < 2020 else TEMPLATES)
    rows.append({"출원번호": f"10-{y}-{i:07d}", "출원일자": f"{y}.{random.randint(1,12):02d}.{random.randint(1,28):02d}",
                 "발명의명칭": t, "요약": t + "에 관한 것이다.", "IPC분류": ipc,
                 "출원인": random.choice(["DB손해보험주식회사"] * 6 + ["동부화재해상보험주식회사"] * (3 if y < 2018 else 0)
                                       + ["DB손해보험주식회사|○○테크(가상)"]),
                 "등록번호": f"10-{random.randint(1000000,2999999)}" if random.random() < (0.6 if y < 2024 else 0.15) else ""})
pd.DataFrame(rows).to_excel("dummy_kipris.xlsx", index=False)
print("dummy rows:", len(rows))
