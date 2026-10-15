# Suh & Sohn (2015) 설정과 이 스킬의 대응

Suh, J., & Sohn, S. Y. (2015). Analyzing technological convergence trends in a business ecosystem.
*Industrial Management & Data Systems*, 115(4), 718–739. https://doi.org/10.1108/IMDS-10-2014-0310

## 원 논문 절차 (쪽수는 학술지 기준)

| 단계 | 원 논문 | 쪽 |
|---|---|---|
| 데이터 | 선도기업(삼성전자) USPTO 특허, 출원일 기준, 모든 법적 상태, 2000–2011, 2년 단위 6구간 | 721, 724–725 |
| 전처리 | 제목의 명사·명사구, log 국소가중 × entropy 전역가중 | 722 |
| 차원축소 | SVD 최대 25차원 | 722–723 |
| 군집 | EM, 최대 20군집. 대표어는 상위 2m 빈출어를 이항확률 순으로 m개 | 723 |
| 병합 | 비슷한 군집은 연구자가 병합 | 725 |
| 관심분야 | 비중이 크거나 최근 변화가 두드러진 분야 4개, 분야별 상위 10 IPC(중분류) | 728, Table III |
| 연관규칙 | 거래 = 특허, 항목 = IPC. lift > 1, confidence > 60%, 규칙당 최대 4개 IPC, 같은 패턴 규칙 축소 | 723–724, 730 |
| 해석 | 규칙을 기업의 실제 제품 출시와 대조 | 731 |

원 논문도 여러 구간에서 "No rule"을 보고했다(Tables IV–VII). 규칙 0개는 그대로 결과다.
p.730의 "three consecutive sequential codes" 조건은 뜻이 불명확해 구현하지 않았다.

## 이 스킬에서 다르게 하는 것 (보고서·논문에 명시)

| 항목 | 원 논문 | 이 스킬 | 이유 |
|---|---|---|---|
| 분석 단위 | 선도기업 1곳 | 산업 또는 기술 생태계 전체 | 선도기업이 생태계를 대표하지 않을 수 있음(검증 대상) |
| 텍스트 | 제목 | 제목 + 요약 | BM특허 제목은 "~시스템 및 방법"으로 획일적 |
| 군집 시점 | 구간별 군집 | 전체 기간 한 번 군집 후 구간별 비중 | 소표본에서 구간별 군집 불가 |
| SVD 차원 | 25 | 표본에 따라 8–25 (ARI로 선택) | 소표본 안정성 |
| k 선택 | 최대 20 지정 | BIC + 초기값 간 ARI | 과분할 방지 |
| 불용어 | 명시 없음 | 특허 상투어·출원인 문체 추가 | 문체 기반 군집 방지 |
| 규칙 중복 | "같은 패턴 축소" | 같은 뒷받침 특허 묶음(tidset)마다 1개 | 축소 기준의 조작적 정의 |
| 규칙 유의성 | 없음 | 초기하분포 + BH | support 기준 부재 보완 |

## 관련 문헌 (확인된 것)

- Ozcan, S., Vogel, D. B., & Saritas, O. (2025). Technological adoptions and sector-specific innovations in a low-tech
  environment: key actors and sources of R&D in InsurTech. *Scientometrics*, 130(1). https://doi.org/10.1007/s11192-024-05209-7
- Karvonen, M., & Kässi, T. (2011). Patent analysis for analysing technological convergence. *foresight*, 13(5).
- Eling, M., Nuessle, D., & Staubli, J. (2022). The impact of artificial intelligence along the insurance value chain and on the
  insurability of risks. *Geneva Papers on Risk and Insurance – Issues and Practice*, 47, 205–241.

서지를 논문에 넣기 전에는 원문으로 권·호·쪽을 대조한다.
