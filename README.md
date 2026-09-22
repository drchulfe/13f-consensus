# 13F 컨센서스 레이더

버핏 등 앵커 투자자가 매수했고, 같은 분기에 거물급 투자자 여러 명이 함께 매수(또는 보유)한 종목을
SEC EDGAR 13F 원자료에서 골라 보여주는 정적 대시보드입니다. GitHub Actions가 매일 08:00(KST) 새 공시를 확인해 페이지를 다시 만듭니다.

## 설치 (한 번, 약 5분)
1. GitHub에서 새 저장소(Public 권장 — 무료 Pages)를 만들고 이 폴더 전체를 올립니다(`.github` 폴더 포함).
2. **Settings → Secrets and variables → Actions → Variables** 에 `SEC_USER_AGENT` 추가
   값 예: `13F-Radar 본인이메일@example.com` (SEC 정책상 이름·연락처가 없는 요청은 차단됩니다)
3. (선택) **Secrets** 에 `OPENFIGI_API_KEY` 추가 — 없으면 첫 실행의 티커 매핑이 몇 분 더 걸릴 뿐입니다(https://www.openfigi.com/api 무료 발급).
4. **Settings → Pages** → Source: *Deploy from a branch*, Branch: `main`, 폴더: `/docs`
5. **Actions → update-13f → Run workflow** 로 첫 실행. 끝나면 `https://<아이디>.github.io/<저장소명>/` 에서 확인.
   (첫 실행 전 docs/index.html은 '예시 데이터' 화면입니다.)

## 파일
- `investors.json` — 추적 투자자 목록. `tier: "A"` = 앵커(레전드)군, `expect` = EDGAR 등록명 확인용 문자열(불일치하면 자동 제외되고 화면에 'CIK 불일치' 표시).
- `build.py` — EDGAR 수집·파싱·분류 → `docs/index.html`, `docs/data.json`
- `data/cache/` — 접수번호별 파싱 캐시(한 번 받은 13F는 다시 안 받음), `data/cusip_map.json` — CUSIP→티커

## 판정 규칙
- 분기 기준: 투자자별 13F-HR 원본 + 수정신고(RESTATEMENT는 대체, NEW HOLDINGS는 합산)
- 매수 = 직전 분기 대비 신규 편입(`신규`) 또는 주식수 증가(`추가`). 직전 13F가 없는 투자자는 `첫13F`
- 같은 CUSIP의 여러 행은 합산, 옵션(Put/Call)·PRN 제외
- 보유자 전원의 주식수가 같은 정수배로 변하면 주식분할로 보고 매수에서 제외
- 2023-01-03 이전 제출분은 value 단위가 천달러 → 자동 환산

## 기대수익(1주·1달·1년·3년·5년)
- 방법: 이벤트 스터디. 2013년~ 모든 분기에서 같은 규칙(앵커·최소 인원·매수/보유 기준·신규만)을 만족한 과거 시그널을 모아, 공시 다음 거래일 종가(배당 포함 수정주가, yfinance)에서 산 뒤 5·21·252·756·1260거래일 수익률을 구함
- 종목별 값 = 같은 인원 시그널(표본 30건 미만이면 조건 전체)의 **중앙값**. 공시 후 이미 지난 거래일(0·21·63·126일 격자)만큼 늦게 샀을 때 기준으로 보정 → "지금 사면"
- 범위 = 중앙값 ± 종목 최근 1년 변동성 × √기간 (로그수익률 ±1σ)
- 선택한 분기보다 이전 분기 시그널만 사용(미래 정보 차단). 백테스트는 매주 일요일(UTC) 재계산, 강제 재계산은 `FULL_BACKTEST=1`
- 편향: 상장폐지 종목은 yfinance에 없어 빠짐(생존편향, 수익률 과대), 옛 CUSIP은 현재 티커로 매핑돼 오매핑 가능, 거래비용·세금 미반영, 3·5년 구간은 겹치는 표본

## 한계
- 13F는 분기말 스냅샷(최대 45일 지연), 롱 포지션·미국 상장 증권만. 매매 시점·가격, 공매도, 해외주식은 알 수 없음
- CUSIP 변경(합병·재상장)은 '매도+신규'로 보일 수 있음
- 로컬 실행: `SEC_USER_AGENT="이름 메일" python build.py`
