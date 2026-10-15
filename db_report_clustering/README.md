# DB손해보험 사업보고서(FY2016–FY2025) 텍스트 군집분석

Suh, J. & Sohn, S.Y. (2015), "Analyzing technological convergence trends in a business ecosystem",
*Industrial Management & Data Systems* 115(4), 718–739, doi:10.1108/IMDS-10-2014-0310 의
4.2절 텍스트 군집분석(time-sequential text clustering)을 사업보고서 텍스트에 옮겨 놓은 코드.
4.3절 연관규칙분석(IPC 공출현)은 특허 분류코드가 전제라 여기서는 구현하지 않았다.

## 실행

```bash
pip install -r requirements.txt
DART_API_KEY=발급키 python fetch_dart.py --from 2016 --to 2025 --out raw   # raw/2016.xml ... raw/2025.xml
python cluster.py --raw raw --out out --mode pooled      # 전 기간 공통 군집
python cluster.py --raw raw --out out --mode per-period  # 논문 방식: 기간별 군집 → 유사 군집 병합
```

DART에서 직접 받은 파일을 쓸 때는 `raw/` 에 `2016.pdf`, `2017.html` 처럼 **사업연도로 시작하는 이름**으로
넣으면 된다(XML/HTML/PDF/TXT 지원).

산출물(`out/`): `report_<mode>.md`(군집 설명어 + 논문 Table II 형식의 기간별 비중·특징어),
`clusters_*.csv`, `share_by_period_*.csv`, `assignments_*.csv`(문단별 군집), `share_heatmap_*.png`, `info_*.json`.

## 논문 절차와의 대응

| 논문 (특허) | 이 코드 (사업보고서) |
|---|---|
| 문서 = 특허 제목 | 문서 = 「II. 사업의 내용」 문단(40–500자, 표 제외) |
| 명사·명사구만 파싱 | Kiwi 형태소 분석, 일반·고유명사 + 연속 명사 결합 명사구 |
| log 지역가중 × entropy 전역가중 | 동일: log2(tf+1) × [1 + Σ p log2 p / log2 n] |
| SVD 최대 25차원 | 동일(TruncatedSVD, 문서벡터 L2 정규화) |
| EM 군집, 최대 20개 | 대각공분산 가우시안 혼합 EM, 2–20개 중 BIC 최소 |
| 설명어: 상위 2m 빈출어 → 이항확률 순 m개 | 동일(이항 꼬리확률 P(X≥k), 기준보다 과대출현한 용어만) |
| 2년 단위 기간, 기간별 군집 비중(%) | `--bin 2` 기본(2016-17 … 2024-25), `--bin 1` 가능 |
| 유사 군집은 연구자가 수작업 병합 | `per-period`: 엔트로피 가중 공간 군집중심 코사인 유사도 ≥ `--merge-sim`(0.5)이면 평균연결 병합 |

## 해석상 주의

- 논문은 군집 비중을 "R&D 역량 집중도"로 읽는다(특허 출원 = 투자). 사업보고서 문단 비중은 **공시 서술의 비중**이지
  자원 배분이 아니다. 서식 개정(예: 2023년 IFRS 17 도입에 따른 보험 관련 기재 변경)이 그대로 군집 비중 변화로 나타난다.
- 사업보고서는 해마다 문장이 대량 이월된다. 비중이 안정적이라는 결과는 "전략 불변"보다 "복사·붙여넣기"일 가능성을
  먼저 배제해야 한다(`assignments_*.csv` 로 원문 확인).
- `per-period` 결과는 `--merge-sim` 값에 민감하다. 0.4/0.5/0.6 정도로 바꿔 군집 수·추세가 유지되는지 확인할 것.
- BIC 기준은 문서가 많을수록 큰 k를 고르는 경향이 있다. `info_*.json` 의 k가 20(상한)에 붙으면 `--max-k` 를 낮춰 해석
  가능한 수준에서 비교할 것.
- `tests/` 는 합성 말뭉치 스모크 테스트이며 분석 결과가 아니다.
