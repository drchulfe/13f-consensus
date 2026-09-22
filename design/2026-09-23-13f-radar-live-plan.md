# 13F 컨센서스 레이더 실데이터화 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 13F 레이더를 실제 SEC·주가 데이터로 돌아가게 고치고, 실전 투자용 기능(지금 사면 기대수익 개선·추정 매입가·원화·애널리스트 목표가·전략 트랙레코드·수시 공시)을 더해 GitHub Actions로 매일 자동 게시한다.

**Architecture:** 정적 사이트 파이프라인. `build.py`(얇은 진입점)가 `radar/` 모듈을 순서대로 호출해 SEC EDGAR 13F·Form 4·13D/G와 yfinance 주가를 모으고, `template.html`에 데이터를 내장한 `docs/index.html`을 만든다. GitHub Actions가 매일 실행해 `data/` 캐시를 커밋하고 `docs/`를 Pages 아티팩트로 배포한다.

**Tech Stack:** Python 3.12+(로컬 3.14), requests, pandas, numpy, yfinance(1.x), pytest / 바닐라 JS(단일 HTML), Node 내장 test runner / GitHub Actions + Pages.

**Spec:** `design/2026-09-23-13f-radar-live-design.md`

## Global Constraints

- 모든 경로 기준: 저장소 루트 `/mnt/c/사업/투자_/13f-consensus/13f-consensus` (이하 ROOT). `$SCRATCH` = 세션 스크래치패드 디렉터리(임시 스크립트·로그).
- 로컬 파이썬: `~/.venvs/13f/bin/python` (시스템 파이썬 건드리지 않음). 테스트: `~/.venvs/13f/bin/python -m pytest -q`.
- Python 3.12 호환 문법만(Actions가 3.12). 의존성: requests, pandas, numpy, yfinance, (개발) pytest. 그 외 추가 금지.
- SEC 요청: 초당 8회 이하, User-Agent는 환경변수 `SEC_USER_AGENT` (= `13F-Consensus drchulfe@gmail.com`). 이 이메일은 SEC 요청 외 어디에도 보내지 않는다.
- 화면: 단일 HTML(데이터 내장), 한국어 UI, 기존 디자인 토큰(IBM Plex, 녹색 강조, 다크 모드), 모바일 16px 여백·가로 스크롤 없음, 목표 크기 8MB 이하.
- 차트 색: 전략 `#2a78d6`(다크 `#3987e5`), S&P500 `#1baf7a`(다크 `#199e70`) — dataviz 검증기 통과(라이트 aqua 대비 2.82는 직접 라벨+표로 보완).
- `docs/`는 공개된다(GitHub Pages). 빌드 산출물(`docs/`)은 커밋하지 않고 Actions 아티팩트로 배포(저장소 비대화 방지).
- 코드 주석은 기존처럼 짧은 한국어. 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## 파일 구조

| 파일 | 책임 |
|---|---|
| `radar/config.py` | 경로·상수(HIST_START, K_GRID, HORIZONS, OFFSETS 등) |
| `radar/dates.py` | 분기 계산: 직전 분기, 분기말, 제출기한, 분기 시작일 |
| `radar/sec.py` | SEC HTTP: 토큰버킷·재시도·스레드 풀 |
| `radar/edgar.py` | 13F 파싱·캐시·분기 확정·다중 CIK·13F-NT 추적·투자자 상태 |
| `radar/classify.py` | 직전 분기 대비 변화 분류, 주식분할 판정 |
| `radar/tickers.py` | CUSIP→티커(OpenFIGI), yfinance 심볼 변환 |
| `radar/prices.py` | yfinance 청크 다운로드, 원시가격·검증, 종목 지표, 환율, 애널리스트 |
| `radar/metrics.py` | 표시 종목 지표 채우기 + 분할 후보 가격 확인 |
| `radar/backtest.py` | 이벤트, 선행수익률(청크), 압축 저장 |
| `radar/filings.py` | Form 4·13D·13G 최근 90일 |
| `build.py` | 순서 조율, 실패 시 기존 페이지 유지, HTML 렌더 |
| `template.html` | 화면(CORE 순수 함수 + UI) |
| `tests/…` | pytest(파이썬), `tests/js/core.test.mjs`(Node) |

---

### Task 1: 패키지 뼈대와 분기 계산

**Files:**
- Create: `radar/__init__.py`, `radar/config.py`, `radar/dates.py`, `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `tests/conftest.py`, `tests/fakes.py`
- Test: `tests/test_dates.py`

**Interfaces:**
- Produces: `radar.config` 상수 `ROOT, DATA, CACHE, FIGI_CACHE, BT_FILE, ANALYST_FILE, OUT, TEMPLATE, INVESTORS, HIST_START, N_SHOW, K_GRID, HORIZONS, OFFSETS, FILINGS_DAYS, CACHE_VERSION`; `radar.dates.prev_quarter(p:str)->str`, `quarter_end_on_or_before(d:date)->str`, `deadline(pe:str)->date`, `latest_due_quarter(today:date)->str`, `quarter_start(p:str)->str`; `tests/fakes.py`의 `FakeSec, subs_json, add_filing, info_xml, PRIMARY`.

- [ ] **Step 1: 테스트 작성** — `tests/test_dates.py`

```python
import datetime as dt

from radar.dates import deadline, latest_due_quarter, prev_quarter, quarter_end_on_or_before, quarter_start


def test_prev_quarter_all_quarters():
    assert prev_quarter("2026-03-31") == "2025-12-31"
    assert prev_quarter("2026-06-30") == "2026-03-31"
    assert prev_quarter("2026-09-30") == "2026-06-30"
    assert prev_quarter("2026-12-31") == "2026-09-30"


def test_quarter_end_on_or_before():
    assert quarter_end_on_or_before(dt.date(2026, 9, 23)) == "2026-06-30"
    assert quarter_end_on_or_before(dt.date(2026, 6, 30)) == "2026-06-30"
    assert quarter_end_on_or_before(dt.date(2026, 1, 5)) == "2025-12-31"


def test_deadline_shifts_weekend_to_monday():
    assert deadline("2026-06-30") == dt.date(2026, 8, 14)      # 금요일
    assert deadline("2026-12-31") == dt.date(2027, 2, 15)      # 2/14 일요일 → 월요일


def test_latest_due_quarter():
    assert latest_due_quarter(dt.date(2026, 9, 23)) == "2026-06-30"
    assert latest_due_quarter(dt.date(2026, 8, 1)) == "2026-03-31"


def test_quarter_start():
    assert quarter_start("2026-06-30") == "2026-04-01"
    assert quarter_start("2026-03-31") == "2026-01-01"
```

- [ ] **Step 2: 실패 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_dates.py` → Expected: FAIL (`ModuleNotFoundError: radar`)

- [ ] **Step 3: 구현**

`radar/__init__.py`:
```python
"""13F 컨센서스 레이더 빌드 파이프라인."""
```

`radar/config.py`:
```python
"""경로·상수."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"                   # 접수번호별 파싱 결과
FIGI_CACHE = DATA / "cusip_map.json"     # CUSIP → 티커
BT_FILE = DATA / "backtest.json"
ANALYST_FILE = DATA / "analyst.json"
OUT = ROOT / "docs"
TEMPLATE = ROOT / "template.html"
INVESTORS = ROOT / "investors.json"

HIST_START = "2013-06-30"                # XML 정보표가 나오기 시작한 분기(백테스트 시작점)
N_SHOW = 2                               # 화면에 보여줄 최근 보고분기 수
K_GRID = [0, 21, 63, 126]                # 공시 후 경과 거래일 격자(지금 매수 보정용)
HORIZONS = {"1w": 5, "1m": 21, "1y": 252, "3y": 756, "5y": 1260}
OFFSETS = sorted({k + h for k in K_GRID for h in HORIZONS.values()} | set(K_GRID))
FILINGS_DAYS = 90                        # 수시 공시 조회 기간
CACHE_VERSION = 2
```

`radar/dates.py`:
```python
"""분기 날짜 계산."""
import datetime as dt


def prev_quarter(p):
    y, m = int(p[:4]), int(p[5:7])
    y, m = (y - 1, 12) if m <= 3 else (y, (m - 1) // 3 * 3)
    return f"{y}-{m:02d}-{[31, 30, 30, 31][m // 3 - 1]:02d}"


def quarter_end_on_or_before(d):
    for m, day in ((12, 31), (9, 30), (6, 30), (3, 31)):
        q = dt.date(d.year, m, day)
        if q <= d:
            return q.isoformat()
    return f"{d.year - 1}-12-31"


def deadline(pe):
    """13F 제출기한: 분기말 + 45일, 주말이면 다음 평일."""
    d = dt.date.fromisoformat(pe) + dt.timedelta(days=45)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def latest_due_quarter(today):
    """제출기한이 지난 가장 최근 분기말."""
    q = quarter_end_on_or_before(today)
    while deadline(q) > today:
        q = prev_quarter(q)
    return q


def quarter_start(p):
    return (dt.date.fromisoformat(prev_quarter(p)) + dt.timedelta(days=1)).isoformat()
```

`requirements.txt`:
```
requests>=2.31
pandas>=2.2
numpy>=1.26
yfinance>=1.0
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest>=8
```

`pytest.ini`:
```
[pytest]
testpaths = tests
```

`tests/conftest.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

`tests/fakes.py`:
```python
"""테스트용 가짜 SEC 클라이언트와 공시 조립 도우미."""
import json


class FakeSec:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url):
        self.calls.append(url)
        v = self.routes.get(url)
        if v is None or isinstance(v, bytes):
            return v
        return json.dumps(v).encode()

    def get_json(self, url):
        b = self.get(url)
        return None if b is None else json.loads(b)

    def map(self, fn, items):
        return [fn(x) for x in items]


def subs_json(name, rows):
    """rows: [(acc, form, filed, period)] → submissions JSON."""
    return {"name": name, "filings": {"recent": {
        "accessionNumber": [r[0] for r in rows], "form": [r[1] for r in rows],
        "filingDate": [r[2] for r in rows], "reportDate": [r[3] for r in rows],
        "primaryDocument": ["primary_doc.xml"] * len(rows)}, "files": []}}


def add_filing(routes, cik, acc, primary, info=None):
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"
    items = [{"name": "primary_doc.xml", "size": str(len(primary))}]
    routes[base + "primary_doc.xml"] = primary
    if info is not None:
        items.append({"name": "infotable.xml", "size": str(len(info))})
        routes[base + "infotable.xml"] = info
    routes[base + "index.json"] = {"directory": {"item": items}}


def info_xml(rows):
    """rows: [(cusip, name, value, shares)] → 정보표 XML bytes."""
    body = "".join(
        f"<infoTable><nameOfIssuer>{n}</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>{c}</cusip>"
        f"<value>{v}</value><shrsOrPrnAmt><sshPrnamt>{s}</sshPrnamt><sshPrnamtType>SH</sshPrnamtType>"
        f"</shrsOrPrnAmt></infoTable>" for c, n, v, s in rows)
    return ('<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">'
            f"{body}</informationTable>").encode()


PRIMARY = (b'<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"><formData><coverPage>'
           b'<reportType>13F HOLDINGS REPORT</reportType></coverPage></formData></edgarSubmission>')
```

- [ ] **Step 4: 통과 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_dates.py` → Expected: `5 passed`

- [ ] **Step 5: 커밋**
```bash
git add radar tests requirements.txt requirements-dev.txt pytest.ini
git commit -m "Add radar package skeleton with quarter date helpers"
```

---

### Task 2: SEC 요청 클라이언트

**Files:**
- Create: `radar/sec.py`
- Test: `tests/test_sec.py`

**Interfaces:**
- Produces: `RateLimiter(rate, clock=time.monotonic, sleep=time.sleep).acquire()`, `SecClient(ua, max_rps=8, workers=6, session=None, sleep=time.sleep)` with `.get(url)->bytes|None`, `.get_json(url)->dict|None`, `.map(fn, items)->list`.

- [ ] **Step 1: 테스트 작성** — `tests/test_sec.py`

```python
import pytest

from radar.sec import RateLimiter, SecClient


class Resp:
    def __init__(self, code, content=b""):
        self.status_code, self.content = code, content


class Session:
    def __init__(self, seq):
        self.seq, self.calls = list(seq), []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        return self.seq.pop(0)


def client(seq):
    s = Session(seq)
    c = SecClient("13F-Test a@b.co", session=s, sleep=lambda _: None)
    c.limiter = RateLimiter(1000, sleep=lambda _: None)
    return c, s


def test_rate_limiter_spaces_calls():
    t, slept = [0.0], []
    rl = RateLimiter(8, clock=lambda: t[0], sleep=lambda s: slept.append(round(s, 3)))
    for _ in range(3):
        rl.acquire()
    assert slept == [0.125, 0.25]


def test_get_retries_then_succeeds_and_sends_user_agent():
    c, s = client([Resp(429), Resp(200, b"ok")])
    assert c.get("https://x") == b"ok"
    assert s.calls[0][1]["User-Agent"] == "13F-Test a@b.co"


def test_get_404_returns_none_and_400_raises():
    c, _ = client([Resp(404)])
    assert c.get("https://x") is None
    c, _ = client([Resp(400)])
    with pytest.raises(RuntimeError):
        c.get("https://x")


def test_get_json_and_map():
    c, _ = client([Resp(200, b'{"a": 1}')])
    assert c.get_json("https://x") == {"a": 1}
    c.workers = 3
    assert c.map(lambda x: x * 2, [1, 2, 3]) == [2, 4, 6]


def test_requires_email_in_user_agent():
    with pytest.raises(SystemExit):
        SecClient("no-contact")
```

- [ ] **Step 2: 실패 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_sec.py` → Expected: FAIL (`No module named 'radar.sec'`)

- [ ] **Step 3: 구현** — `radar/sec.py`

```python
"""SEC EDGAR 요청: 초당 한도 토큰버킷 + 재시도 + 스레드 풀."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests


class RateLimiter:
    """초당 rate회 이하로 acquire()를 통과시킨다(스레드 안전)."""

    def __init__(self, rate, clock=time.monotonic, sleep=time.sleep):
        self.interval = 1.0 / rate
        self.clock, self.sleep = clock, sleep
        self.lock = threading.Lock()
        self.next_t = 0.0

    def acquire(self):
        with self.lock:
            now = self.clock()
            t = max(now, self.next_t)
            self.next_t = t + self.interval
        if t > now:
            self.sleep(t - now)


class SecClient:
    def __init__(self, ua, max_rps=8, workers=6, session=None, sleep=time.sleep):
        if not ua or "@" not in ua:
            raise SystemExit("SEC_USER_AGENT 환경변수에 이름과 이메일을 넣어주세요 (예: '13F-Consensus me@example.com').")
        self.ua, self.workers, self.sleep = ua, workers, sleep
        self.limiter = RateLimiter(max_rps)
        self.session = session or requests.Session()

    def get(self, url, tries=5):
        """본문 bytes. 404는 None. 일시 오류(403·429·5xx·연결)는 지수 백오프로 재시도."""
        last = None
        for i in range(tries):
            self.limiter.acquire()
            try:
                r = self.session.get(url, headers={"User-Agent": self.ua, "Accept-Encoding": "gzip, deflate"},
                                     timeout=30)
            except requests.RequestException as e:
                last = e
                self.sleep(2 ** i)
                continue
            if r.status_code == 200:
                return r.content
            if r.status_code == 404:
                return None
            last = f"HTTP {r.status_code}"
            if r.status_code in (403, 429, 500, 502, 503, 504):
                self.sleep(2 ** i * 2)
                continue
            break
        raise RuntimeError(f"SEC 요청 실패({last}): {url}")

    def get_json(self, url):
        b = self.get(url)
        return None if b is None else json.loads(b)

    def map(self, fn, items):
        items = list(items)
        if self.workers <= 1 or len(items) <= 1:
            return [fn(x) for x in items]
        with ThreadPoolExecutor(self.workers) as ex:
            return list(ex.map(fn, items))
```

- [ ] **Step 4: 통과 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_sec.py` → Expected: `5 passed`

- [ ] **Step 5: 커밋**
```bash
git add radar/sec.py tests/test_sec.py
git commit -m "Add rate-limited SEC client with retries and thread pool"
```

---

### Task 3: 13F XML 파싱·단위 판정·합계 점검

**Files:**
- Create: `radar/edgar.py` (파싱 부분), `tests/fixtures/infotable.xml`, `tests/fixtures/primary_doc.xml`, `tests/fixtures/primary_doc_amend.xml`, `tests/fixtures/primary_doc_nt.xml`
- Test: `tests/test_edgar_parse.py`

**Interfaces:**
- Produces: `strip_ns(root)`, `txt(el, path, default="")->str`, `num(s)->float|None`, `parse_info_table(bytes)->list[dict(name,cls,cusip,value,shares,sh_type,put_call)]`, `parse_primary_doc(bytes)->dict(amendment_type,report_type,table_total,entry_total,other_managers[{cik,name}])`, `aggregate(rows)->{cusip:{name,cls,value,shares}}`, `detect_thousands(holdings, filed)->bool`, `sanity(rows, meta)->dict(rows,sum,total_ok,count_ok)`, `pick_files(items)->(primary|None, info|None)`.

- [ ] **Step 1: fixture 작성**

`tests/fixtures/infotable.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>2000000</value><shrsOrPrnAmt><sshPrnamt>10,000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><investmentDiscretion>SOLE</investmentDiscretion></infoTable>
  <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>1000000</value><shrsOrPrnAmt><sshPrnamt>5000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><investmentDiscretion>DFND</investmentDiscretion></infoTable>
  <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>50000</value><shrsOrPrnAmt><sshPrnamt>250</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><putCall>Put</putCall><investmentDiscretion>SOLE</investmentDiscretion></infoTable>
  <infoTable><nameOfIssuer>XYZ CORP NOTE</nameOfIssuer><titleOfClass>NOTE 1.5%</titleOfClass><cusip>98765XAB1</cusip><value>300000</value><shrsOrPrnAmt><sshPrnamt>300000</sshPrnamt><sshPrnamtType>PRN</sshPrnamtType></shrsOrPrnAmt><investmentDiscretion>SOLE</investmentDiscretion></infoTable>
  <infoTable><nameOfIssuer>COCA COLA CO</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>191216100</cusip><value>650000</value><shrsOrPrnAmt><sshPrnamt>10000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><investmentDiscretion>SOLE</investmentDiscretion></infoTable>
</informationTable>
```

`tests/fixtures/primary_doc.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler" xmlns:com="http://www.sec.gov/edgar/common">
  <headerData><submissionType>13F-HR</submissionType><filerInfo><periodOfReport>06-30-2026</periodOfReport></filerInfo></headerData>
  <formData>
    <coverPage><reportCalendarOrQuarter>06-30-2026</reportCalendarOrQuarter><isAmendment>false</isAmendment><reportType>13F HOLDINGS REPORT</reportType></coverPage>
    <summaryPage><otherIncludedManagersCount>0</otherIncludedManagersCount><tableEntryTotal>5</tableEntryTotal><tableValueTotal>4000000</tableValueTotal></summaryPage>
  </formData>
</edgarSubmission>
```

`tests/fixtures/primary_doc_amend.xml`:
```xml
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"><headerData><submissionType>13F-HR/A</submissionType></headerData><formData><coverPage><isAmendment>true</isAmendment><amendmentNo>1</amendmentNo><amendmentInfo><amendmentType>NEW HOLDINGS</amendmentType></amendmentInfo><reportType>13F HOLDINGS REPORT</reportType></coverPage><summaryPage><tableEntryTotal>1</tableEntryTotal><tableValueTotal>100</tableValueTotal></summaryPage></formData></edgarSubmission>
```

`tests/fixtures/primary_doc_nt.xml` (실제 퍼싱스퀘어 13F-NT 축약):
```xml
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler" xmlns:ns1="http://www.sec.gov/edgar/common"><headerData><submissionType>13F-NT</submissionType></headerData><formData><coverPage><reportCalendarOrQuarter>06-30-2026</reportCalendarOrQuarter><isAmendment>false</isAmendment><reportType>13F NOTICE</reportType><otherManagersInfo><otherManager><cik>0002026053</cik><form13FFileNumber>028-25746</form13FFileNumber><name>PERSHING SQUARE INC.</name></otherManager></otherManagersInfo></coverPage><summaryPage><otherIncludedManagersCount/><tableEntryTotal/><tableValueTotal/></summaryPage></formData></edgarSubmission>
```

- [ ] **Step 2: 테스트 작성** — `tests/test_edgar_parse.py`

```python
from pathlib import Path

from radar.edgar import aggregate, detect_thousands, parse_info_table, parse_primary_doc, pick_files, sanity

FX = Path(__file__).parent / "fixtures"


def test_parse_info_table_reads_all_rows():
    rows = parse_info_table((FX / "infotable.xml").read_bytes())
    assert len(rows) == 5
    assert rows[0] == {"name": "APPLE INC", "cls": "COM", "cusip": "037833100", "value": 2000000.0,
                       "shares": 10000.0, "sh_type": "SH", "put_call": ""}
    assert rows[2]["put_call"] == "Put" and rows[3]["sh_type"] == "PRN"


def test_aggregate_sums_cusip_and_drops_options_and_prn():
    agg = aggregate(parse_info_table((FX / "infotable.xml").read_bytes()))
    assert set(agg) == {"037833100", "191216100"}
    assert agg["037833100"]["value"] == 3000000.0 and agg["037833100"]["shares"] == 15000.0


def test_parse_primary_doc_totals_and_amendment():
    m = parse_primary_doc((FX / "primary_doc.xml").read_bytes())
    assert m["table_total"] == 4000000.0 and m["entry_total"] == 5 and m["amendment_type"] == ""
    assert parse_primary_doc((FX / "primary_doc_amend.xml").read_bytes())["amendment_type"] == "NEW HOLDINGS"


def test_parse_primary_doc_nt_other_managers():
    m = parse_primary_doc((FX / "primary_doc_nt.xml").read_bytes())
    assert m["report_type"] == "13F NOTICE"
    assert m["other_managers"] == [{"cik": "0002026053", "name": "PERSHING SQUARE INC."}]
    assert m["table_total"] == 0.0 and m["entry_total"] == 0


def test_detect_thousands_by_implied_price():
    dollars = {"a": {"value": 20000.0, "shares": 100}, "b": {"value": 650.0, "shares": 10}, "c": {"value": 30.0, "shares": 1}}
    thousands = {k: {**v, "value": v["value"] / 1000} for k, v in dollars.items()}
    assert detect_thousands(dollars, "2020-01-01") is False        # 제출일 규칙과 달라도 가격으로 판정
    assert detect_thousands(thousands, "2024-01-01") is True
    assert detect_thousands({"a": dollars["a"]}, "2020-01-01") is True   # 표본 부족 → 제출일 규칙


def test_sanity_flags_total_and_count():
    rows = parse_info_table((FX / "infotable.xml").read_bytes())
    ok = sanity(rows, {"table_total": 4000000.0, "entry_total": 5})
    assert ok["total_ok"] and ok["count_ok"] and ok["rows"] == 5
    bad = sanity(rows, {"table_total": 4000.0, "entry_total": 4})
    assert not bad["total_ok"] and not bad["count_ok"]


def test_pick_files_prefers_named_then_largest():
    items = [{"name": "primary_doc.xml", "size": "5555"}, {"name": "56757.xml", "size": "44724"},
             {"name": "0001-index.html", "size": ""}]
    assert pick_files(items) == ("primary_doc.xml", "56757.xml")
    assert pick_files(items + [{"name": "form13fInfoTable.xml", "size": "100"}]) == ("primary_doc.xml", "form13fInfoTable.xml")
    assert pick_files([{"name": "primary_doc.xml", "size": "1"}]) == ("primary_doc.xml", None)
```

- [ ] **Step 3: 실패 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_edgar_parse.py` → Expected: FAIL (`No module named 'radar.edgar'`)

- [ ] **Step 4: 구현** — `radar/edgar.py` (이번 태스크는 파싱 부분만; Task 4에서 아래에 이어 붙임)

```python
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
```

- [ ] **Step 5: 통과 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_edgar_parse.py` → Expected: `7 passed`

- [ ] **Step 6: 커밋**
```bash
git add radar/edgar.py tests/fixtures tests/test_edgar_parse.py
git commit -m "Parse 13F XML with unit detection and total checks"
```

---

### Task 4: 공시 캐시·분기 확정·다중 CIK·13F-NT 추적·투자자 상태

**Files:**
- Modify: `radar/edgar.py` (파일 끝에 추가)
- Test: `tests/test_edgar_periods.py`

**Interfaces:**
- Consumes: Task 3 함수들, `tests/fakes.py`.
- Produces: `submissions(sec, cik)->(name, rows[{acc,form,filed,period,doc}])`, `load_filing(sec, cik, f)->dict`, `cik_periods(filings, loader, cik, san=None)->{period:{holdings,filed,last_filed,accs,cik,aum}}`, `merge_periods(per_cik)->dict`, `nt_successors(loader, filings)->[{cik,name}]`, `name_ok(name, expect)->bool`, `normalize_investor(inv)->dict(ciks,expect 리스트)`, `investor_periods(sec, inv)->dict(periods,subs,names,notes,followed,bad,san)`, `investor_status(periods, today)->"ok"|"inactive"|"no_filings"`. holdings 행: `{name, cls, value(달러), shares, f(공개일)}`.

- [ ] **Step 1: 테스트 작성** — `tests/test_edgar_periods.py`

```python
import datetime as dt
from pathlib import Path

from fakes import PRIMARY, FakeSec, add_filing, info_xml, subs_json
from radar import edgar
from radar.edgar import cik_periods, investor_periods, investor_status, merge_periods, normalize_investor

FX = Path(__file__).parent / "fixtures"


def H(**kw):
    return {k: {"name": k, "cls": "COM", "value": v[0], "shares": v[1]} for k, v in kw.items()}


def test_cik_periods_restatement_keeps_dates_and_new_holdings_merge():
    fl = [{"acc": "a1", "form": "13F-HR", "filed": "2026-05-15", "period": "2026-03-31"},
          {"acc": "a2", "form": "13F-HR/A", "filed": "2026-08-01", "period": "2026-03-31"},
          {"acc": "a3", "form": "13F-HR/A", "filed": "2027-01-10", "period": "2026-03-31"}]
    docs = {"a1": {"holdings": H(AAA=(2000.0, 10), BBB=(5000.0, 50), CCC=(3000.0, 30)), "amendment_type": ""},
            "a2": {"holdings": H(DDD=(1000.0, 10), EEE=(400.0, 4), FFF=(900.0, 9)), "amendment_type": "NEW HOLDINGS"},
            "a3": {"holdings": H(AAA=(2000.0, 10), BBB=(6000.0, 60), CCC=(3000.0, 30), DDD=(1000.0, 10)),
                   "amendment_type": "RESTATEMENT"}}
    P = cik_periods(fl, lambda f: docs[f["acc"]], "0000000001")["2026-03-31"]
    assert P["filed"] == "2026-05-15" and P["last_filed"] == "2027-01-10" and P["accs"] == ["a1", "a2", "a3"]
    h = P["holdings"]
    assert h["AAA"]["f"] == "2026-05-15"            # 주식수 같음 → 원공시일 유지
    assert h["DDD"]["f"] == "2026-08-01"            # NEW HOLDINGS 공개일 유지
    assert h["BBB"]["f"] == "2027-01-10" and h["BBB"]["shares"] == 60
    assert "EEE" not in h and P["cik"] == "0000000001"


def test_cik_periods_converts_thousands():
    fl = [{"acc": "b1", "form": "13F-HR", "filed": "2020-02-14", "period": "2019-12-31"}]
    doc = {"holdings": H(A=(20.0, 100), B=(0.65, 10), C=(0.03, 1)), "amendment_type": ""}
    P = cik_periods(fl, lambda f: doc, "C")["2019-12-31"]
    assert P["holdings"]["A"]["value"] == 20000.0 and P["aum"] == 20000.0 + 650.0 + 30.0


def test_merge_periods_prefers_largest_aum():
    a = {"2026-03-31": {"aum": 100, "cik": "A"}, "2025-12-31": {"aum": 50, "cik": "A"}}
    b = {"2026-03-31": {"aum": 300, "cik": "B"}, "2026-06-30": {"aum": 310, "cik": "B"}}
    m = merge_periods({"A": a, "B": b})
    assert (m["2026-03-31"]["cik"], m["2025-12-31"]["cik"], m["2026-06-30"]["cik"]) == ("B", "A", "B")


def test_investor_periods_follows_13f_nt_to_parent(tmp_path, monkeypatch):
    monkeypatch.setattr(edgar, "CACHE", tmp_path)
    old, new = "0001336528", "0002026053"
    routes = {
        f"https://data.sec.gov/submissions/CIK{old}.json": subs_json("Pershing Square Capital Management, L.P.", [
            ("0000000001-26-000002", "13F-NT", "2026-08-14", "2026-06-30"),
            ("0000000001-26-000001", "13F-HR", "2026-05-15", "2026-03-31")]),
        f"https://data.sec.gov/submissions/CIK{new}.json": subs_json("PERSHING SQUARE INC.", [
            ("0000000002-26-000002", "13F-HR", "2026-08-14", "2026-06-30")])}
    rows3 = [("111111111", "AAA", 2000, 10), ("222222222", "BBB", 3000, 30), ("333333333", "CCC", 500, 5)]
    add_filing(routes, old, "0000000001-26-000001", PRIMARY, info_xml(rows3))
    add_filing(routes, old, "0000000001-26-000002", (FX / "primary_doc_nt.xml").read_bytes())
    add_filing(routes, new, "0000000002-26-000002", PRIMARY, info_xml([("111111111", "AAA", 4000, 20)] + rows3[1:]))
    r = investor_periods(FakeSec(routes), {"id": "ackman", "ciks": [old], "expect": ["PERSHING"]})
    assert set(r["periods"]) == {"2026-03-31", "2026-06-30"}
    assert r["periods"]["2026-06-30"]["cik"] == new and r["followed"] == [new]
    assert set(r["subs"]) == {old, new} and r["san"]["n"] == 2
    assert (tmp_path / "0000000001-26-000001.json").exists()      # 캐시 저장


def test_investor_periods_rejects_name_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(edgar, "CACHE", tmp_path)
    routes = {"https://data.sec.gov/submissions/CIK0000000009.json": subs_json("SOMEONE ELSE LLC", [])}
    r = investor_periods(FakeSec(routes), {"id": "x", "ciks": ["9"], "expect": ["PERSHING"]})
    assert r["periods"] == {} and r["bad"] == ["0000000009"]


def test_investor_status():
    today = dt.date(2026, 9, 23)
    assert investor_status({"2026-06-30": {}}, today) == "ok"
    assert investor_status({"2026-03-31": {}}, today) == "ok"
    assert investor_status({"2025-09-30": {}}, today) == "inactive"
    assert investor_status({}, today) == "no_filings"


def test_normalize_investor_accepts_legacy_fields():
    n = normalize_investor({"id": "b", "cik": "1067983", "expect": "BERKSHIRE"})
    assert n["ciks"] == ["0001067983"] and n["expect"] == ["BERKSHIRE"]
```

- [ ] **Step 2: 실패 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_edgar_periods.py` → Expected: FAIL (`cannot import name 'cik_periods'`)

- [ ] **Step 3: 구현** — `radar/edgar.py` 끝에 추가

```python
# ---------- EDGAR 수집 ----------
def submissions(sec, cik):
    """(등록명, 제출 행 리스트). 행: acc, form, filed, period, doc(primaryDocument)"""
    sub = sec.get_json(f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json")
    if not sub:
        return "", []
    pages = [sub["filings"]["recent"]]
    for extra in sub["filings"].get("files", []):          # 오래된 공시는 별도 페이지
        if extra.get("filingTo", "9999") >= HIST_START:
            pages.append(sec.get_json("https://data.sec.gov/submissions/" + extra["name"]) or {})
    rows, seen = [], set()
    for rec in pages:
        forms = rec.get("form", [])
        rd = rec.get("reportDate") or [""] * len(forms)
        pdoc = rec.get("primaryDocument") or [""] * len(forms)
        for i, form in enumerate(forms):
            acc = rec["accessionNumber"][i]
            if acc in seen:
                continue
            seen.add(acc)
            rows.append({"acc": acc, "form": form, "filed": rec["filingDate"][i], "period": rd[i] or "", "doc": pdoc[i] or ""})
    return sub.get("name", ""), rows


def load_filing(sec, cik, f):
    """접수번호 단위 파싱 결과(캐시). holdings는 보고 단위 그대로, 13F-NT·정보표 없음은 None."""
    cp = CACHE / f"{f['acc']}.json"
    if cp.exists():
        d = json.loads(cp.read_text(encoding="utf-8"))
        if d.get("v") == CACHE_VERSION:
            return d
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{f['acc'].replace('-', '')}/"
    idx = sec.get_json(base + "index.json") or {}
    primary, info = pick_files(idx.get("directory", {}).get("item", []))
    holdings = san = None
    try:
        pb = sec.get(base + primary) if primary else None
        meta = parse_primary_doc(pb) if pb else {}
        if info and f["form"] in HR:
            ib = sec.get(base + info)
            if ib:
                rows = parse_info_table(ib)
                holdings, san = aggregate(rows), sanity(rows, meta)
    except ET.ParseError:                                   # 깨진 XML → 이번엔 건너뛰고 캐시하지 않음
        return {"v": CACHE_VERSION, **f, "amendment_type": "", "report_type": "", "other_managers": [],
                "holdings": None, "sanity": None}
    d = {"v": CACHE_VERSION, "acc": f["acc"], "form": f["form"], "filed": f["filed"], "period": f["period"],
         "amendment_type": meta.get("amendment_type", ""), "report_type": meta.get("report_type", ""),
         "other_managers": meta.get("other_managers", []), "holdings": holdings, "sanity": san}
    CACHE.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return d


def cik_periods(filings, loader, cik, san=None):
    """한 CIK의 13F-HR(/A) → 분기별 확정 보유(달러 환산, 행별 공개일 f)."""
    by_p = defaultdict(list)
    for f in filings:
        if f["form"] in HR and f["period"] >= HIST_START:
            by_p[f["period"]].append(f)
    out = {}
    for p, fs in by_p.items():
        hold, first_filed, last_filed, accs = None, None, None, []
        for f in sorted(fs, key=lambda x: (x["filed"], x["acc"])):
            d = loader(f)
            if d.get("holdings") is None:
                continue
            k = 1000.0 if detect_thousands(d["holdings"], f["filed"]) else 1.0
            cur = {c: {**v, "value": v["value"] * k, "f": f["filed"]} for c, v in d["holdings"].items()}
            at = (d.get("amendment_type") or "").upper()
            if hold is None or f["form"] == "13F-HR" or at == "RESTATEMENT":
                if hold is not None:                        # 재작성: 주식수가 같은 행은 기존 공개일 유지
                    for c, v in cur.items():
                        old = hold.get(c)
                        if old and abs(old["shares"] - v["shares"]) <= 1e-4 * max(1.0, old["shares"]):
                            v["f"] = old["f"]
                hold = cur
                first_filed = first_filed or f["filed"]
            elif at == "NEW HOLDINGS":                      # 비공개 승인 후 추가 공개분
                for c, v in cur.items():
                    if c in hold:
                        hold[c]["value"] += v["value"]
                        hold[c]["shares"] += v["shares"]
                    else:
                        hold[c] = v
            else:
                continue
            last_filed = f["filed"]
            accs.append(f["acc"])
            if san is not None and d.get("sanity"):
                san["n"] += 1
                san["total_bad"] += not d["sanity"]["total_ok"]
                san["count_bad"] += not d["sanity"]["count_ok"]
        if hold is not None:
            out[p] = {"holdings": hold, "filed": first_filed, "last_filed": last_filed, "accs": accs,
                      "cik": cik, "aum": sum(v["value"] for v in hold.values())}
    return out


def merge_periods(per_cik):
    """같은 분기에 여러 CIK가 보고하면 평가액 합계가 가장 큰 쪽(주 보고자)."""
    out = {}
    for periods in per_cik.values():
        for p, P in periods.items():
            if p not in out or P["aum"] > out[p]["aum"]:
                out[p] = P
    return out


def nt_successors(loader, filings):
    """가장 최근 13F류 공시가 13F-NT면 그 표지의 '대신 보고하는 매니저' 목록."""
    f13 = sorted((f for f in filings if f["form"] in FORMS_13F), key=lambda x: (x["filed"], x["acc"]))
    if not f13 or not f13[-1]["form"].startswith("13F-NT"):
        return []
    return loader(f13[-1]).get("other_managers") or []


def name_ok(name, expect):
    return any(e.upper() in (name or "").upper() for e in expect)


def normalize_investor(inv):
    ciks = inv.get("ciks") or [inv["cik"]]
    exp = inv.get("expect") or []
    return {**inv, "ciks": [str(c).zfill(10) for c in ciks], "expect": [exp] if isinstance(exp, str) else list(exp)}


def investor_periods(sec, inv):
    inv = normalize_investor(inv)
    queue, done = list(inv["ciks"]), set()
    per_cik, subs, names, notes, followed, bad = {}, {}, {}, [], [], []
    san = {"n": 0, "total_bad": 0, "count_bad": 0}
    while queue:
        cik = queue.pop(0)
        if cik in done:
            continue
        done.add(cik)
        name, rows = submissions(sec, cik)
        names[cik] = name
        if not name_ok(name, inv["expect"]):
            bad.append(cik)
            notes.append(f"CIK {cik} 등록명 불일치: {name or '없음'}")
            continue
        subs[cik] = rows
        loader = lambda f, _c=cik: load_filing(sec, _c, f)
        f13 = [r for r in rows if r["form"] in FORMS_13F and r["period"] >= HIST_START]
        sec.map(loader, [r for r in f13 if r["form"] in HR])      # 병렬 프리패치(캐시에 저장)
        per_cik[cik] = cik_periods(f13, loader, cik, san)
        for om in nt_successors(loader, f13):
            if om["cik"] in done or om["cik"] in queue:
                continue
            if name_ok(om["name"], inv["expect"]):
                queue.append(om["cik"])
                followed.append(om["cik"])
                notes.append(f"13F-NT 자동 추적: {om['name']} ({om['cik']})")
            else:
                notes.append(f"13F-NT: 보고 주체 {om['name']} ({om['cik']}) — investors.json 추가 검토")
    return {"periods": merge_periods(per_cik), "subs": subs, "names": names, "notes": notes,
            "followed": followed, "bad": bad, "san": san}


def investor_status(periods, today):
    if not periods:
        return "no_filings"
    return "ok" if max(periods) >= prev_quarter(latest_due_quarter(today)) else "inactive"
```

- [ ] **Step 4: 통과 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_edgar_periods.py tests/test_edgar_parse.py` → Expected: `14 passed`

- [ ] **Step 5: 커밋**
```bash
git add radar/edgar.py tests/test_edgar_periods.py
git commit -m "Build quarterly holdings with amendments, multi-CIK merge and 13F-NT follow"
```

---

### Task 5: 변화 분류와 분할 판정

**Files:**
- Create: `radar/classify.py`
- Test: `tests/test_classify.py`

**Interfaces:**
- Consumes: `radar.dates.prev_quarter`; raw = `{inv_id: {"periods": {period: P}}}` (Task 4 형식).
- Produces: `BUY=("new","add")`, `HOLD=("new","first","add","hold","reduce")`, `detect_split(actions)->int|None`, `classify(invs, raw)->{period:{filed:[{inv,cik,filed,last_filed,accs,n,aum,has_prev}], stocks:[{cusip,name,cls,split,actions:[{inv,t,sh,psh,v,w,f[,t0]}]}]}}`, `entry_date(stock)->str|None`, `buy_stocks(P, use_t0=True)->P`.

- [ ] **Step 1: 테스트 작성** — `tests/test_classify.py`

```python
from radar.classify import buy_stocks, classify, detect_split, entry_date

INV = [{"id": "buffett", "tier": "A"}, {"id": "gates", "tier": "B"}]


def P(hold, filed="2026-05-15", cik="C"):
    return {"holdings": {c: {"name": c, "cls": "COM", "value": v, "shares": s, "f": filed} for c, (v, s) in hold.items()},
            "filed": filed, "last_filed": filed, "accs": ["x"], "cik": cik, "aum": sum(v for v, _ in hold.values())}


def test_classify_types_and_first():
    raw = {"buffett": {"periods": {
        "2026-03-31": P({"A": (100, 10), "B": (100, 10), "C": (100, 10), "E": (100, 10)}),
        "2026-06-30": P({"A": (350, 35), "B": (60, 6), "C": (100, 10), "D": (70, 7)}, "2026-08-14")}}}
    out = classify(INV, raw)
    t = {s["cusip"]: s["actions"][0]["t"] for s in out["2026-06-30"]["stocks"]}
    assert t == {"A": "add", "B": "reduce", "C": "hold", "D": "new", "E": "sold"}
    assert {s["cusip"]: s["actions"][0]["t"] for s in out["2026-03-31"]["stocks"]}["A"] == "first"
    a = next(s for s in out["2026-06-30"]["stocks"] if s["cusip"] == "A")["actions"][0]
    assert a["sh"] == 35 and a["psh"] == 10 and a["v"] == 350 and a["f"] == "2026-08-14"
    f = out["2026-06-30"]["filed"][0]
    assert f["inv"] == "buffett" and f["has_prev"] is True and f["cik"] == "C"


def test_split_marks_hold_and_keeps_original_type():
    raw = {"buffett": {"periods": {"2026-03-31": P({"A": (100, 10)}), "2026-06-30": P({"A": (100, 40)})}},
           "gates": {"periods": {"2026-03-31": P({"A": (50, 5)}), "2026-06-30": P({"A": (50, 20)})}}}
    s = classify(INV, raw)["2026-06-30"]["stocks"][0]
    assert s["split"] == 4
    assert all(a["t"] == "hold" and a["t0"] == "add" for a in s["actions"])


def test_detect_split_single_holder_needs_exact_ratio():
    assert detect_split([{"sh": 200, "psh": 100}]) == 2
    assert detect_split([{"sh": 201, "psh": 100}]) is None
    assert detect_split([{"sh": 10, "psh": 100}, {"sh": 20, "psh": 200}]) == -10


def test_buy_stocks_and_entry_date():
    P2 = {"filed": [], "stocks": [
        {"cusip": "A", "actions": [{"inv": "x", "t": "hold", "f": "2026-08-01"}]},
        {"cusip": "B", "actions": [{"inv": "x", "t": "new", "f": "2026-08-10"}, {"inv": "y", "t": "sold", "f": "2026-08-20"}]},
        {"cusip": "C", "split": 2, "actions": [{"inv": "x", "t": "hold", "t0": "add", "f": "2026-08-12"}]}]}
    assert [s["cusip"] for s in buy_stocks(P2)["stocks"]] == ["B", "C"]
    assert [s["cusip"] for s in buy_stocks(P2, use_t0=False)["stocks"]] == ["B"]
    assert entry_date(P2["stocks"][1]) == "2026-08-10"
```

- [ ] **Step 2: 실패 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_classify.py` → Expected: FAIL (`No module named 'radar.classify'`)

- [ ] **Step 3: 구현** — `radar/classify.py`

```python
"""직전 분기 대비 변화 분류와 주식분할 판정."""
from collections import defaultdict

from .dates import prev_quarter

BUY = ("new", "add")
HOLD = ("new", "first", "add", "hold", "reduce")
SPLIT_KS = (2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50)


def detect_split(actions):
    """보유 지속자 주식수 비율이 모두 같은 정수배(또는 역수)면 분할. 1명이면 0.2% 이내로 정확해야 함."""
    ratios = [a["sh"] / a["psh"] for a in actions if a["psh"] > 0 and a["sh"] > 0]
    if not ratios:
        return None
    for k in SPLIT_KS:
        for kk in (k, 1 / k):
            if all(abs(x / kk - 1) < 0.02 for x in ratios) and (len(ratios) >= 2 or abs(ratios[0] / kk - 1) < 0.002):
                return k if kk >= 1 else -k
    return None


def classify(invs, raw):
    all_periods = sorted({p for r in raw.values() for p in r["periods"]}, reverse=True)
    out = {}
    for p in all_periods:
        stocks = defaultdict(lambda: {"actions": []})
        filed = []
        for inv in invs:
            r = raw.get(inv["id"])
            if not r or p not in r["periods"]:
                continue
            cur = r["periods"][p]
            pp = prev_quarter(p)                                 # 정확히 직전 분기가 있어야 비교
            prev = r["periods"][pp]["holdings"] if pp in r["periods"] else None
            total = sum(v["value"] for v in cur["holdings"].values()) or 1
            filed.append({"inv": inv["id"], "cik": cur.get("cik"), "filed": cur["filed"], "last_filed": cur["last_filed"],
                          "accs": cur["accs"], "n": len(cur["holdings"]), "aum": round(total), "has_prev": prev is not None})
            for c in set(cur["holdings"]) | set(prev or {}):
                h, ph = cur["holdings"].get(c), (prev or {}).get(c)
                sh, psh = (h or {}).get("shares", 0), (ph or {}).get("shares", 0)
                if h and not ph:
                    t = "new" if prev is not None else "first"   # first = 직전 13F 없음
                elif h and ph:
                    t = "add" if sh > psh * 1.0001 else ("reduce" if sh < psh * 0.9999 else "hold")
                else:
                    t = "sold"
                s = stocks[c]
                src = h or ph
                s.setdefault("name", src["name"])
                s.setdefault("cls", src["cls"])
                v = (h or {}).get("value", 0)
                s["actions"].append({"inv": inv["id"], "t": t, "sh": round(sh), "psh": round(psh), "v": round(v),
                                     "w": round(v / total * 100, 3), "f": (h or {}).get("f", cur["last_filed"])})
        for s in stocks.values():
            s["split"] = detect_split(s["actions"])
            if s["split"]:                                        # 분할 후보: 원래 분류는 t0에 보관(주가로 확인)
                for a in s["actions"]:
                    if a["t"] in ("add", "reduce"):
                        a["t0"], a["t"] = a["t"], "hold"
        out[p] = {"filed": filed, "stocks": [{"cusip": c, **v} for c, v in stocks.items()]}
    return out


def entry_date(stock):
    """시그널이 완전히 공개된 날 = 매도 아닌 행 공시일 중 가장 늦은 날."""
    ds = [a["f"] for a in stock["actions"] if a["t"] != "sold"]
    return max(ds) if ds else None


def buy_stocks(P, use_t0=True):
    """매수(new/add) 1명 이상 종목만. use_t0면 분할 후보의 원래 분류도 매수로 본다."""
    def buy(a):
        return a["t"] in BUY or (use_t0 and a.get("t0") in BUY)
    return {**P, "stocks": [s for s in P["stocks"] if any(buy(a) for a in s["actions"])]}
```

- [ ] **Step 4: 통과 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_classify.py` → Expected: `4 passed`

- [ ] **Step 5: 커밋**
```bash
git add radar/classify.py tests/test_classify.py
git commit -m "Classify quarter-over-quarter changes with split candidates"
```

---

### Task 6: CUSIP→티커 (OpenFIGI)

**Files:**
- Create: `radar/tickers.py`
- Test: `tests/test_tickers.py`

**Interfaces:**
- Produces: `pick_ticker(result)->str`, `map_tickers(cusips, post=requests.post, sleep=time.sleep, key=None, cache_path=FIGI_CACHE, log=print)->{cusip: ticker|""}`, `yf_sym(tk)->str`.

- [ ] **Step 1: 테스트 작성** — `tests/test_tickers.py`

```python
from radar.tickers import map_tickers, pick_ticker, yf_sym


class R:
    def __init__(self, code, js):
        self.status_code, self._js = code, js

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_pick_ticker_prefers_equity():
    res = {"data": [{"ticker": "X1", "marketSector": "Corp"}, {"ticker": "AAPL", "marketSector": "Equity"}]}
    assert pick_ticker(res) == "AAPL"
    assert pick_ticker({"warning": "No identifier found."}) == ""


def test_map_tickers_caches_hits_and_misses_but_not_errors(tmp_path):
    table = {"084670702": {"data": [{"ticker": "BRK/B", "marketSector": "Equity"}]},
             "000000000": {"warning": "No identifier found."}, "BADCUSIP1": {"error": "Invalid idValue"}}
    calls = []

    def post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        return R(200, [table[j["idValue"]] for j in json])

    cp = tmp_path / "map.json"
    m = map_tickers(["084670702", "000000000", "BADCUSIP1"], post=post, sleep=lambda s: None, key="k", cache_path=cp)
    assert m["084670702"] == "BRK/B" and m["000000000"] == "" and "BADCUSIP1" not in m
    m2 = map_tickers(["084670702"], post=post, sleep=lambda s: None, key="k", cache_path=cp)
    assert len(calls) == 1 and m2["084670702"] == "BRK/B"


def test_yf_sym():
    assert yf_sym("BRK/B") == "BRK-B" and yf_sym("bf.b") == "BF-B"
```

- [ ] **Step 2: 실패 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_tickers.py` → Expected: FAIL

- [ ] **Step 3: 구현** — `radar/tickers.py`

```python
"""CUSIP → 티커 (OpenFIGI, 캐시)."""
import json
import os
import time

import requests

from .config import FIGI_CACHE

FIGI_URL = "https://api.openfigi.com/v3/mapping"


def pick_ticker(result):
    data = result.get("data") or []
    eq = [d for d in data if d.get("marketSector") == "Equity"] or data
    return (eq[0].get("ticker") or "") if eq else ""


def _save(m, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m, ensure_ascii=False, indent=0, sort_keys=True))


def map_tickers(cusips, post=requests.post, sleep=time.sleep, key=None, cache_path=FIGI_CACHE, log=print):
    """없음(warning)은 ''로 캐시, 오류(error·네트워크)는 캐시하지 않아 다음 실행에서 재시도."""
    m = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    todo = sorted({c for c in cusips if c and c not in m})
    key = key if key is not None else os.environ.get("OPENFIGI_API_KEY", "").strip()
    batch, pause = (100, 0.3) if key else (10, 2.6)        # 무키: 25req/분, 요청당 10건
    hdr = {"Content-Type": "application/json", **({"X-OPENFIGI-APIKEY": key} if key else {})}
    for n, i in enumerate(range(0, len(todo), batch)):
        chunk = todo[i:i + batch]
        body = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in chunk]
        try:
            r = post(FIGI_URL, json=body, headers=hdr, timeout=30)
            if r.status_code == 429:
                sleep(60)
                r = post(FIGI_URL, json=body, headers=hdr, timeout=30)
            r.raise_for_status()
            for c, res in zip(chunk, r.json()):
                if "error" not in res:
                    m[c] = pick_ticker(res)
        except Exception as e:                              # 티커는 부가정보 → 실패해도 빌드는 계속
            log(f"OpenFIGI 실패: {e}")
            break
        if n % 20 == 19:
            _save(m, cache_path)                            # 긴 첫 실행 중단 대비
        sleep(pause)
    _save(m, cache_path)
    return m


def yf_sym(tk):
    return tk.replace("/", "-").replace(".", "-").strip().upper()
```

- [ ] **Step 4: 통과 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_tickers.py` → Expected: `3 passed`

- [ ] **Step 5: 커밋**
```bash
git add radar/tickers.py tests/test_tickers.py
git commit -m "Map CUSIPs to tickers via OpenFIGI with retry-safe cache"
```

---

### Task 7: 주가·가격 검증·종목 지표·환율·애널리스트

**Files:**
- Create: `radar/prices.py`
- Test: `tests/test_prices.py`

**Interfaces:**
- Consumes: `radar.dates.prev_quarter, quarter_start`.
- Produces: `FIELDS=["Adj Close","Close","Volume","Stock Splits"]`, `download(tickers, start, chunk=100, dl=None, sleep=time.sleep, log=print)` → generator of `{ticker: DataFrame[FIELDS]}`; `split_factor_after(frame, day)->float`; `raw_close_on(frame, date)->float|None`; `validate(frame, period_end, implied)->True|False|None`; `had_split(frame, p)->bool`; `stock_metrics(frame, entry, period_end, implied, fx=None)->dict(last,d,el,since,vol,hi52,lo52,ok,vwap,qlo,qhi,prem,krw)|None`; `fx_krw(dl=None)->{krw,d}|None`; `analyst_targets(tickers, cache_path, today, max_age=7, limit=250, ticker_cls=None, sleep=time.sleep, log=print)->{sym:{mean,median,n,rec,d}}`.

- [ ] **Step 1: 테스트 작성** — `tests/test_prices.py`

```python
import datetime as dt

import numpy as np
import pandas as pd

from radar.prices import analyst_targets, download, fx_krw, had_split, raw_close_on, stock_metrics, validate


def frame(dates, close, vol=None, splits=None):
    idx = pd.to_datetime(list(dates))
    n = len(idx)
    return pd.DataFrame({"Adj Close": close, "Close": close, "Volume": vol if vol is not None else [100.0] * n,
                         "Stock Splits": splits if splits is not None else [0.0] * n}, index=idx)


def test_raw_close_reverses_later_splits():
    f = frame(["2024-06-07", "2024-06-10", "2024-06-11"], [120.888, 121.79, 120.91], splits=[0, 10.0, 0])
    assert round(raw_close_on(f, "2024-06-07"), 2) == 1208.88
    assert round(raw_close_on(f, "2024-06-09"), 2) == 1208.88      # 주말 → 직전 거래일
    assert round(raw_close_on(f, "2024-06-11"), 2) == 120.91


def test_validate_ranges():
    f = frame(["2026-06-29", "2026-06-30"], [99.0, 100.0])
    assert validate(f, "2026-06-30", 120.0) is True
    assert validate(f, "2026-06-30", 130.0) is False
    assert validate(f, "2026-06-30", None) is None
    assert validate(f, "2025-01-01", 100.0) is None                  # 해당 시점 가격 없음


def test_had_split_within_quarter():
    f = frame(["2026-03-31", "2026-05-01", "2026-07-01"], [1.0, 1.0, 1.0], splits=[0, 4.0, 0])
    assert had_split(f, "2026-06-30") is True
    assert had_split(f, "2026-09-30") is False


def test_stock_metrics_vwap_premium_and_elapsed():
    dates = pd.bdate_range("2026-01-02", "2026-09-22")
    close = np.linspace(50, 100, len(dates))
    f = frame(dates, close, vol=[1000.0] * len(dates))
    imp = float(f.loc["2026-06-30", "Close"])
    m = stock_metrics(f, "2026-08-14", "2026-06-30", imp, {"krw": 1400.0, "d": "2026-09-22"})
    q = f.loc["2026-04-01":"2026-06-30", "Close"]
    assert m["last"] == round(close[-1], 2) and m["d"] == "2026-09-22"
    assert abs(m["vwap"] - q.mean()) < 0.01 and m["qlo"] == round(q.min(), 2) and m["qhi"] == round(q.max(), 2)
    assert abs(m["prem"] - (close[-1] / q.mean() - 1)) < 1e-3
    assert m["el"] == int((dates > pd.Timestamp("2026-08-14")).sum()) - 1
    assert m["ok"] is True and m["krw"] == round(close[-1] * 1400)
    assert m["hi52"] == round(close[-1], 2) and m["vol"] is not None


def test_download_yields_per_ticker_frames():
    idx = pd.to_datetime(["2026-09-21", "2026-09-22"])
    cols = pd.MultiIndex.from_product([["AAA", "BBB"], ["Adj Close", "Close", "Dividends", "High", "Low", "Open", "Stock Splits", "Volume"]])
    df = pd.DataFrame(np.ones((2, len(cols))), index=idx, columns=cols)
    df[("BBB", "Close")] = np.nan
    chunks = list(download(["AAA", "BBB"], "2026-01-01", dl=lambda *a, **k: df, sleep=lambda s: None))
    assert list(chunks[0]) == ["AAA"]
    assert list(chunks[0]["AAA"].columns) == ["Adj Close", "Close", "Volume", "Stock Splits"]


def test_fx_krw_reads_last_close():
    idx = pd.to_datetime(["2026-09-21", "2026-09-22"])
    df = pd.DataFrame({("KRW=X", "Close"): [1384.86, 1358.88]}, index=idx)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    assert fx_krw(dl=lambda *a, **k: df) == {"krw": 1358.88, "d": "2026-09-22"}
    assert fx_krw(dl=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))) is None


def test_analyst_targets_uses_7day_cache(tmp_path):
    class T:
        n = 0

        def __init__(self, t):
            T.n += 1
            self.info = {"targetMeanPrice": 80.0, "targetMedianPrice": 75.0, "numberOfAnalystOpinions": 13,
                         "recommendationKey": "hold"}

    cp, today = tmp_path / "an.json", dt.date(2026, 9, 22)
    a = analyst_targets(["LEN"], cp, today, ticker_cls=T, sleep=lambda s: None)
    assert a["LEN"]["mean"] == 80.0 and a["LEN"]["n"] == 13 and T.n == 1
    analyst_targets(["LEN"], cp, today + dt.timedelta(days=3), ticker_cls=T, sleep=lambda s: None)
    assert T.n == 1
```

- [ ] **Step 2: 실패 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_prices.py` → Expected: FAIL

- [ ] **Step 3: 구현** — `radar/prices.py`

```python
"""주가(yfinance): 청크 다운로드, 원시가격 복원·가격 검증, 표시 지표, 환율, 애널리스트 목표가."""
import datetime as dt
import json
import time

import numpy as np
import pandas as pd

from .dates import prev_quarter, quarter_start

FIELDS = ["Adj Close", "Close", "Volume", "Stock Splits"]


def _yf():
    import yfinance as yf
    return yf


def download(tickers, start, chunk=100, dl=None, sleep=time.sleep, log=print):
    """{티커: DataFrame(FIELDS)}를 청크마다 yield. Close=분할 반영, Adj Close=분할+배당 반영."""
    dl = dl or _yf().download
    tickers = sorted({t for t in tickers if t})
    for i in range(0, len(tickers), chunk):
        part, df = tickers[i:i + chunk], None
        for attempt in range(2):
            try:
                df = dl(part, start=start, auto_adjust=False, actions=True, group_by="ticker",
                        progress=False, threads=True)
                break
            except Exception as e:
                log(f"yfinance 실패({attempt + 1}/2): {e}")
                sleep(5)
        out = {}
        if df is not None and len(df):
            for t in part:
                try:
                    sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
                except KeyError:
                    continue
                sub = sub.reindex(columns=FIELDS)
                sub = sub[sub["Close"].notna()]
                if len(sub):
                    sub = sub.copy()
                    sub.index = pd.to_datetime(sub.index).tz_localize(None).normalize()
                    out[t] = sub.sort_index()
        yield out
        sleep(1)


def split_factor_after(frame, day):
    s = frame["Stock Splits"].fillna(0)
    s = s[(s.index > pd.Timestamp(day)) & (s > 0)]
    return float(np.prod(s.to_numpy())) if len(s) else 1.0


def raw_close_on(frame, date):
    """date 이전(포함) 마지막 거래일의 당시 원시 종가 = Close × 이후 분할 비율 곱."""
    c = frame["Close"].loc[:pd.Timestamp(date)].dropna()
    if c.empty or (pd.Timestamp(date) - c.index[-1]).days > 7:
        return None
    return float(c.iloc[-1]) * split_factor_after(frame, c.index[-1])


def validate(frame, period_end, implied):
    """13F 내재가격(평가액/주식수)과 분기말 원시가격 비율이 0.8~1.25면 True. 판단 불가면 None."""
    raw = raw_close_on(frame, period_end)
    if not raw or not implied or implied <= 0:
        return None
    return bool(0.8 <= implied / raw <= 1.25)


def had_split(frame, p):
    s = frame["Stock Splits"].fillna(0)
    m = (s.index > pd.Timestamp(prev_quarter(p))) & (s.index <= pd.Timestamp(p)) & (s > 0)
    return bool(m.any())


def _r(x, n):
    return None if x is None else round(float(x), n)


def stock_metrics(frame, entry, period_end, implied, fx=None):
    close = frame["Close"].dropna()
    if close.empty:
        return None
    adj = frame["Adj Close"].dropna()
    last, idx = float(close.iloc[-1]), adj.index
    i0 = int(idx.searchsorted(pd.Timestamp(entry), side="right")) if entry else len(idx)
    lr = np.log(adj).diff().dropna().iloc[-252:]
    yr = close.iloc[-252:]
    q = frame.loc[pd.Timestamp(quarter_start(period_end)):pd.Timestamp(period_end)]
    q = q[q["Close"].notna()]
    qv = q["Volume"].fillna(0)
    vwap = (float((q["Close"] * qv).sum() / qv.sum()) if qv.sum() > 0 else float(q["Close"].mean())) if len(q) else None
    return {"last": round(last, 2), "d": close.index[-1].date().isoformat(),
            "el": max(0, len(idx) - 1 - i0) if i0 < len(idx) else 0,
            "since": _r(adj.iloc[-1] / adj.iloc[i0] - 1, 4) if i0 < len(idx) else None,
            "vol": _r(lr.std() * np.sqrt(252), 4) if len(lr) > 60 else None,
            "hi52": _r(yr.max(), 2), "lo52": _r(yr.min(), 2),
            "ok": validate(frame, period_end, implied),
            "vwap": _r(vwap, 2), "qlo": _r(q["Close"].min(), 2) if len(q) else None,
            "qhi": _r(q["Close"].max(), 2) if len(q) else None,
            "prem": _r(last / vwap - 1, 4) if vwap else None,
            "krw": round(last * fx["krw"]) if fx else None}


def fx_krw(dl=None):
    try:
        df = (dl or _yf().download)(["KRW=X"], period="10d", auto_adjust=False, group_by="ticker", progress=False)
        c = df["KRW=X"]["Close"].dropna()
        return {"krw": round(float(c.iloc[-1]), 2), "d": c.index[-1].date().isoformat()}
    except Exception:
        return None


def analyst_targets(tickers, cache_path, today, max_age=7, limit=250, ticker_cls=None, sleep=time.sleep, log=print):
    """yfinance info의 애널리스트 목표가. 7일 캐시, 실행당 최대 limit개, 연속 5회 실패 시 중단."""
    ticker_cls = ticker_cls or _yf().Ticker
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    def fresh(e):
        return bool(e) and (today - dt.date.fromisoformat(e["d"])).days < max_age

    fails = 0
    for t in [t for t in sorted(set(tickers)) if not fresh(cache.get(t))][:limit]:
        try:
            info = ticker_cls(t).info or {}
            cache[t] = {"mean": info.get("targetMeanPrice"), "median": info.get("targetMedianPrice"),
                        "n": info.get("numberOfAnalystOpinions"), "rec": info.get("recommendationKey"),
                        "d": today.isoformat()}
            fails = 0
        except Exception as e:
            fails += 1
            log(f"애널리스트 목표가 실패 {t}: {e}")
            if fails >= 5:
                log("애널리스트 목표가: 연속 실패로 중단")
                break
        sleep(0.4)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True))
    return {t: cache[t] for t in tickers if cache.get(t) and cache[t].get("mean")}
```

- [ ] **Step 4: 통과 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_prices.py` → Expected: `7 passed`

- [ ] **Step 5: 커밋**
```bash
git add radar/prices.py tests/test_prices.py
git commit -m "Add price download, split-aware validation, stock metrics, FX and analyst targets"
```

---

### Task 8: 백테스트(이벤트·선행수익률·압축 저장)

**Files:**
- Create: `radar/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `classify.BUY/HOLD/entry_date`, `prices.validate`, `tickers.yf_sym`, config `BT_FILE, HORIZONS, K_GRID, OFFSETS`.
- Produces: `make_events(periods, tick)->[{p,c,tk,e,hn,imp,b:[[inv,"n"|"a"]]}]`, `forward_returns(events, frames_iter, spy)->spy_rows` (이벤트에 R·si·st 설정), `permille(xs)->list`, `run_backtest(periods, tick, download_fn, today, inv_ids, full=False, bt_file=BT_FILE, log=print)->bt|None`. bt 형식: `{built,K,H,O,P,I,stats{total,nopx,mismatch,used},ev:[[P인덱스, 티커, [투자자인덱스*2+신규], 보유자수, R퍼밀(뒤쪽 null 제거), spy인덱스]], spy:[퍼밀 행]}`.

- [ ] **Step 1: 테스트 작성** — `tests/test_backtest.py`

```python
import datetime as dt

import numpy as np
import pandas as pd

from radar.backtest import forward_returns, make_events, permille, run_backtest
from radar.config import OFFSETS


def test_make_events_requires_buyer_and_two_holders():
    periods = {"2026-03-31": {"stocks": [
        {"cusip": "A", "split": None, "actions": [
            {"inv": "buffett", "t": "new", "sh": 10, "psh": 0, "v": 1000, "f": "2026-05-15"},
            {"inv": "gates", "t": "hold", "sh": 30, "psh": 30, "v": 3000, "f": "2026-05-10"}]},
        {"cusip": "B", "split": None, "actions": [{"inv": "buffett", "t": "add", "sh": 10, "psh": 5, "v": 1000, "f": "2026-05-15"}]},
        {"cusip": "C", "split": 2, "actions": [
            {"inv": "buffett", "t": "hold", "sh": 10, "psh": 5, "v": 1000, "f": "2026-05-15"},
            {"inv": "gates", "t": "hold", "sh": 10, "psh": 5, "v": 1000, "f": "2026-05-15"}]}]}}
    ev = make_events(periods, {"A": "AAA"})
    assert len(ev) == 1
    e = ev[0]
    assert (e["tk"], e["e"], e["hn"], e["b"], e["imp"]) == ("AAA", "2026-05-15", 2, [["buffett", "n"]], 100.0)


def _frame(cal, px):
    return pd.DataFrame({"Adj Close": px, "Close": px, "Volume": 1.0, "Stock Splits": 0.0}, index=cal)


def test_forward_returns_next_day_entry_and_validation():
    cal = pd.bdate_range("2026-03-02", periods=400)
    spy = pd.Series(np.linspace(100, 140, len(cal)), index=cal)
    px = np.linspace(10, 30, len(cal))
    good = _frame(cal, px)
    imp = float(good.loc["2026-03-31", "Close"])
    e_ok = {"p": "2026-03-31", "tk": "AAA", "e": "2026-05-15", "imp": imp}
    e_bad = {"p": "2026-03-31", "tk": "BBB", "e": "2026-05-15", "imp": 999.0}
    e_none = {"p": "2026-03-31", "tk": "CCC", "e": "2026-05-15", "imp": 10.0}
    spy_rows = forward_returns([e_ok, e_bad, e_none], iter([{"AAA": good, "BBB": good}]), spy)
    assert (e_ok["st"], e_bad["st"], e_none["st"]) == ("ok", "mismatch", "nopx")
    i0, j = int(cal.searchsorted(pd.Timestamp("2026-05-15"), side="right")), OFFSETS.index(21)
    assert e_ok["R"][0] == 0.0 and e_ok["R"][j] == round(px[i0 + 21] / px[i0] - 1, 3)
    assert spy_rows[e_ok["si"]][j] == round(spy.iloc[i0 + 21] / spy.iloc[i0] - 1, 3)
    assert e_ok["R"][OFFSETS.index(1260)] is None


def test_forward_returns_skips_zero_entry_price():
    cal = pd.bdate_range("2026-03-02", periods=300)
    spy = pd.Series(np.linspace(100, 140, len(cal)), index=cal)
    px = np.linspace(10, 30, len(cal))
    px[int(cal.searchsorted(pd.Timestamp("2026-05-15"), side="right"))] = 0.0     # 진입일 가격 0
    fr = _frame(cal, px)
    e = {"p": "2026-03-31", "tk": "AAA", "e": "2026-05-15", "imp": float(fr.loc["2026-03-31", "Close"])}
    forward_returns([e], iter([{"AAA": fr}]), spy)
    assert e["st"] == "nopx" and e["R"] is None


def test_permille_trims_trailing_nulls():
    assert permille([0.0, 0.1234, None, -0.05, None, None]) == [0, 123, None, -50]


def test_run_backtest_compact_encoding(tmp_path):
    cal = pd.bdate_range("2026-03-02", periods=400)
    fr = _frame(cal, np.linspace(10, 30, len(cal)))
    v = float(fr.loc["2026-03-31", "Close"]) * 10
    periods = {"2026-03-31": {"stocks": [{"cusip": "A", "split": None, "actions": [
        {"inv": "buffett", "t": "new", "sh": 10, "psh": 0, "v": v, "f": "2026-05-15"},
        {"inv": "gates", "t": "hold", "sh": 10, "psh": 10, "v": v, "f": "2026-05-10"}]}]}}

    def dl(tickers, start):
        yield {t: fr for t in tickers}

    bt = run_backtest(periods, {"A": "AAA"}, dl, dt.date(2026, 9, 23), ["buffett", "gates"], full=True,
                      bt_file=tmp_path / "bt.json")
    assert bt["P"] == ["2026-03-31"] and bt["I"] == ["buffett", "gates"]
    e = bt["ev"][0]
    assert e[:4] == [0, "AAA", [1], 2] and e[4][0] == 0 and e[5] == 0
    assert bt["stats"] == {"total": 1, "nopx": 0, "mismatch": 0, "used": 1}
    assert (tmp_path / "bt.json").exists()
```

- [ ] **Step 2: 실패 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_backtest.py` → Expected: FAIL

- [ ] **Step 3: 구현** — `radar/backtest.py`

```python
"""과거 시그널 이벤트 → 공시 다음 거래일 매수 기준 선행수익률(가격 검증 통과분만)."""
import json
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from .classify import BUY, HOLD, entry_date
from .config import BT_FILE, HORIZONS, K_GRID, OFFSETS
from .prices import validate
from .tickers import yf_sym


def make_events(periods, tick):
    """표본: 분할 아닌 종목 중 매수 1명+ 이고 보유자(매수 포함) 2명+."""
    ev = []
    for p, P in periods.items():
        for s in P["stocks"]:
            if s.get("split"):
                continue
            b = [a for a in s["actions"] if a["t"] in BUY]
            h = [a for a in s["actions"] if a["t"] in HOLD]
            if not b or len(h) < 2:
                continue
            held = [a for a in s["actions"] if a["sh"] > 0]
            sh = sum(a["sh"] for a in held)
            ev.append({"p": p, "c": s["cusip"], "tk": tick.get(s["cusip"], ""), "e": entry_date(s), "hn": len(h),
                       "imp": sum(a["v"] for a in held) / sh if sh else None,
                       "b": [[a["inv"], "n" if a["t"] == "new" else "a"] for a in b]})
    return ev


def forward_returns(events, frames_iter, spy):
    """이벤트마다 R(OFFSETS 거래일 누적수익률), si(SPY 행 번호), st(ok/mismatch/nopx) 설정."""
    cal = spy.index
    sv = spy.to_numpy(dtype=float)
    spy_rows, spy_idx, by_sym = [], {}, defaultdict(list)
    for e in events:
        e.update(R=None, si=None, st="nopx")
        if e["tk"]:
            by_sym[yf_sym(e["tk"])].append(e)
    for chunk in frames_iter:
        for sym, fr in chunk.items():
            evs = by_sym.get(sym)
            if not evs:
                continue
            adj = fr["Adj Close"].reindex(cal).ffill(limit=5).to_numpy(dtype=float)
            for e in evs:
                ok = validate(fr, e["p"], e["imp"])
                if ok is not True:
                    e["st"] = "mismatch" if ok is False else "nopx"
                    continue
                i0 = int(cal.searchsorted(pd.Timestamp(e["e"]), side="right"))
                if i0 >= len(cal) or not np.isfinite(adj[i0]) or adj[i0] <= 0:   # 0이면 수익률이 NaN/Inf
                    continue
                e["R"] = [round(float(adj[i0 + o] / adj[i0] - 1), 3)
                          if i0 + o < len(cal) and np.isfinite(adj[i0 + o]) else None for o in OFFSETS]
                if i0 not in spy_idx:
                    spy_idx[i0] = len(spy_rows)
                    spy_rows.append([round(float(sv[i0 + o] / sv[i0] - 1), 3) if i0 + o < len(cal) else None
                                     for o in OFFSETS])
                e["si"], e["st"] = spy_idx[i0], "ok"
    return spy_rows


def permille(xs):
    out = [None if x is None else int(round(x * 1000)) for x in xs]
    while out and out[-1] is None:
        out.pop()
    return out


def run_backtest(periods, tick, download_fn, today, inv_ids, full=False, bt_file=BT_FILE, log=print):
    if not full and bt_file.exists():
        return json.loads(bt_file.read_text(encoding="utf-8"))
    ev = make_events(periods, tick)
    first = min((e["e"] for e in ev if e["e"]), default="2013-08-01")
    spy_fr = {}
    for chunk in download_fn(["SPY"], first):
        spy_fr.update(chunk)
    if "SPY" not in spy_fr:
        log("SPY 가격을 못 받아 백테스트 생략")
        return json.loads(bt_file.read_text(encoding="utf-8")) if bt_file.exists() else None
    spy = spy_fr["SPY"]["Adj Close"].dropna()
    spy_rows = forward_returns(ev, download_fn(sorted({yf_sym(e["tk"]) for e in ev if e["tk"]}), first), spy)
    st = Counter(e["st"] for e in ev)
    ii = {x: i for i, x in enumerate(inv_ids)}
    ok = [e for e in ev if e["st"] == "ok" and all(i in ii for i, _ in e["b"])]
    P = sorted({e["p"] for e in ok})
    pi = {p: i for i, p in enumerate(P)}
    bt = {"built": today.isoformat(), "K": K_GRID, "H": HORIZONS, "O": OFFSETS, "P": P, "I": list(inv_ids),
          "stats": {"total": len(ev), "nopx": st["nopx"], "mismatch": st["mismatch"], "used": len(ok)},
          "ev": [[pi[e["p"]], e["tk"], [ii[i] * 2 + (t == "n") for i, t in e["b"]], e["hn"], permille(e["R"]), e["si"]]
                 for e in ok],
          "spy": [permille(r) for r in spy_rows]}
    bt_file.parent.mkdir(parents=True, exist_ok=True)
    bt_file.write_text(json.dumps(bt, separators=(",", ":")), encoding="utf-8")
    log(f"백테스트: {bt['stats']}")
    return bt
```

- [ ] **Step 4: 통과 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_backtest.py` → Expected: `5 passed`

- [ ] **Step 5: 커밋**
```bash
git add radar/backtest.py tests/test_backtest.py
git commit -m "Add streaming event-study backtest with price validation and compact output"
```

---

### Task 9: 표시 종목 지표 채우기

**Files:**
- Create: `radar/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `classify.entry_date`, `prices.had_split/stock_metrics`, `tickers.yf_sym`.
- Produces: `implied_price(stock)->float|None`, `display_metrics(show, tick, download_fn, fx, today, extra=(), log=print)->{"price_date": str|None, "quotes": {sym: last}}` (각 종목에 `tk`, `px` 설정, 가격상 분할이 없으면 `t0` 복원·`split=None`).

- [ ] **Step 1: 테스트 작성** — `tests/test_metrics.py`

```python
import datetime as dt

import numpy as np
import pandas as pd

from radar.metrics import display_metrics, implied_price


def test_display_metrics_fills_px_and_reverts_unconfirmed_split():
    cal = pd.bdate_range("2026-01-02", "2026-09-22")
    px = np.linspace(50, 100, len(cal))
    fr = pd.DataFrame({"Adj Close": px, "Close": px, "Volume": 1000.0, "Stock Splits": 0.0}, index=cal)
    imp = float(fr.loc["2026-06-30", "Close"])
    show = {"2026-06-30": {"filed": [], "stocks": [
        {"cusip": "A", "name": "A", "cls": "COM", "split": 2, "actions": [
            {"inv": "buffett", "t": "hold", "t0": "add", "sh": 20, "psh": 10, "v": imp * 20, "f": "2026-08-14"}]}]}}

    def dl(tickers, start):
        yield {t: fr for t in tickers}

    res = display_metrics(show, {"A": "AAA"}, dl, {"krw": 1400.0, "d": "2026-09-22"}, dt.date(2026, 9, 23),
                          extra={"LEN"}, log=lambda *a: None)
    s = show["2026-06-30"]["stocks"][0]
    assert s["split"] is None and s["actions"][0]["t"] == "add" and "t0" not in s["actions"][0]
    assert s["tk"] == "AAA" and s["px"]["ok"] is True
    assert res["price_date"] == "2026-09-22" and res["quotes"]["AAA"] == 100.0 and "LEN" in res["quotes"]


def test_implied_price_ignores_sold():
    s = {"actions": [{"sh": 10, "v": 1000}, {"sh": 30, "v": 3000}, {"sh": 0, "v": 0}]}
    assert implied_price(s) == 100.0
    assert implied_price({"actions": [{"sh": 0, "v": 0}]}) is None
```

- [ ] **Step 2: 실패 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_metrics.py` → Expected: FAIL

- [ ] **Step 3: 구현** — `radar/metrics.py`

```python
"""화면 표시 종목: 현재가·경과일·변동성·52주·추정 매입가·가격 검증 + 분할 후보를 주가로 확인."""
import datetime as dt
from collections import defaultdict

from .classify import entry_date
from .prices import had_split, stock_metrics
from .tickers import yf_sym


def implied_price(s):
    held = [a for a in s["actions"] if a["sh"] > 0]
    sh = sum(a["sh"] for a in held)
    return sum(a["v"] for a in held) / sh if sh else None


def display_metrics(show, tick, download_fn, fx, today, extra=(), log=print):
    by_sym = defaultdict(list)
    for p, P in show.items():
        for s in P["stocks"]:
            s["tk"], s["px"] = tick.get(s["cusip"], ""), None
            if s["tk"]:
                by_sym[yf_sym(s["tk"])].append((p, s))
    syms = sorted(set(by_sym) | set(extra) | {"SPY"})
    start = (today - dt.timedelta(days=560)).isoformat()
    price_date, quotes = None, {}
    for chunk in download_fn(syms, start):
        for sym, fr in chunk.items():
            close = fr["Close"].dropna()
            if close.empty:
                continue
            quotes[sym] = round(float(close.iloc[-1]), 2)
            if sym == "SPY":
                price_date = close.index[-1].date().isoformat()
            for p, s in by_sym.get(sym, []):
                if s.get("split") and not had_split(fr, p):        # 주가에 분할 없음 → 원래 분류 복원
                    for a in s["actions"]:
                        if "t0" in a:
                            a["t"] = a.pop("t0")
                    s["split"] = None
                s["px"] = stock_metrics(fr, entry_date(s), p, implied_price(s), fx)
    log(f"현재가: {len(quotes)}/{len(syms)}개 심볼")
    return {"price_date": price_date, "quotes": quotes}
```

- [ ] **Step 4: 통과 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_metrics.py` → Expected: `2 passed`

- [ ] **Step 5: 커밋**
```bash
git add radar/metrics.py tests/test_metrics.py
git commit -m "Fill display metrics and confirm split candidates with price data"
```

---

### Task 10: 수시 공시(Form 4·13D·13G)

**Files:**
- Create: `radar/filings.py`, `tests/fixtures/form4.xml`, `tests/fixtures/schedule13g.xml`, `tests/fixtures/schedule13d.xml`
- Test: `tests/test_filings.py`

**Interfaces:**
- Consumes: `edgar.strip_ns/txt/num`, config `CACHE, FILINGS_DAYS`.
- Produces: `parse_form4(bytes)->{issuer_cik,name,symbols,tx[]}`, `summarize_form4(d)->[{kind,sh,px,post,date,title}]`, `parse_schedule13(bytes)->{issuer_cik,name,cusip,form,amend,event,sh,pct}`, `pick_symbol(symbols, title)->str`, `raw_doc_name(doc)->str`, `recent_filings(sec, inv_subs, own, today, days=90, limit=300)->[{d,inv,form,acc,cik,name,kind,tk,cusip,sh,px,val,post,pct,td}]`.

- [ ] **Step 1: fixture 작성** (실제 공시 축약)

`tests/fixtures/form4.xml`:
```xml
<?xml version="1.0"?>
<ownershipDocument><schemaVersion>X0609</schemaVersion><documentType>4</documentType><periodOfReport>2026-09-17</periodOfReport>
<issuer><issuerCik>0000920760</issuerCik><issuerName>LENNAR CORP /NEW/</issuerName><issuerTradingSymbol>LEN, LEN.B</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerCik>0001067983</rptOwnerCik><rptOwnerName>BERKSHIRE HATHAWAY INC</rptOwnerName></reportingOwnerId></reportingOwner>
<nonDerivativeTable>
<nonDerivativeTransaction><securityTitle><value>Class A Common Stock</value></securityTitle><transactionDate><value>2026-09-17</value></transactionDate><transactionCoding><transactionFormType>4</transactionFormType><transactionCode>P</transactionCode></transactionCoding><transactionAmounts><transactionShares><value>267585</value></transactionShares><transactionPricePerShare><value>78.41</value></transactionPricePerShare><transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts><postTransactionAmounts><sharesOwnedFollowingTransaction><value>21318186</value></sharesOwnedFollowingTransaction></postTransactionAmounts></nonDerivativeTransaction>
<nonDerivativeTransaction><securityTitle><value>Class A Common Stock</value></securityTitle><transactionDate><value>2026-09-18</value></transactionDate><transactionCoding><transactionFormType>4</transactionFormType><transactionCode>P</transactionCode></transactionCoding><transactionAmounts><transactionShares><value>100000</value></transactionShares><transactionPricePerShare><value>80.00</value></transactionPricePerShare><transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts><postTransactionAmounts><sharesOwnedFollowingTransaction><value>21418186</value></sharesOwnedFollowingTransaction></postTransactionAmounts></nonDerivativeTransaction>
<nonDerivativeTransaction><securityTitle><value>Class A Common Stock</value></securityTitle><transactionDate><value>2026-09-18</value></transactionDate><transactionCoding><transactionFormType>4</transactionFormType><transactionCode>G</transactionCode></transactionCoding><transactionAmounts><transactionShares><value>500</value></transactionShares><transactionPricePerShare><value>0</value></transactionPricePerShare><transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts><postTransactionAmounts><sharesOwnedFollowingTransaction><value>21417686</value></sharesOwnedFollowingTransaction></postTransactionAmounts></nonDerivativeTransaction>
</nonDerivativeTable></ownershipDocument>
```

`tests/fixtures/schedule13g.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13g"><headerData><submissionType>SCHEDULE 13G</submissionType><filerInfo><filer><filerCredentials><cik>0001067983</cik></filerCredentials></filer></filerInfo></headerData>
<formData><coverPageHeader><securitiesClassTitle>Common Stock, par value $.10</securitiesClassTitle><eventDateRequiresFilingThisStatement>06/30/2026</eventDateRequiresFilingThisStatement><issuerInfo><issuerCik>0000920760</issuerCik><issuerName>LENNAR CORPORATION</issuerName><issuerCusips><issuerCusipNumber>526057104</issuerCusipNumber></issuerCusips></issuerInfo></coverPageHeader>
<coverPageHeaderReportingPersonDetails><reportingPersonName>Warren E. Buffett</reportingPersonName><reportingPersonBeneficiallyOwnedAggregateNumberOfShares>13111741</reportingPersonBeneficiallyOwnedAggregateNumberOfShares><classPercent>6.2</classPercent></coverPageHeaderReportingPersonDetails>
<coverPageHeaderReportingPersonDetails><reportingPersonName>Berkshire Hathaway Inc.</reportingPersonName><reportingPersonBeneficiallyOwnedAggregateNumberOfShares>13111741</reportingPersonBeneficiallyOwnedAggregateNumberOfShares><classPercent>6.2</classPercent></coverPageHeaderReportingPersonDetails>
</formData></edgarSubmission>
```

`tests/fixtures/schedule13d.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13D"><headerData><submissionType>SCHEDULE 13D/A</submissionType></headerData>
<formData><coverPageHeader><amendmentNo>81</amendmentNo><securitiesClassTitle>Class A Common Stock</securitiesClassTitle><dateOfEvent>07/14/2026</dateOfEvent><issuerInfo><issuerCIK>0001067983</issuerCIK><issuerCusips><issuerCusipNumber>084670108</issuerCusipNumber></issuerCusips><issuerName>Berkshire Hathaway Inc.</issuerName></issuerInfo></coverPageHeader>
<reportingPersons><reportingPersonInfo><reportingPersonName>Warren E. Buffett</reportingPersonName><aggregateAmountOwned>188290</aggregateAmountOwned><percentOfClass>38.2</percentOfClass></reportingPersonInfo></reportingPersons></formData></edgarSubmission>
```

- [ ] **Step 2: 테스트 작성** — `tests/test_filings.py`

```python
import datetime as dt
from pathlib import Path

from fakes import FakeSec
from radar import filings
from radar.filings import parse_form4, parse_schedule13, pick_symbol, recent_filings, summarize_form4

FX = Path(__file__).parent / "fixtures"


def test_parse_and_summarize_form4():
    d = parse_form4((FX / "form4.xml").read_bytes())
    assert d["issuer_cik"] == "0000920760" and d["symbols"] == "LEN, LEN.B" and len(d["tx"]) == 3
    s = summarize_form4(d)
    assert len(s) == 1 and s[0]["kind"] == "buy" and s[0]["sh"] == 367585
    assert abs(s[0]["px"] - (267585 * 78.41 + 100000 * 80.0) / 367585) < 1e-3
    assert s[0]["post"] == 21418186 and s[0]["date"] == "2026-09-18"
    assert pick_symbol(d["symbols"], "Class A Common Stock") == "LEN"
    assert pick_symbol(d["symbols"], "Class B Common Stock") == "LEN.B"


def test_summarize_form4_splits_share_classes():
    d = {"issuer_cik": "0000920760", "name": "LENNAR", "symbols": "LEN, LEN.B",
         "tx": [{"code": "P", "date": "2026-09-17", "title": "Class A Common Stock", "sh": 100.0, "px": 80.0, "post": 900.0},
                {"code": "P", "date": "2026-09-18", "title": "Class B Common Stock", "sh": 50.0, "px": 70.0, "post": 500.0},
                {"code": "P", "date": "2026-09-19", "title": "Class A Common Stock", "sh": 100.0, "px": 82.0, "post": 1000.0}]}
    rows = summarize_form4(d)
    assert [(r["title"], r["sh"], r["post"]) for r in rows] == [
        ("Class A Common Stock", 200.0, 1000.0), ("Class B Common Stock", 50.0, 500.0)]
    assert rows[0]["px"] == 81.0
    assert pick_symbol(d["symbols"], rows[0]["title"]) == "LEN" and pick_symbol(d["symbols"], rows[1]["title"]) == "LEN.B"


def test_summarize_form4_uses_last_same_day_transaction_for_post():
    d = {"issuer_cik": "0000920760", "name": "X", "symbols": "LEN",
         "tx": [{"code": "P", "date": "2026-09-18", "title": "COM", "sh": 100.0, "px": 10.0, "post": 1100.0},
                {"code": "P", "date": "2026-09-18", "title": "COM", "sh": 100.0, "px": 12.0, "post": 1300.0}]}
    s = summarize_form4(d)[0]
    assert s["post"] == 1300.0 and s["sh"] == 200.0 and s["px"] == 11.0


def test_parse_schedule13g_and_13d():
    g = parse_schedule13((FX / "schedule13g.xml").read_bytes())
    assert g == {"issuer_cik": "0000920760", "name": "LENNAR CORPORATION", "cusip": "526057104", "form": "SCHEDULE 13G",
                 "amend": "", "event": "06/30/2026", "sh": 13111741.0, "pct": 6.2}
    d = parse_schedule13((FX / "schedule13d.xml").read_bytes())
    assert (d["issuer_cik"], d["amend"], d["pct"], d["sh"]) == ("0001067983", "81", 38.2, 188290.0)


def test_recent_filings_filters_window_forms_and_self_issuer(tmp_path, monkeypatch):
    monkeypatch.setattr(filings, "CACHE", tmp_path)
    cik = "0001067983"

    def url(acc, name):
        return f"https://www.sec.gov/Archives/edgar/data/1067983/{acc.replace('-', '')}/{name}"

    routes = {url("0001-26-000010", "ownership.xml"): (FX / "form4.xml").read_bytes(),
              url("0001-26-000011", "primary_doc.xml"): (FX / "schedule13g.xml").read_bytes(),
              url("0001-26-000012", "primary_doc.xml"): (FX / "schedule13d.xml").read_bytes()}
    rows = [{"acc": "0001-26-000010", "form": "4", "filed": "2026-09-21", "period": "", "doc": "xslF345X06/ownership.xml"},
            {"acc": "0001-26-000011", "form": "SCHEDULE 13G", "filed": "2026-08-14", "period": "", "doc": "xslSCHEDULE_13G_X02/primary_doc.xml"},
            {"acc": "0001-26-000012", "form": "SCHEDULE 13D/A", "filed": "2026-07-15", "period": "", "doc": "xslSCHEDULE_13D_X02/primary_doc.xml"},
            {"acc": "0001-26-000013", "form": "4", "filed": "2026-01-02", "period": "", "doc": "x/ownership.xml"},
            {"acc": "0001-26-000014", "form": "8-K", "filed": "2026-09-01", "period": "", "doc": "d.htm"}]
    out = recent_filings(FakeSec(routes), [("buffett", cik, rows)], {"buffett": {cik}}, dt.date(2026, 9, 23))
    assert [(o["form"], o["kind"]) for o in out] == [("4", "buy"), ("SCHEDULE 13G", "stake")]
    assert out[0]["tk"] == "LEN" and out[0]["sh"] == 367585 and out[0]["val"] == round(367585 * out[0]["px"])
    assert out[1]["cusip"] == "526057104" and out[1]["pct"] == 6.2
    assert (tmp_path / "f_0001-26-000010.json").exists()
```

- [ ] **Step 3: 실패 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_filings.py` → Expected: FAIL

- [ ] **Step 4: 구현** — `radar/filings.py`

```python
"""추적 투자자의 최근 Form 4(장내 매수·매도)와 Schedule 13D/13G(5%+ 지분) 공시."""
import datetime as dt
import json
import re
import xml.etree.ElementTree as ET

from .config import CACHE, FILINGS_DAYS
from .edgar import num, strip_ns, txt

F4 = ("4", "4/A")
SCHED = ("SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A")   # 2024-12 이후 XML 형식


def raw_doc_name(doc):
    """'xslF345X06/ownership.xml' → 'ownership.xml' (XSL 렌더링 경로 제거)."""
    return doc.split("/")[-1]


def pick_symbol(symbols, title):
    syms = [s for s in re.split(r"[,;\s]+", symbols or "") if s]
    if not syms:
        return ""
    if re.search(r"\bclass\s*b\b", title or "", re.I):
        b = [s for s in syms if s.upper().endswith((".B", "-B", "/B"))]
        if b:
            return b[0]
    return syms[0]


def parse_form4(xml_bytes):
    root = strip_ns(ET.fromstring(xml_bytes))
    iss = root.find("issuer")
    tx = [{"code": txt(t, "transactionCoding/transactionCode"), "date": txt(t, "transactionDate/value"),
           "title": txt(t, "securityTitle/value"),
           "sh": num(txt(t, "transactionAmounts/transactionShares/value", "0")) or 0.0,
           "px": num(txt(t, "transactionAmounts/transactionPricePerShare/value", "0")) or 0.0,
           "post": num(txt(t, "postTransactionAmounts/sharesOwnedFollowingTransaction/value", "0")) or 0.0}
          for t in root.iter("nonDerivativeTransaction")]
    return {"issuer_cik": txt(iss, "issuerCik").zfill(10), "name": txt(iss, "issuerName"),
            "symbols": txt(iss, "issuerTradingSymbol"), "tx": tx}


def summarize_form4(d):
    """P(장내매수)·S(장내매도)를 증권 종류(클래스)별로 합산(가중평균가, 마지막 거래 후 보유).
    한 공시에 Class A·B가 섞여 오므로 종류를 합치면 주식수·티커·보유량이 모두 틀어진다."""
    res = []
    for code, kind in (("P", "buy"), ("S", "sell")):
        titles = []
        for t in d["tx"]:
            if t["code"] == code and t["sh"] > 0 and t["title"] not in titles:
                titles.append(t["title"])
        for title in titles:
            tx = [t for t in d["tx"] if t["code"] == code and t["sh"] > 0 and t["title"] == title]
            sh = sum(t["sh"] for t in tx)
            last = max(enumerate(tx), key=lambda p: (p[1]["date"], p[0]))[1]   # 같은 날 여러 건이면 문서 순서상 마지막
            res.append({"kind": kind, "sh": sh, "px": round(sum(t["sh"] * t["px"] for t in tx) / sh, 4),
                        "post": last["post"], "date": last["date"], "title": title})
    return res


def parse_schedule13(xml_bytes):
    root = strip_ns(ET.fromstring(xml_bytes))

    def first(*tags):
        for tg in tags:
            for el in root.iter(tg):
                if el.text and el.text.strip():
                    return el.text.strip()
        return ""

    def nums(*tags):
        return [num(el.text) or 0.0 for tg in tags for el in root.iter(tg) if el.text and el.text.strip()]

    sh = nums("reportingPersonBeneficiallyOwnedAggregateNumberOfShares", "aggregateAmountOwned")
    pct = nums("classPercent", "percentOfClass")
    return {"issuer_cik": first("issuerCik", "issuerCIK").zfill(10), "name": first("issuerName"),
            "cusip": first("issuerCusipNumber").upper(), "form": first("submissionType"),
            "amend": first("amendmentNo"), "event": first("dateOfEvent", "eventDateRequiresFilingThisStatement"),
            "sh": max(sh) if sh else 0.0, "pct": max(pct) if pct else 0.0}


def recent_filings(sec, inv_subs, own, today, days=FILINGS_DAYS, limit=300):
    """inv_subs: [(투자자 id, CIK, 제출 행)], own: {투자자 id: 자기 CIK 집합} → 최신순 리스트."""
    since = (today - dt.timedelta(days=days)).isoformat()
    jobs = [(inv, cik, r) for inv, cik, rows in inv_subs for r in rows
            if r["filed"] >= since and r["form"] in F4 + SCHED and r["doc"].lower().endswith(".xml")]

    def load(job):
        inv, cik, r = job
        cp = CACHE / f"f_{r['acc']}.json"
        if cp.exists():
            return job, json.loads(cp.read_text(encoding="utf-8"))
        b = sec.get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{r['acc'].replace('-', '')}/{raw_doc_name(r['doc'])}")
        if not b:
            return job, None
        try:
            d = parse_form4(b) if r["form"] in F4 else parse_schedule13(b)
        except ET.ParseError:
            return job, None
        CACHE.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return job, d

    out, seen = [], set()
    for (inv, cik, r), d in sec.map(load, jobs):
        if not d or r["acc"] in seen or d["issuer_cik"] in own.get(inv, set()):   # 투자자 자신이 발행사면 제외
            continue
        seen.add(r["acc"])
        base = {"d": r["filed"], "inv": inv, "form": r["form"], "acc": r["acc"], "cik": cik, "name": d["name"]}
        if r["form"] in F4:
            for x in summarize_form4(d):
                out.append({**base, "kind": x["kind"], "tk": pick_symbol(d["symbols"], x["title"]), "cusip": "",
                            "sh": x["sh"], "px": x["px"], "val": round(x["sh"] * x["px"]), "post": x["post"],
                            "pct": None, "td": x["date"]})
        else:
            out.append({**base, "kind": "stake", "tk": "", "cusip": d["cusip"], "sh": d["sh"], "px": None,
                        "val": None, "post": d["sh"], "pct": d["pct"], "td": d["event"]})
    out.sort(key=lambda x: (x["d"], x["acc"]), reverse=True)
    return out[:limit]
```

- [ ] **Step 5: 통과 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_filings.py` → Expected: `5 passed`

- [ ] **Step 6: 커밋**
```bash
git add radar/filings.py tests/fixtures tests/test_filings.py
git commit -m "Add Form 4 and Schedule 13D/13G recent filings"
```

---

### Task 11: build.py 재작성과 투자자 목록 갱신

**Files:**
- Modify: `build.py` (전체 교체), `investors.json` (전체 교체)
- Test: `tests/test_build.py`

**Interfaces:**
- Consumes: 모든 `radar.*` 공개 함수.
- Produces: `build.is_candidate(stock, tier)->bool`, `build.finite(obj)->obj` (NaN/Inf→None), `build.render_html(tpl, data)->str`, `build.collect(sec, invs, today)`, `build.main(today=None)`; 출력 `docs/index.html`, `docs/data.json` (스키마: 스펙 5절).

- [ ] **Step 1: 테스트 작성** — `tests/test_build.py`

```python
import json

from build import finite, is_candidate, render_html


def test_render_html_embeds_and_escapes():
    html = render_html('<script id="data" type="application/json">/*__DATA__*/null</script>', {"x": "</script><b>"})
    assert "/*__DATA__*/null" not in html and "<\\/script>" in html
    assert json.loads(html.split(">", 1)[1].rsplit("</script>", 1)[0].replace("<\\/", "</")) == {"x": "</script><b>"}


def test_finite_replaces_nan_and_inf():
    out = finite({"a": float("nan"), "b": [float("inf"), 1.5], "c": {"d": float("-inf")}, "e": "x", "f": 3})
    assert out == {"a": None, "b": [None, 1.5], "c": {"d": None}, "e": "x", "f": 3}


def test_is_candidate():
    tier = {"buffett": "A", "gates": "B", "soros": "B"}

    def s(acts):
        return {"actions": [{"inv": i, "t": t} for i, t in acts]}

    assert is_candidate(s([("gates", "new"), ("soros", "add")]), tier)
    assert is_candidate(s([("buffett", "new"), ("gates", "hold")]), tier)
    assert not is_candidate(s([("gates", "new"), ("soros", "hold")]), tier)
```

- [ ] **Step 2: 실패 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q tests/test_build.py` → Expected: FAIL (`cannot import name 'is_candidate'`)

- [ ] **Step 3: 구현** — `build.py` 전체 교체

```python
#!/usr/bin/env python3
"""
13F 컨센서스 빌더
SEC EDGAR 13F → 변화 분류 → 주가·가격 검증 → 백테스트·수시 공시 → docs/index.html(데이터 내장)
환경변수:
  SEC_USER_AGENT   (필수) 예: "13F-Consensus yourname@example.com" — SEC 공정접근 정책상 연락처 필수
  OPENFIGI_API_KEY (선택) CUSIP→티커 변환 속도 향상
  FULL_BACKTEST=1  (선택) 백테스트 강제 전체 재계산
"""
import datetime as dt
import json
import math
import os
import sys

from radar import config as C
from radar import prices
from radar.backtest import make_events, run_backtest
from radar.classify import BUY, HOLD, buy_stocks, classify
from radar.edgar import investor_periods, investor_status, normalize_investor
from radar.filings import recent_filings
from radar.metrics import display_metrics
from radar.sec import SecClient
from radar.tickers import map_tickers, yf_sym


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def is_candidate(s, tier):
    """애널리스트 목표가 조회 대상: 매수 2명+ 또는 앵커(A) 매수 + 보유 2명+."""
    b = [a for a in s["actions"] if a["t"] in BUY]
    h = [a for a in s["actions"] if a["t"] in HOLD]
    return len(b) >= 2 or (any(tier.get(a["inv"]) == "A" for a in b) and len(h) >= 2)


def finite(o):
    """NaN·Infinity가 JSON에 들어가면 페이지 전체가 깨지므로 None으로 바꾼다."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: finite(v) for k, v in o.items()}
    if isinstance(o, list):
        return [finite(v) for v in o]
    return o


def render_html(tpl, data):
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return tpl.replace("/*__DATA__*/null", js.replace("</", "<\\/"))


def collect(sec, invs, today):
    raw, meta, inv_subs, own, errors = {}, [], [], {}, 0
    san = {"n": 0, "total_bad": 0, "count_bad": 0}
    for inv in invs:
        base = {k: inv[k] for k in ("id", "label", "fund", "tier")}
        try:
            r = investor_periods(sec, inv)
        except Exception as e:
            errors += 1
            log(f"[error] {inv['label']}: {e}")
            meta.append({**base, "ciks": inv["ciks"], "edgar_names": {}, "status": f"error: {e}",
                         "last_period": None, "notes": [], "followed": []})
            continue
        periods = r["periods"]
        if periods:
            raw[inv["id"]] = {"periods": periods}
        status = investor_status(periods, today) if periods else ("cik_mismatch" if r["bad"] else "no_filings")
        own[inv["id"]] = set(r["subs"])
        inv_subs += [(inv["id"], cik, rows) for cik, rows in r["subs"].items()]
        for k in san:
            san[k] += r["san"][k]
        meta.append({**base, "ciks": list(r["subs"]), "edgar_names": r["names"], "status": status,
                     "last_period": max(periods) if periods else None, "notes": r["notes"], "followed": r["followed"]})
        log(f"[{status}] {inv['label']}: 분기 {len(periods)}개 {'; '.join(r['notes'])}")
    return raw, meta, inv_subs, own, san, errors


def main(today=None):
    today = today or dt.date.today()
    sec = SecClient(os.environ.get("SEC_USER_AGENT", "").strip())
    invs = [normalize_investor(i) for i in json.loads(C.INVESTORS.read_text(encoding="utf-8"))["investors"]]
    tier = {i["id"]: i["tier"] for i in invs}

    raw, meta, inv_subs, own, san, errors = collect(sec, invs, today)
    if errors >= max(1, round(0.3 * len(invs))):
        sys.exit(f"투자자 {errors}명 수집 실패 — 기존 페이지를 유지합니다.")

    allp = classify(invs, raw)
    show = {p: buy_stocks(allp[p]) for p in sorted(allp, reverse=True)[:C.N_SHOW]}
    filings = recent_filings(sec, inv_subs, own, today)
    cusips = ({s["cusip"] for P in show.values() for s in P["stocks"]}
              | {e["c"] for e in make_events(allp, {})} | {f["cusip"] for f in filings if f["cusip"]})
    tick = map_tickers(cusips, log=log)
    for f in filings:
        f["tk"] = f["tk"] or tick.get(f["cusip"], "")

    fx = prices.fx_krw()
    dm = display_metrics(show, tick, prices.download, fx, today,
                         extra={yf_sym(f["tk"]) for f in filings if f["tk"]}, log=log)
    if not dm["price_date"]:
        sys.exit("SPY 주가를 받지 못했습니다 — 기존 페이지를 유지합니다.")
    for f in filings:
        f["now"] = dm["quotes"].get(yf_sym(f["tk"])) if f["tk"] else None
    for P in show.values():                                   # 분할 확인 후 최종 매수 종목
        P["stocks"] = [s for s in P["stocks"] if any(a["t"] in BUY for a in s["actions"])]
        for s in P["stocks"]:
            for a in s["actions"]:
                a.pop("t0", None)

    cand = sorted({yf_sym(s["tk"]) for P in show.values() for s in P["stocks"] if s.get("tk") and is_candidate(s, tier)})
    an = prices.analyst_targets(cand, C.ANALYST_FILE, today, log=log)
    for P in show.values():
        for s in P["stocks"]:
            s["an"] = an.get(yf_sym(s["tk"])) if s.get("tk") else None

    full = not C.BT_FILE.exists() or today.weekday() == 6 or os.environ.get("FULL_BACKTEST") == "1"
    try:
        bt = run_backtest(allp, tick, prices.download, today, [i["id"] for i in invs], full=full, log=log)
    except Exception as e:
        log(f"백테스트 실패: {e}")
        bt = json.loads(C.BT_FILE.read_text(encoding="utf-8")) if C.BT_FILE.exists() else None

    pxs = [s.get("px") for P in show.values() for s in P["stocks"] if s.get("tk")]
    san.update(validated=sum(1 for p in pxs if p and p["ok"]), unvalidated=sum(1 for p in pxs if p and p["ok"] is False),
               noprice=sum(1 for p in pxs if not p))
    data = finite({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "price_date": dm["price_date"], "fx": fx, "investors": meta, "periods": show,
                   "bt": bt, "filings": filings, "sanity": san})
    C.OUT.mkdir(exist_ok=True)
    (C.OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    html = render_html(C.TEMPLATE.read_text(encoding="utf-8"), data)
    (C.OUT / "index.html").write_text(html, encoding="utf-8")
    log(f"완료: 분기 {list(show)} · 표시 종목 {sum(len(P['stocks']) for P in show.values())} · "
        f"수시 공시 {len(filings)} · 페이지 {len(html) / 1e6:.1f}MB · 점검 {san}")


if __name__ == "__main__":
    main()
```

`investors.json` 전체 교체(애크먼·아인혼 CIK 추가, 전 항목 `ciks`/`expect` 리스트화):
```json
{
  "_note": "tier A = 앵커(레전드) 투자자, B = 거물급 동반 투자자. ciks = 보고 법인 CIK 목록(법인 변경 시 추가), expect = EDGAR 등록명에 포함돼야 하는 문자열(하나라도). 13F-NT로 다른 법인이 대신 보고하면 이름이 맞을 때 자동 추적.",
  "investors": [
    {"id": "buffett",   "label": "워런 버핏",           "fund": "Berkshire Hathaway",          "tier": "A", "ciks": ["0001067983"], "expect": ["BERKSHIRE"]},
    {"id": "lilu",      "label": "리 루",               "fund": "Himalaya Capital",            "tier": "A", "ciks": ["0001709323"], "expect": ["HIMALAYA"]},
    {"id": "klarman",   "label": "세스 클라만",         "fund": "Baupost Group",               "tier": "A", "ciks": ["0001061768"], "expect": ["BAUPOST"]},
    {"id": "ackman",    "label": "빌 애크먼",           "fund": "Pershing Square",             "tier": "A", "ciks": ["0001336528", "0002026053"], "expect": ["PERSHING"]},
    {"id": "druck",     "label": "스탠리 드러켄밀러",   "fund": "Duquesne Family Office",      "tier": "A", "ciks": ["0001536411"], "expect": ["DUQUESNE"]},
    {"id": "tepper",    "label": "데이비드 테퍼",       "fund": "Appaloosa",                   "tier": "A", "ciks": ["0001656456"], "expect": ["APPALOOSA"]},
    {"id": "pabrai",    "label": "모니시 파브라이",     "fund": "Dalal Street",                "tier": "A", "ciks": ["0001549575"], "expect": ["DALAL"]},
    {"id": "akre",      "label": "척 에이커",           "fund": "Akre Capital",                "tier": "A", "ciks": ["0001112520"], "expect": ["AKRE"]},
    {"id": "gayner",    "label": "톰 게이너",           "fund": "Markel Group",                "tier": "A", "ciks": ["0001096343"], "expect": ["MARKEL"]},
    {"id": "russo",     "label": "톰 루소",             "fund": "Gardner Russo & Quinn",       "tier": "A", "ciks": ["0000860643"], "expect": ["GARDNER"]},
    {"id": "einhorn",   "label": "데이비드 아인혼",     "fund": "Greenlight Capital (DME)",    "tier": "A", "ciks": ["0001079114", "0001489933"], "expect": ["GREENLIGHT", "DME"]},
    {"id": "loeb",      "label": "댄 로브",             "fund": "Third Point",                 "tier": "A", "ciks": ["0001040273"], "expect": ["THIRD POINT"]},
    {"id": "burry",     "label": "마이클 버리",         "fund": "Scion Asset Management",      "tier": "A", "ciks": ["0001649339"], "expect": ["SCION"]},
    {"id": "icahn",     "label": "칼 아이칸",           "fund": "Icahn Carl C",                "tier": "B", "ciks": ["0000921669"], "expect": ["ICAHN"]},
    {"id": "marks",     "label": "하워드 막스",         "fund": "Oaktree Capital",             "tier": "B", "ciks": ["0000949509"], "expect": ["OAKTREE"]},
    {"id": "soros",     "label": "조지 소로스",         "fund": "Soros Fund Management",       "tier": "B", "ciks": ["0001029160"], "expect": ["SOROS"]},
    {"id": "gates",     "label": "게이츠 재단",         "fund": "Gates Foundation Trust",      "tier": "B", "ciks": ["0001166559"], "expect": ["GATES"]},
    {"id": "peltz",     "label": "넬슨 펠츠",           "fund": "Trian Fund Management",       "tier": "B", "ciks": ["0001345471"], "expect": ["TRIAN"]},
    {"id": "valueact",  "label": "ValueAct",            "fund": "ValueAct Holdings",           "tier": "B", "ciks": ["0001418814"], "expect": ["VALUEACT"]},
    {"id": "nygren",    "label": "빌 나이그렌",         "fund": "Harris Associates (Oakmark)", "tier": "B", "ciks": ["0000813917"], "expect": ["HARRIS"]},
    {"id": "dodge",     "label": "Dodge & Cox",         "fund": "Dodge & Cox",                 "tier": "B", "ciks": ["0000200217"], "expect": ["DODGE"]},
    {"id": "smith",     "label": "테리 스미스",         "fund": "Fundsmith",                   "tier": "B", "ciks": ["0001569205"], "expect": ["FUNDSMITH"]},
    {"id": "berkowitz", "label": "브루스 버코위츠",     "fund": "Fairholme Capital",           "tier": "B", "ciks": ["0001056831"], "expect": ["FAIRHOLME"]},
    {"id": "coleman",   "label": "체이스 콜먼",         "fund": "Tiger Global",                "tier": "B", "ciks": ["0001167483"], "expect": ["TIGER GLOBAL"]},
    {"id": "mandel",    "label": "스티븐 맨덜",         "fund": "Lone Pine Capital",           "tier": "B", "ciks": ["0001061165"], "expect": ["LONE PINE"]},
    {"id": "halvorsen", "label": "안드레아스 할보르센", "fund": "Viking Global",               "tier": "B", "ciks": ["0001103804"], "expect": ["VIKING"]},
    {"id": "laffont",   "label": "필립 라퐁",           "fund": "Coatue Management",           "tier": "B", "ciks": ["0001135730"], "expect": ["COATUE"]}
  ]
}
```

- [ ] **Step 4: 통과 확인** — Run: `~/.venvs/13f/bin/python -m pytest -q` → Expected: `53 passed`, 실패 0

- [ ] **Step 5: 커밋**
```bash
git add build.py investors.json tests/test_build.py
git commit -m "Rewrite build orchestrator on radar modules; fix Pershing and Greenlight CIKs"
```

---

### Task 12: 첫 실데이터 전체 수집과 검증

**Files:**
- Create(로컬 산출물): `data/cache/*.json`, `data/cusip_map.json`, `data/backtest.json`, `data/analyst.json`, `docs/index.html`, `docs/data.json`
- Create(검증 스크립트, 스크래치패드): `$SCRATCH/verify_run.py`, `$SCRATCH/check_brk.py`

**Interfaces:**
- Consumes: `build.main()`; 출력 스키마(스펙 5절).

- [ ] **Step 1: 전체 실행(백그라운드, 로그 저장)**

Run:
```bash
cd ROOT && SEC_USER_AGENT="13F-Consensus drchulfe@gmail.com" FULL_BACKTEST=1 ~/.venvs/13f/bin/python build.py 2>&1 | tee $SCRATCH/build.log
```
Expected: 투자자별 `[ok]`/`[inactive]` 줄, 애크먼 줄에 Pershing Square Inc. 병합, 버리 `[inactive]`, 마지막 `완료: …` 줄. 실패 시 로그의 첫 오류를 systematic-debugging 절차로 원인부터 확인.

- [ ] **Step 2: 결과 점검 스크립트** — `$SCRATCH/verify_run.py`

```python
import json
from pathlib import Path

d = json.loads(Path("docs/data.json").read_text(encoding="utf-8"))
print("generated", d["generated_at"], "price_date", d["price_date"], "fx", d["fx"])
for i in d["investors"]:
    print(f"{i['id']:10s} {i['status']:12s} last={i['last_period']} ciks={i['ciks']} {'; '.join(i['notes'])}")
for p, P in d["periods"].items():
    px = [s["px"] for s in P["stocks"] if s.get("px")]
    print(p, "filed", len(P["filed"]), "stocks", len(P["stocks"]), "px", len(px),
          "ok", sum(1 for x in px if x["ok"]), "bad", sum(1 for x in px if x["ok"] is False))
bt = d["bt"]
print("bt", bt and bt["stats"], "ev", bt and len(bt["ev"]), "periods", bt and (bt["P"][0], bt["P"][-1]))
print("filings", len(d["filings"]))
for f in d["filings"][:8]:
    print("  ", f["d"], f["inv"], f["form"], f["kind"], f["tk"], f["sh"], f["px"], f["pct"], f.get("now"))
print("sanity", d["sanity"])
print("page MB", round(Path("docs/index.html").stat().st_size / 1e6, 2))
```

Run: `cd ROOT && ~/.venvs/13f/bin/python $SCRATCH/verify_run.py`
Expected(판정 기준):
- 활동 투자자 26명 내외 `ok`, `burry` = `inactive`, `cik_mismatch`/`error` 0.
- `ackman` ciks에 `0002026053`, `einhorn` ciks에 `0001489933` 포함.
- 최신 분기(2026-06-30) filed ≥ 24, 가격 검증 `ok` 비율 ≥ 90%.
- `sanity.total_bad`와 `count_bad`가 전체 `n`의 5% 이하(넘으면 해당 접수번호를 원문과 대조).
- bt `used` ≥ 3,000, `mismatch`는 `total`의 15% 이하.
- filings에 2026-09 버크셔 LEN Form 4 `buy`가 있다.
- page MB ≤ 8.

- [ ] **Step 3: 버크셔 원문 대조** — `$SCRATCH/check_brk.py`

```python
import json
from pathlib import Path

d = json.loads(Path("docs/data.json").read_text(encoding="utf-8"))
P = d["periods"]["2026-06-30"]
f = next(x for x in P["filed"] if x["inv"] == "buffett")
print("BRK filed", f["filed"], "accs", f["accs"], "n", f["n"], "aum", f"{f['aum'] / 1e9:.1f}B")
for acc in f["accs"]:
    c = json.loads(Path(f"data/cache/{acc}.json").read_text(encoding="utf-8"))
    print(" ", acc, c["form"], c["amendment_type"] or "-", c["sanity"])
rows = [(s.get("tk"), s["name"], a) for s in P["stocks"] for a in s["actions"] if a["inv"] == "buffett"]
for tk, nm, a in sorted(rows, key=lambda x: -x[2]["v"])[:12]:
    print(f"  {tk or '-':6s} {nm[:26]:26s} {a['t']:6s} {a['psh']:>13,} → {a['sh']:>13,}  ${a['v'] / 1e9:6.2f}B")
len_rows = [r for r in rows if r[0] in ("LEN", "LEN.B", "LEN/B")]
print("LEN in BRK buys:", [(r[0], r[2]["t"], r[2]["sh"]) for r in len_rows])
```

Run: `cd ROOT && ~/.venvs/13f/bin/python $SCRATCH/check_brk.py`
Expected: 버크셔 13F의 sanity `total_ok`·`count_ok` True, 평가액이 EDGAR 표지 합계와 일치, LEN이 신규/추가로 보임(13G에서 6/30 기준 6.2% 보유 확인됨). 같은 분기 13F 원문(`https://www.sec.gov/Archives/edgar/data/1067983/<acc>/`)을 WebFetch 없이 SecClient로 받아 상위 5개 종목 주식수를 대조.

- [ ] **Step 4: 데이터 커밋(docs 제외)**

```bash
cd ROOT && git add data && git commit -m "Add first full EDGAR 13F cache, ticker map and backtest"
```

---

### Task 13: 화면(template.html) 재작성 + CORE 테스트

**Files:**
- Modify: `template.html` (전체 교체)
- Create: `tests/js/core.test.mjs`

**Interfaces:**
- Consumes: 데이터 스키마(스펙 5절), bt 압축 형식(Task 8).
- Produces: `CORE = {med, quant, winsorMean, annualize, band, niceTicks, decodeBT, evCount, stats, trackRecord}` (`/*CORE-BEGIN*/…/*CORE-END*/` 구간). 페이지 렌더 끝에 `document.body.dataset.ready = "1"`.

- [ ] **Step 1: Node 테스트 작성** — `tests/js/core.test.mjs`

```js
import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const html = readFileSync(new URL('../../template.html', import.meta.url), 'utf8');
const src = html.split('/*CORE-BEGIN*/')[1].split('/*CORE-END*/')[0];
const CORE = new Function(`${src}; return CORE;`)();

const K = [0, 21, 63, 126], H = { '1w': 5, '1m': 21, '1y': 252, '3y': 756, '5y': 1260 };
const O = [...new Set([...K.flatMap(k => Object.values(H).map(h => k + h)), ...K])].sort((a, b) => a - b);
const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);
const R = map => { const r = new Array(O.length).fill(null); for (const [o, v] of Object.entries(map)) r[O.indexOf(+o)] = v; return r; };
const F = (o = {}) => ({ anchorSet: null, basis: 'buy', minN: 2, newOnly: false, ...o });

test('offset grid matches python', () => {
  assert.equal(O.length, 23);
  assert.ok(O.includes(63) && O.includes(252) && O.includes(1386));
});

test('median, quantile, winsorized mean', () => {
  assert.equal(CORE.med([3, 1, 2]), 2); assert.equal(CORE.med([1, 2, 3, 4]), 2.5); assert.equal(CORE.med([]), null);
  near(CORE.quant([0, 10], 0.16), 1.6);
  const a = Array.from({ length: 100 }, (_, i) => i); a[99] = 1e6;
  assert.ok(CORE.winsorMean(a) < 200);          // 원평균 ≈ 10,049 → 1% 윈저화 ≈ 149.5
});

test('annualize and band', () => {
  near(CORE.annualize(0.21, 504), 0.1, 1e-12);
  const b = CORE.band(0.1, 0.3, 252);
  near(b[0], Math.exp(Math.log(1.1) - 0.3) - 1); near(b[1], Math.exp(Math.log(1.1) + 0.3) - 1);
  assert.equal(CORE.band(null, 0.3, 5), null);
});

test('decodeBT expands compact events', () => {
  const bt = { K, H, O, P: ['2025-12-31'], I: ['buffett', 'gates'], ev: [[0, 'AAA', [1, 2], 3, [0, 50], 0]], spy: [[0, 20]] };
  const d = CORE.decodeBT(bt);
  assert.deepEqual(d.ev[0].slice(0, 4), ['2025-12-31', 'AAA', [['buffett', 'n'], ['gates', 'a']], 3]);
  assert.equal(d.ev[0][4].length, O.length); near(d.ev[0][4][1], 0.05); assert.equal(d.ev[0][4][5], null);
  near(d.spy[0][1], 0.02);
});

test('evCount respects anchor, newOnly and basis', () => {
  const ev = ['2025-12-31', 'A', [['buffett', 'n'], ['gates', 'a']], 4, R({}), 0];
  assert.equal(CORE.evCount(ev, F()), 2);
  assert.equal(CORE.evCount(ev, F({ basis: 'hold' })), 4);
  assert.equal(CORE.evCount(ev, F({ newOnly: true })), 1);
  assert.equal(CORE.evCount(ev, F({ anchorSet: new Set(['soros']) })), -1);
});

test('stats: horizon returns, cutoff, bucket and SPY excess', () => {
  const b = [['buffett', 'n'], ['gates', 'a']];
  const bt = { K, H, O, spy: [R({ 0: 0, 21: 0.05 })], ev: [
    ['2025-09-30', 'A', b, 2, R({ 0: 0, 21: 0.10 }), 0],
    ['2025-09-30', 'B', b, 2, R({ 0: 0, 21: 0.20 }), 0],
    ['2025-09-30', 'C', b, 2, R({ 0: 0, 21: -0.10 }), 0],
    ['2026-03-31', 'D', b, 2, R({ 0: 0, 21: 0.90 }), 0]] };
  const st = CORE.stats(bt, F(), '2026-03-31', 0, null);
  assert.equal(st.nev, 3); assert.equal(st['1m'].n, 3);
  near(st['1m'].med, 0.10); near(st['1m'].hit, 2 / 3); near(st['1m'].ex, 0.05);
  assert.equal(st['1y'].n, 0);
  assert.equal(CORE.stats(bt, F(), '2026-03-31', 0, 3).nev, 0);
});

test('stats: elapsed k re-bases returns', () => {
  const bt = { K, H, O, spy: [R({})], ev: [['2025-09-30', 'A', [['buffett', 'n'], ['gates', 'n']], 2, R({ 21: 0.10, 42: 0.21 }), 0]] };
  near(CORE.stats(bt, F(), null, 21, null)['1m'].med, 0.1);
});

test('trackRecord chains cohorts with cash for empty quarters', () => {
  const bA = [['buffett', 'n'], ['gates', 'a']], bB = [['soros', 'n'], ['gates', 'a']];
  const bt = { K, H, O, spy: [R({ 63: 0.02, 252: 0.08 }), R({ 63: 0.03 })], ev: [
    ['2025-03-31', 'A', bA, 2, R({ 63: 0.10, 252: 0.30 }), 0],
    ['2025-03-31', 'B', bA, 2, R({ 63: 0.00, 252: 0.10 }), 0],
    ['2025-06-30', 'C', bB, 2, R({ 63: 0.50 }), 1]] };
  const T = CORE.trackRecord(bt, F({ anchorSet: new Set(['buffett']) }));
  assert.equal(T.q, 2);
  near(T.rows[0].r3, 0.05); near(T.rows[0].s3, 0.02); near(T.rows[0].r1, 0.2);
  assert.equal(T.rows[1].n, 0); assert.equal(T.rows[1].r3, 0); near(T.rows[1].s3, 0.03);
  near(T.curve[1].nav, 1.05); near(T.curve[1].snav, 1.02 * 1.03);
  near(T.win, 0.5); near(T.mdd, 0); near(T.cagr, Math.pow(1.05, 2) - 1);
});

test('niceTicks covers range with round steps', () => {
  assert.deepEqual(CORE.niceTicks(0.9, 3.4, 4), [0, 1, 2, 3, 4]);
  const t = CORE.niceTicks(0.95, 1.32, 4);
  assert.ok(t[0] <= 0.95 && t[t.length - 1] >= 1.32);
});
```

- [ ] **Step 2: 실패 확인** — Run: `cd ROOT && node --test tests/js/core.test.mjs` → Expected: FAIL (`Cannot read properties of undefined` — 현 템플릿에 CORE 구간 없음)

- [ ] **Step 3: template.html 전체 교체** — 아래 전체 내용으로 저장.

````html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>13F 컨센서스 레이더</title>
<meta name="description" content="버핏 등 거물 투자자가 함께 산 미국 주식과 지금 사면 기대수익 — SEC 13F 기반, 매일 갱신">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">
<style>
:root{
  --ground:#F2F4F3; --panel:#FFFFFF; --ink:#16211D; --ink-2:#4A5852; --ink-3:#66736D;
  --line:#D9DFDC; --line-2:#E8ECEA; --accent:#0B6B53; --accent-soft:#DDEFE8;
  --new:#1F5FBF; --new-soft:#E1EAF8; --add:#0B6B53; --add-soft:#DDEFE8;
  --red:#B4412F; --red-soft:#F6E3DF; --amber:#8A5F00; --amber-soft:#F5ECD3;
  --series-a:#2a78d6; --series-b:#1baf7a;
  --shadow:0 1px 2px rgba(22,33,29,.06),0 4px 14px rgba(22,33,29,.05);
  --sans:"IBM Plex Sans KR",-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;
  color-scheme:light;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0F1513; --panel:#161E1B; --ink:#E4ECE8; --ink-2:#AAB7B1; --ink-3:#86938D;
  --line:#2A3531; --line-2:#212A27; --accent:#4CC39C; --accent-soft:#16352B;
  --new:#7AA8F0; --new-soft:#1A2A45; --add:#4CC39C; --add-soft:#16352B;
  --red:#E88A78; --red-soft:#3A201B; --amber:#E0B455; --amber-soft:#352A12;
  --series-a:#3987e5; --series-b:#199e70; --shadow:none; color-scheme:dark;}}
:root[data-theme="dark"]{
  --ground:#0F1513; --panel:#161E1B; --ink:#E4ECE8; --ink-2:#AAB7B1; --ink-3:#86938D;
  --line:#2A3531; --line-2:#212A27; --accent:#4CC39C; --accent-soft:#16352B;
  --new:#7AA8F0; --new-soft:#1A2A45; --add:#4CC39C; --add-soft:#16352B;
  --red:#E88A78; --red-soft:#3A201B; --amber:#E0B455; --amber-soft:#352A12;
  --series-a:#3987e5; --series-b:#199e70; --shadow:none; color-scheme:dark;}
*{box-sizing:border-box}
html{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
body{margin:0;background:var(--ground);color:var(--ink);font:14px/1.55 var(--sans);-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding-inline:16px;padding-block:22px 60px;display:grid;gap:18px}
header.top{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px}
h1{margin:0;font-size:24px;font-weight:700;letter-spacing:-.01em;text-wrap:balance}
h1 small{display:block;font:500 11px/1.4 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--accent);margin-bottom:4px}
.stamp{font:12px/1.5 var(--mono);color:var(--ink-3);text-align:right}
.demo{background:var(--amber-soft);color:var(--amber);border:1px solid var(--amber);border-radius:8px;padding:10px 14px;font-weight:600}
.warn{background:var(--red-soft);color:var(--red);border:1px solid var(--red);border-radius:8px;padding:10px 14px;font-weight:600}
.status{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.status>div{background:var(--panel);padding:12px 14px;display:grid;gap:2px}
.k{font:500 11px/1.3 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3)}
.v{font:600 18px/1.3 var(--mono);font-variant-numeric:tabular-nums}
.v em{font-style:normal;font-weight:400;font-size:12px;color:var(--ink-3)}
.bar{height:4px;background:var(--line-2);border-radius:2px;overflow:hidden;margin-top:4px}
.bar i{display:block;height:100%;background:var(--accent)}
.controls{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;display:flex;flex-wrap:wrap;gap:14px 22px;align-items:flex-end;box-shadow:var(--shadow)}
.ctl{display:grid;gap:5px}
.ctl label,.ctl .lab{font:500 11px/1.3 var(--mono);letter-spacing:.06em;color:var(--ink-3);text-transform:uppercase}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:7px;overflow:hidden;flex-wrap:wrap}
.seg button{border:0;background:transparent;color:var(--ink-2);font:500 13px var(--sans);padding:6px 11px;cursor:pointer}
.seg button+button{border-left:1px solid var(--line)}
.seg button[aria-pressed="true"]{background:var(--ink);color:var(--panel)}
select,input[type=search]{font:13px var(--sans);color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:6px 9px}
input[type=search]{min-width:0;width:180px}
.chk{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--ink-2);cursor:pointer}
button:focus-visible,select:focus-visible,input:focus-visible,summary:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.rule{font-size:13px;color:var(--ink-2);margin:0}
.rule b{color:var(--ink)}
section.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;box-shadow:var(--shadow);min-width:0}
.card h2{margin:0;font-size:15px;font-weight:600;padding:12px 16px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}
.card h2 span{font:12px var(--mono);color:var(--ink-3);font-weight:400}
.list{display:grid;grid-template-columns:minmax(0,1fr)}
details.row{border-bottom:1px solid var(--line-2)}
details.row:last-child{border-bottom:0}
details.row>summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:92px minmax(0,1fr) auto;gap:6px 16px;padding:12px 16px;align-items:start}
details.row>summary::-webkit-details-marker{display:none}
details.row>summary:hover{background:var(--line-2)}
.tk{font:600 15px/1.3 var(--mono);overflow-wrap:anywhere}
.tk small{display:block;font:400 11px var(--mono);color:var(--ink-3)}
.nm{font-weight:600;overflow-wrap:anywhere}
.nm small{font-weight:400;color:var(--ink-3);margin-left:6px}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:12px;padding:2px 8px 2px 6px;border-radius:5px;background:var(--line-2);color:var(--ink-2);white-space:nowrap}
.chip b{font:600 10px var(--mono);padding:1px 4px;border-radius:3px}
.chip.new{background:var(--new-soft);color:var(--ink)} .chip.new b{background:var(--new);color:var(--panel)}
.chip.add{background:var(--add-soft);color:var(--ink)} .chip.add b{background:var(--add);color:var(--panel)}
.chip.anchor{box-shadow:inset 0 0 0 1.5px var(--ink)}
.score{text-align:right;white-space:nowrap;font:600 22px/1 var(--sans)}
.score small{display:block;font:400 11px/1.6 var(--mono);color:var(--ink-3)}
.detail{padding:4px 16px 16px;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid var(--line-2);white-space:nowrap}
th{font:500 11px var(--mono);color:var(--ink-3);letter-spacing:.05em;text-transform:uppercase}
td.n{text-align:right;font-family:var(--mono)}
.t{font:600 11px var(--mono);padding:1px 6px;border-radius:3px}
.t.new,.t.first{background:var(--new-soft);color:var(--new)} .t.add{background:var(--add-soft);color:var(--add)}
.t.reduce{background:var(--amber-soft);color:var(--amber)} .t.sold{background:var(--red-soft);color:var(--red)}
.t.hold{background:var(--line-2);color:var(--ink-3)}
.empty{padding:28px 16px;color:var(--ink-2);text-align:center}
.grid2{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:18px;align-items:start}
.side{display:grid;gap:18px;min-width:0}
.scroll{overflow-x:auto}
.note{font-size:12.5px;color:var(--ink-2);padding:12px 16px;display:grid;gap:6px}
.note p{margin:0}
.bad{color:var(--red);font-weight:600}
a{color:var(--accent)}
.exp{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:1px;background:var(--line-2);border:1px solid var(--line-2);border-radius:6px;overflow:hidden;margin-top:8px;max-width:440px}
.exp div{background:var(--panel);padding:4px 6px;display:grid;gap:0}
.exp span{font:500 10px var(--mono);color:var(--ink-3);letter-spacing:.04em}
.exp b{font:600 12.5px var(--mono);font-variant-numeric:tabular-nums}
.pos{color:var(--add)} .neg{color:var(--red)} .mut{color:var(--ink-3)}
.pxl{font:12px/1.6 var(--mono);color:var(--ink-2);margin-top:6px}
.pxl b{color:var(--ink)}
.sub{font:600 12px var(--sans);color:var(--ink-2);margin:14px 0 6px}
.cap{font-size:12px;color:var(--ink-3);margin:6px 0 0;white-space:normal}
.thin{opacity:.55}
.badge{display:inline-flex;align-items:center;font:600 10.5px var(--mono);padding:1px 6px;border-radius:4px;background:var(--amber-soft);color:var(--amber);margin-left:6px;vertical-align:2px;white-space:nowrap}
.links{margin:6px 0 2px;display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px}
.subbar{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line-2)}
.subbar .cap{margin:0}
.more{display:block;width:100%;border:0;border-top:1px solid var(--line-2);background:transparent;color:var(--accent);font:500 13px var(--sans);padding:10px;cursor:pointer}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--line-2);border-bottom:1px solid var(--line-2)}
.tiles>div{background:var(--panel);padding:10px 16px;display:grid;gap:2px}
.tiles .tv{font:600 20px/1.25 var(--sans)}
.tiles .tv small{font:400 12px var(--sans);color:var(--ink-3);margin-left:6px}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12px;color:var(--ink-2);padding:12px 16px 0}
.legend i,.tip i{display:inline-block;width:14px;height:2px;border-radius:1px;vertical-align:middle;margin-right:6px}
i.ka{background:var(--series-a)} i.kb{background:var(--series-b)}
.chart{position:relative;padding:6px 16px 8px}
.chart svg{display:block;width:100%;height:auto;overflow:visible}
.chart svg:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.chart text{font:11px var(--mono);fill:var(--ink-3)}
.chart .dl text{fill:var(--ink-2);font-weight:600}
.chart .gl{stroke:var(--line-2);stroke-width:1}
.chart .la,.chart .lb{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.chart .la{stroke:var(--series-a)} .chart .lb{stroke:var(--series-b)}
.chart line.ka{stroke:var(--series-a);stroke-width:2} .chart line.kb{stroke:var(--series-b);stroke-width:2}
.chart .da{fill:var(--series-a)} .chart .db{fill:var(--series-b)}
.chart circle{stroke:var(--panel);stroke-width:2}
.chart .xh{stroke:var(--ink-3);stroke-width:1}
.tip{position:absolute;top:8px;pointer-events:none;background:var(--panel);border:1px solid var(--line);border-radius:6px;box-shadow:var(--shadow);padding:6px 10px;font-size:12px;display:none;min-width:150px;z-index:2}
.tip .tt{color:var(--ink-3);font:11px var(--mono);margin-bottom:2px}
.tip b{font:600 13px var(--mono);color:var(--ink)}
.tip span{color:var(--ink-2)}
details.trd{border-top:1px solid var(--line-2)}
details.trd>summary{cursor:pointer;padding:10px 16px;font-size:13px;color:var(--ink-2)}
.foot{font-size:12px;color:var(--ink-3);text-align:center}
@media (max-width:820px){.grid2{grid-template-columns:1fr}}
@media (max-width:560px){details.row>summary{grid-template-columns:68px minmax(0,1fr)}.score{grid-column:1/-1;text-align:left;display:flex;gap:10px;align-items:baseline}.score small{display:inline}input[type=search]{width:100%}.ctl{width:100%}.stamp{text-align:left}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1><small>SEC Form 13F · Superinvestor Consensus</small>13F 컨센서스 레이더</h1>
    <div class="stamp" id="stamp"></div>
  </header>
  <div class="demo" id="demo" hidden>예시 데이터입니다 — 실제 13F가 아닙니다.</div>
  <div class="warn" id="stale" hidden></div>

  <div class="status" id="status"></div>

  <section class="card">
    <h2>수시 공시 — 13F보다 빠른 신호 <span id="fcnt"></span></h2>
    <div class="subbar">
      <div class="seg" id="fk"><button data-v="all">전체</button><button data-v="buy">장내매수</button><button data-v="sell">장내매도</button><button data-v="stake">5%+ 지분</button></div>
      <p class="cap">Form 4(10%+ 주주의 장내 매매, 2영업일 내 공시)·Schedule 13D/13G(5%+ 지분). 아래 조건과 무관하게 최근 90일 전체입니다.</p>
    </div>
    <div class="scroll" id="filings"></div>
  </section>

  <div class="controls">
    <div class="ctl"><span class="lab">공시 기간</span>
      <div class="seg" id="win"><button data-v="d1">최근 공시일</button><button data-v="d7">7일</button><button data-v="d30">30일</button><button data-v="q">분기 전체</button></div></div>
    <div class="ctl"><label for="period">보고 분기</label><select id="period"></select></div>
    <div class="ctl"><span class="lab">앵커 매수</span>
      <div class="seg" id="anchor"><button data-v="buffett">버핏</button><button data-v="A">레전드군</button><button data-v="any">조건 없음</button></div></div>
    <div class="ctl"><span class="lab">동시 투자 기준</span>
      <div class="seg" id="basis"><button data-v="buy">같은 분기 매수</button><button data-v="hold">보유 포함</button></div></div>
    <div class="ctl"><label for="minN">최소 투자자 수</label><select id="minN"><option>2</option><option>3</option><option>4</option><option>5</option></select></div>
    <div class="ctl"><span class="lab">옵션</span><label class="chk"><input type="checkbox" id="newOnly"> 신규매수만</label></div>
    <div class="ctl"><label for="sort">정렬</label><select id="sort"><option value="n">동시 투자자 수</option><option value="exp">기대수익(1년)</option><option value="prem">추정 매입가보다 싼 순</option><option value="recent">최근 공시</option></select></div>
    <div class="ctl"><span class="lab">기대수익 표시</span><div class="seg" id="exp"><button data-v="med">중앙값</button><button data-v="mean">평균</button></div></div>
    <div class="ctl"><label for="q">검색</label><input type="search" id="q" placeholder="티커·종목명"></div>
  </div>
  <p class="rule" id="rule"></p>

  <div class="grid2">
    <section class="card">
      <h2>시그널 종목 <span id="cnt"></span></h2>
      <div class="list" id="list"></div>
    </section>
    <div class="side">
      <section class="card">
        <h2>백테스트 · 현재 조건 <span id="btmeta"></span></h2>
        <div class="scroll"><table id="bttbl"></table></div>
        <div class="note" id="btnote"></div>
      </section>
      <section class="card">
        <h2>투자자 제출 현황 <span id="invcnt"></span></h2>
        <div class="scroll"><table id="invtbl"></table></div>
      </section>
      <section class="card">
        <h2>읽는 법</h2>
        <div class="note">
          <p><b>매수</b> = 직전 분기 13F 대비 신규 편입 또는 주식수 증가. 13F는 분기말 스냅샷(최대 45일 뒤 공개)이라 실제 매매 시점·가격은 알 수 없습니다.</p>
          <p><b>지금 사면 기대수익</b> = 지금 조건과 같은 과거 시그널(2013년~)에서, 이 종목처럼 공시 후 같은 기간이 지난 시점에 샀을 때 1주·1달·1년·3년·5년 뒤 수익률(배당 포함). 중앙값은 전형적인 결과, 평균은 포트폴리오 기대값에 가깝습니다. 예측이 아니라 과거 기저율입니다.</p>
          <p><b>추정 매입가</b> = 매수한 분기의 거래량 가중 평균가(VWAP). 현재가가 이보다 낮으면 그 투자자들보다 싸게 사는 셈입니다(실제 매입가는 비공개).</p>
          <p><b>수시 매수 배지</b> = 최근 90일 안에 추적 투자자의 Form 4 장내매수나 5%+ 신규 지분 공시가 있는 종목.</p>
          <p><b>티커 확인 필요</b> = 13F의 평가가격과 실제 주가가 맞지 않아 티커 매핑이 의심되는 종목. 가격 기반 수치를 숨깁니다.</p>
          <p>주식분할(모든 보유자 주식수가 같은 배수로 변하고 실제 분할 기록이 있는 경우)은 매수에서 제외. 옵션·채권은 제외, 공매도는 13F에 나오지 않습니다.</p>
        </div>
      </section>
    </div>
  </div>

  <section class="card">
    <h2>전략 트랙레코드 — 현재 조건으로 매 분기 샀다면 <span id="trmeta"></span></h2>
    <div class="tiles" id="trtiles"></div>
    <div class="legend"><span><i class="ka"></i>전략(조건 충족 종목 동일가중, 분기마다 교체)</span><span><i class="kb"></i>S&amp;P500(SPY, 같은 기간)</span></div>
    <div class="chart" id="trchart"></div>
    <details class="trd"><summary>분기별 표 보기</summary><div class="scroll" id="trtbl"></div></details>
    <div class="note" id="trnote"></div>
  </section>

  <footer class="foot">투자 권유가 아닙니다 · 원자료 <a href="https://www.sec.gov/edgar/search/" rel="noopener">SEC EDGAR</a> · 주가 Yahoo Finance · 티커 OpenFIGI</footer>
</div>

<script id="data" type="application/json">/*__DATA__*/null</script>
<script>
(function(){
'use strict';
const th = new URLSearchParams(location.search).get('theme');
if(th==='dark'||th==='light') document.documentElement.dataset.theme = th;
const DATA = JSON.parse(document.getElementById('data').textContent);

/*CORE-BEGIN*/
const CORE = (() => {
  const med = a => { if(!a.length) return null; const b=a.slice().sort((x,y)=>x-y), m=b.length>>1; return b.length%2 ? b[m] : (b[m-1]+b[m])/2; };
  const quant = (a,q) => { if(!a.length) return null; const b=a.slice().sort((x,y)=>x-y), i=(b.length-1)*q, lo=Math.floor(i), hi=Math.ceil(i); return b[lo]+(b[hi]-b[lo])*(i-lo); };
  const winsorMean = (a,q=0.01) => { if(!a.length) return null; const lo=quant(a,q), hi=quant(a,1-q); return a.reduce((t,x)=>t+Math.min(hi,Math.max(lo,x)),0)/a.length; };
  const annualize = (x,h) => x==null ? null : Math.pow(1+x, 252/h)-1;
  const band = (c,vol,h) => { if(c==null||!vol) return null; const sd=vol*Math.sqrt(h/252), m=Math.log(1+c); return [Math.exp(m-sd)-1, Math.exp(m+sd)-1]; };
  function niceTicks(lo, hi, n){
    if(!(hi>lo)) hi = lo + 1;
    const span=hi-lo, mag=Math.pow(10, Math.floor(Math.log10(span/n)));
    const step=[1,2,2.5,5,10].map(s=>s*mag).find(s=>span/s<=n);
    const out=[]; for(let v=Math.floor(lo/step)*step; v<hi+step*0.999; v+=step) out.push(+v.toFixed(10));
    return out;
  }
  function decodeBT(bt){
    if(!bt || !bt.P) return bt;
    const n=bt.O.length, R=a=>{ const o=new Array(n).fill(null); (a||[]).forEach((x,i)=>{ o[i] = x==null ? null : x/1000; }); return o; };
    return {...bt, ev: bt.ev.map(e=>[bt.P[e[0]], e[1], e[2].map(x=>[bt.I[x>>1], x&1 ? 'n':'a']), e[3], R(e[4]), e[5]]), spy: bt.spy.map(R)};
  }
  function evCount(ev, F){
    let b=ev[2]; if(F.newOnly) b=b.filter(x=>x[1]==='n');
    if(!b.length) return -1;
    if(F.anchorSet && !b.some(x=>F.anchorSet.has(x[0]))) return -1;
    return F.basis==='buy' ? b.length : ev[3];
  }
  function stats(bt, F, before, k, bucket){
    const O=bt.O, ik=O.indexOf(k), out={};
    const evs=bt.ev.filter(ev=>{ if(before && ev[0]>=before) return false; const n=evCount(ev,F); if(n<F.minN) return false; return bucket==null || (bucket>=4 ? n>=4 : n===bucket); });
    for(const [hk,h] of Object.entries(bt.H)){
      const ih=O.indexOf(k+h), r=[], ex=[];
      for(const ev of evs){ const R=ev[4], S=bt.spy[ev[5]]; if(R[ik]==null||R[ih]==null) continue;
        const x=(1+R[ih])/(1+R[ik])-1; r.push(x);
        if(S && S[ik]!=null && S[ih]!=null) ex.push(x-((1+S[ih])/(1+S[ik])-1)); }
      out[hk]={h, n:r.length, med:med(r), mean:winsorMean(r), hit:r.length ? r.filter(x=>x>0).length/r.length : null, ex:med(ex), p16:quant(r,0.16), p84:quant(r,0.84)};
    }
    out.nev=evs.length; return out;
  }
  function trackRecord(bt, F){
    const O=bt.O, i63=O.indexOf(63), i252=O.indexOf(252), all={}, hit={};
    for(const ev of bt.ev){ (all[ev[0]] ||= []).push(ev); if(evCount(ev,F)>=F.minN) (hit[ev[0]] ||= []).push(ev); }
    const avg=a=>a.length ? a.reduce((t,x)=>t+x,0)/a.length : null;
    const col=(evs,i,spy)=>evs.map(ev=>spy ? (bt.spy[ev[5]]||[])[i] : ev[4][i]).filter(x=>x!=null);
    const rows=[], curve=[]; let nav=1, snav=1, peak=1, mdd=0, wins=0, q=0;
    for(const p of Object.keys(all).sort()){
      const evs=hit[p]||[];
      const s3=avg(col(evs.length ? evs : all[p], i63, true));
      const r3=evs.length ? avg(col(evs,i63,false)) : (s3==null ? null : 0);
      rows.push({p, n:evs.length, r3, s3, r1:avg(col(evs,i252,false)), s1:avg(col(evs,i252,true))});
      if(r3==null || s3==null) continue;
      nav*=1+r3; snav*=1+s3; q++; if(r3>s3) wins++;
      peak=Math.max(peak,nav); mdd=Math.min(mdd,nav/peak-1);
      curve.push({p, nav, snav});
    }
    const yrs=q/4;
    return {rows, curve, q, cagr: q ? Math.pow(nav,1/yrs)-1 : null, scagr: q ? Math.pow(snav,1/yrs)-1 : null, mdd, win: q ? wins/q : null};
  }
  return {med, quant, winsorMean, annualize, band, niceTicks, decodeBT, evCount, stats, trackRecord};
})();
/*CORE-END*/

const BT = CORE.decodeBT(DATA.bt);
const INV = Object.fromEntries(DATA.investors.map(i=>[i.id,i]));
const BUY = new Set(['new','add']), HOLDN = new Set(['new','first','add','hold','reduce']);
const TL = {new:'신규',first:'첫13F',add:'추가',hold:'유지',reduce:'축소',sold:'매도'};
const HL = {'1w':'1주','1m':'1달','1y':'1년','3y':'3년','5y':'5년'};
const HZ = BT ? Object.entries(BT.H) : [];
const FILINGS = DATA.filings || [];
const periods = Object.keys(DATA.periods).sort().reverse();
const activeN = DATA.investors.filter(i=>i.status==='ok').length || DATA.investors.length;
document.getElementById('demo').hidden = !DATA.demo;

let S = {win:'q', anchor:'A', basis:'buy', minN:2, newOnly:false, sort:'n', exp:'med', fk:'all', q:'', period:null};
try{ Object.assign(S, JSON.parse(localStorage.getItem('13f-radar-v2')||'{}')); }catch(e){}
S.q=''; S.period = periods.find(p=>DATA.periods[p].filed.length >= activeN*0.5) || periods[0];
const save = () => { try{ const {q, period, ...keep} = S; localStorage.setItem('13f-radar-v2', JSON.stringify(keep)); }catch(e){} };

const esc = s => String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtUSD = v => v>=1e9 ? '$'+(v/1e9).toFixed(2)+'B' : v>=1e6 ? '$'+(v/1e6).toFixed(1)+'M' : v>=1e3 ? '$'+Math.round(v/1e3)+'K' : '$'+Math.round(v);
const fmtN = v => Math.round(v).toLocaleString('en-US');
const fmtPx = v => v==null ? '–' : '$'+v.toLocaleString('en-US',{minimumFractionDigits:2, maximumFractionDigits:2});
const fmtKRW = v => v==null ? '' : '₩'+Math.round(v).toLocaleString('ko-KR');
const fp = (v,d=1) => v==null||!isFinite(v) ? '–' : (v>0?'+':'')+(Math.abs(v)>=1 ? (v*100).toFixed(0) : (v*100).toFixed(d))+'%';
const cls = v => v==null ? 'mut' : (v>0 ? 'pos' : (v<0 ? 'neg' : 'mut'));
const pctChg = a => a.psh>0 ? '+'+((a.sh/a.psh-1)*100).toFixed(0)+'%' : '';
const yahoo = tk => `https://finance.yahoo.com/quote/${encodeURIComponent(tk.replace(/[\/.]/g,'-'))}`;
const edgarFiling = (cik, acc) => `https://www.sec.gov/Archives/edgar/data/${parseInt(cik,10)}/${acc.replace(/-/g,'')}/`;
const premTxt = p => p==null ? '–' : (p<0 ? `<span class="pos">${(p*100).toFixed(1)}% 싸게</span>` : `<span>+${(p*100).toFixed(1)}% 비싸게</span>`);
const normTk = t => (t||'').replace(/[\/.]/g,'-').toUpperCase();

function addDays(iso,n){ const d=new Date(iso+'T00:00:00Z'); d.setUTCDate(d.getUTCDate()+n); return d.toISOString().slice(0,10); }
function deadline(pe){ const d=new Date(pe+'T00:00:00Z'); d.setUTCDate(d.getUTCDate()+45); while([0,6].includes(d.getUTCDay())) d.setUTCDate(d.getUTCDate()+1); return d.toISOString().slice(0,10); }
function qEndAfter(iso){ const d=new Date(iso+'T00:00:00Z'), y=d.getUTCFullYear(), qm=Math.floor(d.getUTCMonth()/3)*3+2; return new Date(Date.UTC(y,qm+1,0)).toISOString().slice(0,10); }
const gen = DATA.generated_at, today = gen.slice(0,10);
const filedOf = p => Object.fromEntries((DATA.periods[p] ? DATA.periods[p].filed : []).map(x=>[x.inv,x]));
function latestFilingDay(){ let m=''; for(const p of periods) for(const f of DATA.periods[p].filed) if(f.last_filed>m) m=f.last_filed; return m||today; }
function winStart(){ if(S.win==='d1') return latestFilingDay(); if(S.win==='d7') return addDays(today,-6); if(S.win==='d30') return addDays(today,-29); return '0000'; }
function anchorSet(){ if(S.anchor==='buffett') return new Set(['buffett']); if(S.anchor==='A') return new Set(DATA.investors.filter(i=>i.tier==='A').map(i=>i.id)); return null; }
const filt = () => ({anchorSet:anchorSet(), basis:S.basis, minN:S.minN, newOnly:S.newOnly});

const recentByTk = {};
for(const f of FILINGS){ if(f.tk) (recentByTk[normTk(f.tk)] ||= []).push(f); }
const isBuyFiling = f => f.kind==='buy' || (f.kind==='stake' && !f.form.endsWith('/A'));

// ---------- 기대수익 ----------
const btCache = new Map();
function btStats(k, bucket){
  const key=[S.period,S.anchor,S.basis,S.minN,S.newOnly,k,bucket].join('|');
  if(!btCache.has(key)) btCache.set(key, CORE.stats(BT, filt(), S.period, k, bucket));
  return btCache.get(key);
}
function stockExp(r){
  if(!BT) return null;
  const px=r.s.px;
  if(px && px.ok===false) return null;
  const el=px ? px.el : 0, k=BT.K.filter(x=>x<=el).pop() ?? 0, bucket=Math.min(r.n,4);
  let st=btStats(k,bucket), basis=`같은 인원(${bucket>=4?'4명+':bucket+'명'}) 시그널`;
  if(st['1y'].n < 30){ st=btStats(k,null); basis='현재 조건 전체 시그널'; }
  return {k, st, basis};
}
const expVal = v => S.exp==='mean' ? v.mean : v.med;

// ---------- 시그널 목록 ----------
function compute(){
  const P=DATA.periods[S.period]; if(!P) return [];
  const anc=anchorSet(), ws=winStart(), q=S.q.trim().toLowerCase(), out=[];
  for(const s of P.stocks){
    if(s.split) continue;
    const buyers=s.actions.filter(a=>BUY.has(a.t) && (!S.newOnly || a.t==='new'));
    if(!buyers.length) continue;
    const holders=s.actions.filter(a=>HOLDN.has(a.t));
    if(anc && !buyers.some(a=>anc.has(a.inv))) continue;
    const n=S.basis==='buy' ? buyers.length : holders.length;
    if(n<S.minN) continue;
    if(!buyers.some(a=>a.f>=ws)) continue;
    if(q && !((s.tk||'').toLowerCase().includes(q) || s.name.toLowerCase().includes(q))) continue;
    const r={s, buyers, holders, n, ancN: anc ? buyers.filter(a=>anc.has(a.inv)).length : 0,
      val: buyers.reduce((t,a)=>t+a.v,0), last: buyers.reduce((m,a)=>a.f>m?a.f:m,'')};
    r.X=stockExp(r); out.push(r);
  }
  const base=(a,b)=>b.n-a.n || b.ancN-a.ancN || b.val-a.val;
  const e1=r=>{ const v=r.X&&r.X.st['1y']; return v&&v.n>=10 ? expVal(v) : -Infinity; };
  const pr=r=>r.s.px&&r.s.px.prem!=null ? r.s.px.prem : Infinity;
  const sorters={n:base, exp:(a,b)=>e1(b)-e1(a)||base(a,b), prem:(a,b)=>pr(a)-pr(b)||base(a,b), recent:(a,b)=>(a.last<b.last)-(a.last>b.last)||base(a,b)};
  return out.sort(sorters[S.sort]||base);
}

function rowHTML(r, anc, fl){
  const s=r.s, px=s.px, X=r.X;
  const chips=r.buyers.slice().sort((a,b)=>((anc&&anc.has(b.inv))-(anc&&anc.has(a.inv))) || b.v-a.v).map(a=>{
    const i=INV[a.inv]||{label:a.inv,fund:''};
    return `<span class="chip ${a.t==='add'?'add':'new'} ${anc&&anc.has(a.inv)?'anchor':''}" title="${esc(i.fund)} · 포트폴리오 ${a.w.toFixed(2)}%"><b>${TL[a.t]}</b>${esc(i.label)}${a.t==='add'?' '+pctChg(a):''}</span>`;}).join('');
  const rb=(recentByTk[normTk(s.tk)]||[]).filter(isBuyFiling);
  const badge=rb.length ? `<span class="badge" title="${esc(rb.map(f=>`${f.d} ${(INV[f.inv]||{}).label||f.inv} ${f.form}`).join('\n'))}">수시매수 ${rb[0].d.slice(5)}</span>` : '';
  const L=[];
  if(px){
    L.push(`현재가 <b>${fmtPx(px.last)}</b>${px.krw?` <span class="mut">${fmtKRW(px.krw)}</span>`:''} <span class="mut">(${px.d})</span> · 공시 후 <span class="${cls(px.since)}">${fp(px.since)}</span> · ${px.el}거래일 경과`);
    if(px.vwap) L.push(`추정 매입가 ${fmtPx(px.vwap)} <span class="mut">(분기 ${fmtPx(px.qlo)}~${fmtPx(px.qhi)})</span> → 지금 ${premTxt(px.prem)}`);
    const ex=[];
    if(px.hi52) ex.push(`52주 고점 대비 ${fp(px.last/px.hi52-1)}`);
    if(s.an && s.an.mean) ex.push(`애널리스트 목표가 ${fmtPx(s.an.mean)} (${fp(s.an.mean/px.last-1)}, ${s.an.n||'?'}명·참고)`);
    if(ex.length) L.push(`<span class="mut">${ex.join(' · ')}</span>`);
    if(px.ok===false) L.push('<span class="bad">티커 확인 필요 — 13F 평가가격과 주가가 맞지 않아 기대수익을 숨겼습니다</span>');
  } else L.push(`<span class="mut">${s.tk ? '현재가 없음(주가 수집 실패)' : '현재가 없음(티커 미확인)'}</span>`);
  const strip=X ? `<div class="exp" title="${esc(X.basis)} · 공시 후 ${X.k}거래일 시점 매수 기준 ${S.exp==='mean'?'평균':'중앙값'}">${HZ.map(([hk])=>{ const v=X.st[hk];
    return `<div class="${v.n<30?'thin':''}"><span>${HL[hk]}</span><b class="${cls(expVal(v))}">${v.n>=10 ? fp(expVal(v)) : '–'}</b></div>`; }).join('')}</div>` : '';
  return `<details class="row"><summary>
    <div class="tk">${esc(s.tk||'—')}<small>${esc(s.cusip)}</small></div>
    <div><div class="nm">${esc(s.name)}<small>${esc(s.cls)}</small>${badge}</div><div class="chips">${chips}</div><div class="pxl">${L.join('<br>')}</div>${strip}</div>
    <div class="score">${r.n}<small>${S.basis==='buy'?'매수':'보유'} · 보유 ${r.holders.length}명</small><small>${fmtUSD(r.val)} · ${r.last}</small></div>
  </summary><div class="detail">${detailHTML(r, fl)}</div></details>`;
}

function detailHTML(r, fl){
  const s=r.s, px=s.px, X=r.X;
  let h = s.tk ? `<div class="links"><a href="${yahoo(s.tk)}" target="_blank" rel="noopener">Yahoo Finance에서 ${esc(s.tk)} 보기</a></div>` : '';
  if(X){
    h += `<div class="sub">지금 사면 — 기대수익(과거 기저율)</div><table><thead><tr><th>보유기간</th><th>중앙값</th><th>평균</th><th>연환산</th><th>68% 범위</th><th>상승확률</th><th>SPY 대비</th><th>표본</th></tr></thead><tbody>${HZ.map(([hk,hd])=>{
      const v=X.st[hk], ok=v.n>=10, b=ok ? CORE.band(v.med, px&&px.vol, hd) : null;
      return `<tr class="${v.n<30?'thin':''}"><td>${HL[hk]}</td><td class="n ${cls(v.med)}">${ok?fp(v.med):'–'}</td><td class="n ${cls(v.mean)}">${ok?fp(v.mean):'–'}</td><td class="n">${ok&&hd>=756?fp(CORE.annualize(v.med,hd)):'–'}</td><td class="n">${b?fp(b[0])+' ~ '+fp(b[1]):'–'}</td><td class="n">${ok&&v.hit!=null?(v.hit*100).toFixed(0)+'%':'–'}</td><td class="n ${cls(v.ex)}">${ok?fp(v.ex):'–'}</td><td class="n">${v.n.toLocaleString()}</td></tr>`; }).join('')}</tbody></table>
      <p class="cap">기준: ${esc(X.basis)}, 공시 후 ${X.k}거래일 지난 시점에 샀다고 보고 계산${px&&px.vol?` · 범위는 이 종목 1년 변동성 ${(px.vol*100).toFixed(0)}%로 그린 약 68% 구간`:''}. 표본 10건 미만은 –, 30건 미만은 흐리게. 예측이 아니라 과거 기저율입니다.</p>`;
  }
  if(px && px.vwap) h += `<div class="sub">추정 매입가 — ${S.period} 분기</div><p class="cap">해당 분기 거래량 가중 평균가(VWAP) ${fmtPx(px.vwap)}, 분기 저가 ${fmtPx(px.qlo)} · 고가 ${fmtPx(px.qhi)}. 현재가 ${fmtPx(px.last)}는 VWAP보다 ${premTxt(px.prem)}. 실제 매입가는 공시되지 않으며 분기 중 매수 시점에 따라 저가~고가 사이입니다.</p>`;
  const rf=recentByTk[normTk(s.tk)]||[];
  if(rf.length) h += `<div class="sub">최근 수시 공시</div>${filingsTable(rf)}`;
  const rows=s.actions.slice().sort((a,b)=>b.v-a.v).map(a=>{ const i=INV[a.inv]||{label:a.inv,fund:''}, f=fl[a.inv];
    const link=f&&f.accs&&f.accs.length ? `<a href="${edgarFiling(f.cik, f.accs[f.accs.length-1])}" target="_blank" rel="noopener">${a.f}</a>` : a.f;
    return `<tr><td>${esc(i.label)} <span class="mut">${esc(i.fund)}</span></td><td><span class="t ${a.t}">${TL[a.t]}</span></td><td class="n">${fmtN(a.psh)}</td><td class="n">${fmtN(a.sh)}</td><td class="n">${a.v?fmtUSD(a.v):'–'}</td><td class="n">${a.w?a.w.toFixed(2)+'%':'–'}</td><td>${link}</td></tr>`; }).join('');
  return h + `<div class="sub">투자자별 변화</div><table><thead><tr><th>투자자</th><th>변화</th><th>직전 주식수</th><th>현재 주식수</th><th>평가액</th><th>비중</th><th>공시일(원문)</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderList(){
  const rows=compute(), anc=anchorSet(), fl=filedOf(S.period);
  const wl={d1:`최근 공시일(${latestFilingDay()})`, d7:'최근 7일', d30:'최근 30일', q:'분기 전체'}[S.win];
  const al={buffett:'버핏(버크셔)이', A:'레전드군 1명 이상이', any:'누구든'}[S.anchor];
  document.getElementById('rule').innerHTML=`조건: <b>${S.period}</b> 분기에 <b>${al}</b> ${S.newOnly?'<b>신규</b> ':''}매수했고, ${S.basis==='buy'?'같은 분기 매수자':'매수+보유자'}가 <b>${S.minN}명 이상</b>, 매수 공시가 <b>${wl}</b>에 나온 종목`;
  document.getElementById('cnt').textContent=rows.length+'개';
  const el=document.getElementById('list');
  el.innerHTML = rows.length ? rows.map(r=>rowHTML(r, anc, fl)).join('') : `<div class="empty">조건에 맞는 종목이 없습니다. 공시 기간을 '분기 전체'로 넓히거나 최소 투자자 수를 낮춰보세요.</div>`;
}

// ---------- 수시 공시 ----------
const KIND = {buy:'장내매수', sell:'장내매도'};
const kindLabel = f => f.kind==='stake' ? (f.form.endsWith('/A') ? '지분 변경' : '5%+ 신규') : KIND[f.kind];
const formShort = f => f.form.startsWith('SCHEDULE') ? f.form.replace('SCHEDULE ','') : 'Form '+f.form;
function filingsTable(rows){
  return `<table><thead><tr><th>공시일</th><th>투자자</th><th>종목</th><th>구분</th><th>주식수</th><th>평균가</th><th>금액</th><th>지분율</th><th>현재가</th></tr></thead><tbody>${rows.map(f=>{
    const i=INV[f.inv]||{label:f.inv};
    const now=f.now!=null ? `${fmtPx(f.now)}${f.px?` <span class="${cls(f.now/f.px-1)}">(${fp(f.now/f.px-1)})</span>`:''}` : '–';
    return `<tr><td><a href="${edgarFiling(f.cik,f.acc)}" target="_blank" rel="noopener">${f.d}</a></td><td>${esc(i.label)}</td><td><b>${esc(f.tk||'—')}</b> <span class="mut">${esc(f.name)}</span></td><td><span class="t ${f.kind==='sell'?'sold':f.kind==='buy'?'add':'new'}">${kindLabel(f)}</span> <span class="mut">${formShort(f)}</span></td><td class="n">${f.sh?fmtN(f.sh):'–'}</td><td class="n">${f.px?fmtPx(f.px):'–'}</td><td class="n">${f.val?fmtUSD(f.val):'–'}</td><td class="n">${f.pct!=null?f.pct.toFixed(1)+'%':'–'}</td><td class="n">${now}</td></tr>`; }).join('')}</tbody></table>`;
}
let fAll=false;
function renderFilings(){
  const K={all:()=>true, buy:f=>f.kind==='buy', sell:f=>f.kind==='sell', stake:f=>f.kind==='stake'};
  const rows=FILINGS.filter(K[S.fk]||K.all), el=document.getElementById('filings');
  document.getElementById('fcnt').textContent=`${rows.length}건 · 최근 90일`;
  if(!rows.length){ el.innerHTML='<div class="empty">해당하는 수시 공시가 없습니다.</div>'; return; }
  el.innerHTML = filingsTable(fAll ? rows : rows.slice(0,8)) + (rows.length>8 ? `<button class="more" id="fmore">${fAll ? '접기' : `전체 ${rows.length}건 보기`}</button>` : '');
  const b=document.getElementById('fmore'); if(b) b.onclick=()=>{ fAll=!fAll; renderFilings(); };
}

// ---------- 상태·투자자·백테스트 ----------
function renderStatus(){
  const P=DATA.periods[S.period], fn=P ? P.filed.length : 0, nextPE=qEndAfter(today), lastQ=qEndAfter(addDays(today,-92));
  const nd = deadline(lastQ)>today ? [deadline(lastQ), lastQ] : [deadline(nextPE), nextPE];
  document.getElementById('status').innerHTML=`
    <div><span class="k">보고 분기</span><span class="v">${S.period} <em>분기말</em></span></div>
    <div><span class="k">제출 현황</span><span class="v">${fn}<em> / ${activeN}명</em></span><div class="bar"><i style="width:${Math.min(100,fn/activeN*100)}%"></i></div></div>
    <div><span class="k">해당 분기 제출기한</span><span class="v">${deadline(S.period)}</span></div>
    <div><span class="k">다음 시즌 기한</span><span class="v">${nd[0]}<em> · ${nd[1]} 분기</em></span></div>`;
  const kst=new Date(gen).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',dateStyle:'medium',timeStyle:'short'});
  const fx=DATA.fx ? ` · ₩${DATA.fx.krw.toLocaleString('ko-KR')}/$` : '';
  document.getElementById('stamp').innerHTML=`업데이트 ${kst} KST<br>주가 ${DATA.price_date||'–'} 종가${fx}<br>최근 공시일 ${latestFilingDay()}`;
  const st=document.getElementById('stale'), lag=DATA.price_date ? (new Date(gen)-new Date(DATA.price_date+'T00:00:00Z'))/864e5 : 99;
  st.hidden = lag<=4;
  st.textContent = `주가가 ${DATA.price_date||'없음'} 기준입니다 — 최근 수집이 실패했을 수 있어요. 현재가·기대수익은 그 날짜 기준입니다.`;
}
function renderInv(){
  const f=filedOf(S.period), lab={cik_mismatch:'CIK 불일치', no_filings:'13F 없음'};
  const rows=DATA.investors.slice().sort((a,b)=>(a.tier>b.tier)-(a.tier<b.tier) || ((f[b.id]?1:0)-(f[a.id]?1:0))).map(i=>{
    const x=f[i.id];
    let st;
    if(x) st=`<a href="${edgarFiling(x.cik, x.accs[x.accs.length-1])}" target="_blank" rel="noopener">${x.last_filed}</a>`;
    else if(i.status==='inactive') st=`<span class="mut">공시 중단 · 최근 ${i.last_period||'–'}</span>`;
    else if(i.status==='ok') st='<span class="mut">미제출</span>';
    else st=`<span class="bad">${esc(lab[i.status]||i.status)}</span>`;
    const notes=(i.notes||[]).join('\n');
    const fol=(i.followed||[]).length ? ' <span class="badge" title="13F-NT를 따라 새 보고 법인을 자동 추적">자동 추적</span>' : '';
    return `<tr${notes?` title="${esc(notes)}"`:''}><td>${i.tier==='A'?'<b>':''}${esc(i.label)}${i.tier==='A'?'</b>':''}${fol}<br><span class="mut" style="font-size:12px">${esc(i.fund)}</span></td><td>${st}</td><td class="n">${x?x.n:'–'}</td><td class="n">${x?fmtUSD(x.aum):'–'}</td></tr>`; }).join('');
  document.getElementById('invtbl').innerHTML=`<thead><tr><th>투자자</th><th>공시일(원문)</th><th>종목수</th><th>13F 평가액</th></tr></thead><tbody>${rows}</tbody>`;
  document.getElementById('invcnt').textContent='굵게 = 레전드군';
}
function renderBT(){
  const t=document.getElementById('bttbl'), note=document.getElementById('btnote');
  if(!BT){ t.innerHTML=''; note.innerHTML='<p>백테스트 데이터가 아직 없습니다.</p>'; return; }
  const st=CORE.stats(BT, filt(), S.period, 0, null);
  document.getElementById('btmeta').textContent=`공시 다음날 매수 · 시그널 ${st.nev.toLocaleString()}건`;
  t.innerHTML=`<thead><tr><th>보유기간</th><th>표본</th><th>중앙값</th><th>평균</th><th>16~84%</th><th>상승확률</th><th>SPY 대비</th></tr></thead><tbody>${HZ.map(([hk,hd])=>{ const x=st[hk];
    const ann=hd>=756 && x.n>=10 ? `<br><span class="mut">연 ${fp(CORE.annualize(x.med,hd))}</span>` : '';
    return `<tr class="${x.n<30?'thin':''}"><td>${HL[hk]}</td><td class="n">${x.n.toLocaleString()}</td><td class="n ${cls(x.med)}">${fp(x.med)}${ann}</td><td class="n ${cls(x.mean)}">${fp(x.mean)}</td><td class="n">${x.n?fp(x.p16)+' ~ '+fp(x.p84):'–'}</td><td class="n">${x.hit==null?'–':(x.hit*100).toFixed(0)+'%'}</td><td class="n ${cls(x.ex)}">${fp(x.ex)}</td></tr>`; }).join('')}</tbody>`;
  const s2=BT.stats||{};
  note.innerHTML=`<p>${S.period} 이전 분기 시그널만 사용(미래 정보 차단). 재계산 ${BT.built}. 과거 시그널 ${(s2.total||0).toLocaleString()}건 중 주가 없음 ${(s2.nopx||0).toLocaleString()}건·티커 불일치 ${(s2.mismatch||0).toLocaleString()}건 제외 — 상장폐지 종목이 빠지므로 <b>수익률이 위로 치우칩니다(생존편향)</b>. 평균은 상·하위 1% 윈저화. 거래비용·세금·환율 미반영. 3·5년은 표본이 적고 서로 겹칩니다.</p>`;
}

// ---------- 트랙레코드 ----------
let lastCurve=[];
function drawChart(wrap, curve){
  if(curve.length<2){ wrap.innerHTML='<div class="empty">표시할 분기가 부족합니다.</div>'; return; }
  const pts=[{p:null,nav:1,snav:1}, ...curve];
  const W=Math.max(300, Math.round(wrap.clientWidth-32) || 640), narrow=W<520, H=narrow?220:260;
  const m={l:46, r:narrow?14:122, t:14, b:28}, iw=W-m.l-m.r, ih=H-m.t-m.b;
  const vals=pts.flatMap(d=>[d.nav,d.snav]), ticks=CORE.niceTicks(Math.min(...vals), Math.max(...vals), 4);
  const lo=ticks[0], hi=ticks[ticks.length-1];
  const X=i=>m.l+iw*i/(pts.length-1), Y=v=>m.t+ih*(1-(v-lo)/((hi-lo)||1));
  const path=k=>pts.map((d,i)=>`${i?'L':'M'}${X(i).toFixed(1)},${Y(d[k]).toFixed(1)}`).join('');
  let xl='', lastX=-1e9;
  pts.forEach((d,i)=>{ if(!d.p) return; const yr=d.p.slice(0,4), prev=pts[i-1]&&pts[i-1].p; if(prev&&prev.slice(0,4)===yr) return;
    const x=X(i); if(x-lastX<(narrow?34:44)) return; lastX=x; xl+=`<text x="${x.toFixed(1)}" y="${H-8}" text-anchor="middle">${narrow?"'"+yr.slice(2):yr}</text>`; });
  const fmtT=t=>'×'+(Math.abs(t-Math.round(t))<1e-9 ? t.toFixed(0) : t.toFixed(1));
  const grid=ticks.map(t=>`<line x1="${m.l}" x2="${W-m.r}" y1="${Y(t).toFixed(1)}" y2="${Y(t).toFixed(1)}" class="gl"/><text x="${m.l-8}" y="${(Y(t)+4).toFixed(1)}" text-anchor="end">${fmtT(t)}</text>`).join('');
  const L=pts[pts.length-1], xe=X(pts.length-1), ya=Y(L.nav), yb=Y(L.snav);
  const lab=!narrow && Math.abs(ya-yb)>=16 ? `<g class="dl"><line x1="${xe+8}" x2="${xe+20}" y1="${ya}" y2="${ya}" class="ka"/><text x="${xe+24}" y="${ya+4}">전략 ×${L.nav.toFixed(2)}</text><line x1="${xe+8}" x2="${xe+20}" y1="${yb}" y2="${yb}" class="kb"/><text x="${xe+24}" y="${yb+4}">S&amp;P500 ×${L.snav.toFixed(2)}</text></g>` : '';
  wrap.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="현재 조건 전략과 S&amp;P500의 1달러 성장 비교. 수치는 아래 분기별 표에 있습니다." tabindex="0">
    <g>${grid}${xl}</g>
    <path d="${path('snav')}" class="lb"/><path d="${path('nav')}" class="la"/>
    <circle cx="${xe}" cy="${yb}" r="4" class="db"/><circle cx="${xe}" cy="${ya}" r="4" class="da"/>${lab}
    <line class="xh" x1="0" x2="0" y1="${m.t}" y2="${H-m.b}" visibility="hidden"/>
    <circle class="db hb" r="4" visibility="hidden"/><circle class="da ha" r="4" visibility="hidden"/>
    <rect x="${m.l}" y="0" width="${iw}" height="${H}" fill="transparent"/>
  </svg><div class="tip" role="status" aria-live="polite"></div>`;
  const svg=wrap.querySelector('svg'), tip=wrap.querySelector('.tip'), xh=svg.querySelector('.xh'), ha=svg.querySelector('.ha'), hb=svg.querySelector('.hb');
  let cur=-1;
  function show(i){
    cur=Math.max(0, Math.min(pts.length-1, i)); const d=pts[cur], x=X(cur);
    for(const [el,y] of [[ha,Y(d.nav)],[hb,Y(d.snav)]]){ el.setAttribute('cx',x); el.setAttribute('cy',y); el.setAttribute('visibility','visible'); }
    xh.setAttribute('x1',x); xh.setAttribute('x2',x); xh.setAttribute('visibility','visible');
    tip.replaceChildren();
    const hd=document.createElement('div'); hd.className='tt'; hd.textContent = d.p ? `${d.p} 코호트까지` : '시작(1달러)'; tip.append(hd);
    for(const [k,label,c] of [['nav','전략','ka'],['snav','S&P500','kb']]){
      const row=document.createElement('div'), key=document.createElement('i'), b=document.createElement('b'), sp=document.createElement('span');
      key.className=c; b.textContent='×'+d[k].toFixed(2); sp.textContent=' '+label; row.append(key,b,sp); tip.append(row);
    }
    tip.style.display='block';
    const scale=svg.getBoundingClientRect().width/W;
    tip.style.left=Math.max(16, Math.min(16+x*scale+12, wrap.clientWidth-tip.offsetWidth-8))+'px';
  }
  function hide(){ for(const el of [xh,ha,hb]) el.setAttribute('visibility','hidden'); tip.style.display='none'; }
  svg.addEventListener('pointermove', e=>{ const bx=svg.getBoundingClientRect(); show(Math.round(((e.clientX-bx.left)*W/bx.width-m.l)/iw*(pts.length-1))); });
  svg.addEventListener('pointerleave', hide);
  svg.addEventListener('focus', ()=>show(pts.length-1));
  svg.addEventListener('blur', hide);
  svg.addEventListener('keydown', e=>{ if(e.key==='ArrowLeft'){ show(cur-1); e.preventDefault(); } else if(e.key==='ArrowRight'){ show(cur+1); e.preventDefault(); } });
}
function renderTrack(){
  const tl=document.getElementById('trtiles'), ch=document.getElementById('trchart'), tb=document.getElementById('trtbl'), nt=document.getElementById('trnote');
  if(!BT){ tl.innerHTML=''; ch.innerHTML='<div class="empty">백테스트 데이터가 아직 없습니다.</div>'; tb.innerHTML=''; nt.innerHTML=''; lastCurve=[]; return; }
  const T=CORE.trackRecord(BT, filt()), E=T.curve[T.curve.length-1];
  document.getElementById('trmeta').textContent = T.q ? `${T.curve[0].p} ~ ${E.p} · ${T.q}개 분기` : '';
  const tile=(k,v,sub)=>`<div><span class="k">${k}</span><span class="tv">${v}<small>${sub}</small></span></div>`;
  tl.innerHTML = T.q ? tile('전략 연환산', fp(T.cagr), `S&amp;P500 ${fp(T.scagr)}`) + tile('최대낙폭', fp(T.mdd), '분기 기준')
    + tile('S&amp;P500 초과 분기', T.win==null ? '–' : (T.win*100).toFixed(0)+'%', `${T.q}개 중`) + tile('1달러는', '×'+E.nav.toFixed(2), `S&amp;P500 ×${E.snav.toFixed(2)}`) : '';
  lastCurve=T.curve; drawChart(ch, T.curve);
  tb.innerHTML=`<table><thead><tr><th>코호트 분기</th><th>시그널</th><th>3개월</th><th>SPY 3개월</th><th>1년</th><th>SPY 1년</th></tr></thead><tbody>${T.rows.slice().reverse().map(r=>`<tr><td>${r.p}</td><td class="n">${r.n}</td><td class="n ${cls(r.r3)}">${r.n ? fp(r.r3) : (r.r3===0 ? '현금' : '–')}</td><td class="n">${fp(r.s3)}</td><td class="n ${cls(r.r1)}">${fp(r.r1)}</td><td class="n">${fp(r.s1)}</td></tr>`).join('')}</tbody></table>`;
  nt.innerHTML='<p>각 분기(코호트)에 현재 조건을 만족한 시그널을 공시 다음 거래일에 같은 금액씩 사서 63거래일(약 3개월) 보유하고 다음 분기 시그널로 갈아탄다고 가정한 근사치입니다. 조건에 맞는 종목이 없던 분기는 현금(0%). 진입일이 공시 시즌에 흩어져 있어 실제 계좌 수익률과 다르고, 상장폐지 종목이 빠져 위로 치우칩니다. 거래비용·세금 미반영.</p>';
}
window.addEventListener('resize', ()=>{ clearTimeout(window.__rt); window.__rt=setTimeout(()=>{ if(lastCurve.length) drawChart(document.getElementById('trchart'), lastCurve); }, 150); });

// ---------- 바인딩 ----------
function bindSeg(id, key, fn){
  const el=document.getElementById(id);
  el.querySelectorAll('button').forEach(b=>{
    b.setAttribute('aria-pressed', String(b.dataset.v===S[key]));
    b.onclick=()=>{ S[key]=b.dataset.v; el.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed', String(x===b))); save(); (fn||render)(); };
  });
}
function render(){ renderStatus(); renderList(); renderInv(); renderBT(); renderTrack(); }
if(!periods.length){
  document.getElementById('list').innerHTML='<div class="empty">아직 수집된 13F가 없습니다.</div>';
} else {
  const psel=document.getElementById('period');
  psel.innerHTML=periods.map(p=>`<option value="${p}">${p} (${DATA.periods[p].filed.length}명 제출)</option>`).join('');
  psel.value=S.period; psel.onchange=()=>{ S.period=psel.value; render(); };
  bindSeg('win','win'); bindSeg('anchor','anchor'); bindSeg('basis','basis'); bindSeg('exp','exp'); bindSeg('fk','fk',renderFilings);
  const mn=document.getElementById('minN'); mn.value=String(S.minN); mn.onchange=()=>{ S.minN=+mn.value; save(); render(); };
  const so=document.getElementById('sort'); so.value=S.sort; so.onchange=()=>{ S.sort=so.value; save(); renderList(); };
  const no=document.getElementById('newOnly'); no.checked=S.newOnly; no.onchange=()=>{ S.newOnly=no.checked; save(); render(); };
  const qq=document.getElementById('q'); qq.oninput=()=>{ S.q=qq.value; renderList(); };
  renderFilings(); render();
}
document.body.dataset.ready='1';
})();
</script>
</body>
</html>
````

- [ ] **Step 4: Node 테스트 통과 확인** — Run: `cd ROOT && node --test tests/js/core.test.mjs` → Expected: `pass 9`, `fail 0`

- [ ] **Step 5: 실데이터로 페이지 재생성(네트워크 없이)** — `$SCRATCH/rerender.py`

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from build import render_html

data = json.loads(Path("docs/data.json").read_text(encoding="utf-8"))
Path("docs/index.html").write_text(render_html(Path("template.html").read_text(encoding="utf-8"), data), encoding="utf-8")
print("ok", round(Path("docs/index.html").stat().st_size / 1e6, 2), "MB")
```
Run: `cd ROOT && ~/.venvs/13f/bin/python $SCRATCH/rerender.py` → Expected: `ok <크기> MB`

- [ ] **Step 6: 헤드리스 브라우저 스모크(스크립트 끝까지 실행됐는지)**

Run:
```bash
cd ROOT && CH="/mnt/c/Program Files/Google/Chrome/Application/chrome.exe" && U="file:///$(wslpath -m "$PWD/docs/index.html")" && "$CH" --headless=new --disable-gpu --virtual-time-budget=8000 --dump-dom "$U" 2>/dev/null | grep -o 'data-ready="1"' | head -1
```
Expected: `data-ready="1"` (없으면 JS 예외 — 같은 명령에 `--enable-logging=stderr --v=0`를 붙여 콘솔 오류 확인)

- [ ] **Step 7: 커밋**
```bash
git add template.html tests/js/core.test.mjs
git commit -m "Rebuild dashboard UI: expected returns, cost basis, KRW, filings, track record chart"
```

---

### Task 14: 화면 검증(데스크톱·모바일·라이트·다크)

**Files:**
- Modify(필요 시): `template.html`
- Create(무시 폴더): `.shots/*.png`

- [ ] **Step 1: 스크린샷 4장 생성**

Run:
```bash
cd ROOT && mkdir -p .shots && CH="/mnt/c/Program Files/Google/Chrome/Application/chrome.exe" && B="file:///$(wslpath -m "$PWD/docs/index.html")" && for spec in "desk-light:1280:light" "desk-dark:1280:dark" "mob-light:390:light" "mob-dark:390:dark"; do IFS=: read n w t <<<"$spec"; "$CH" --headless=new --disable-gpu --hide-scrollbars --virtual-time-budget=8000 --window-size=$w,3200 --screenshot="$(wslpath -w "$PWD/.shots/$n.png")" "$B?theme=$t" 2>/dev/null; done; ls -la .shots
```
Expected: 4개 PNG 생성.

- [ ] **Step 2: 눈으로 확인** — Read 도구로 `.shots/*.png`를 열어 확인: (1) 가로 넘침·잘림 없음(모바일 390px), (2) 차트 선·축·범례·직접 라벨 겹침 없음, (3) 다크 모드 대비·배경, (4) 수시 공시 표·시그널 행·백테스트 표가 채워짐, (5) 빈 값이 "–"로 보임. 문제는 `template.html`에서 고치고 Task 13 Step 5~6과 이 태스크 Step 1을 반복.

- [ ] **Step 3: 커밋**(수정이 있었을 때)
```bash
git add template.html && git commit -m "Polish dashboard layout after visual review"
```

---

### Task 15: 배포 자동화와 문서

**Files:**
- Modify: `.github/workflows/update.yml`, `README.md`, `.gitignore`
- Remove from git: `docs/index.html` (빌드 산출물)

**Interfaces:**
- Consumes: `build.py`, `requirements*.txt`.
- Produces: 매일 23:00 UTC 실행 → 테스트 → 빌드 → `data/` 커밋 → Pages 배포.

- [ ] **Step 1: 워크플로 교체** — `.github/workflows/update.yml`

```yaml
name: update-13f
on:
  schedule:
    - cron: "0 23 * * *"     # 매일 08:00 KST (미 동부 전날 장 마감·공시 반영)
  workflow_dispatch:
    inputs:
      full_backtest:
        description: "백테스트 전체 재계산"
        type: boolean
        default: false
permissions:
  contents: write
  pages: write
  id-token: write
concurrency: { group: update-13f, cancel-in-progress: false }
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip, cache-dependency-path: requirements-dev.txt }
      - uses: actions/setup-node@v4
        with: { node-version: "22" }
      - run: pip install -r requirements-dev.txt
      - name: Tests
        run: |
          python -m pytest -q
          node --test tests/js/core.test.mjs
      - name: Build dashboard
        env:
          SEC_USER_AGENT: ${{ vars.SEC_USER_AGENT }}
          OPENFIGI_API_KEY: ${{ secrets.OPENFIGI_API_KEY }}
          FULL_BACKTEST: ${{ inputs.full_backtest && '1' || '' }}
        run: python build.py
      - name: Commit data cache
        run: |
          git config user.name  "13f-bot"
          git config user.email "13f-bot@users.noreply.github.com"
          git add data
          git diff --cached --quiet || git commit -m "13F data $(date -u +%F)"
          git push
      - uses: actions/upload-pages-artifact@v3
        with: { path: docs }
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment: { name: github-pages, url: "${{ steps.deploy.outputs.page_url }}" }
    steps:
      - id: deploy
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: .gitignore와 산출물 정리**

`.gitignore`에 추가:
```
docs/
.shots/
```
Run: `cd ROOT && git rm -r --cached docs -q && git status --short | head`
Expected: `D  docs/index.html` 표시.

- [ ] **Step 3: README 교체** — `README.md`

```markdown
# 13F 컨센서스 레이더

버핏 등 앵커 투자자가 매수했고 거물급 투자자 여러 명이 같은 분기에 함께 투자한 미국 주식을
SEC EDGAR 13F 원자료에서 골라, **지금 가격에 샀을 때의 기대수익(1주·1달·1년·3년·5년)** 과 함께 보여주는 정적 대시보드입니다.
GitHub Actions가 매일 08:00(KST)에 새 공시·주가를 반영해 GitHub Pages에 게시합니다.

## 화면에서 보는 것
- **시그널 종목**: 조건(앵커·동시 투자 인원·매수/보유·신규만·공시 기간)에 맞는 종목, 투자자별 변화와 공시 원문 링크
- **지금 사면 기대수익**: 같은 조건 과거 시그널(2013년~)의 중앙값·평균·연환산·68% 범위·상승확률·S&P500 대비
- **추정 매입가**: 매수 분기의 거래량 가중 평균가 대비 현재가(더 싸게 사는지)
- **원화 가격·52주 위치·애널리스트 목표가**(참고)
- **수시 공시**: 최근 90일 Form 4(10%+ 주주 장내 매매)·13D/13G(5%+ 지분) — 13F보다 빠른 신호
- **전략 트랙레코드**: 현재 조건으로 매 분기 샀다면(분기 교체) 연환산·최대낙폭·S&P500 초과 분기 비율

## 설치 (한 번)
1. GitHub에서 빈 저장소(Public)를 만들고 이 폴더를 push.
2. **Settings → Secrets and variables → Actions → Variables**에 `SEC_USER_AGENT` = `13F-Consensus 본인이메일` (SEC 정책상 필수).
3. (선택) **Secrets**에 `OPENFIGI_API_KEY` (https://www.openfigi.com/api 무료) — 새 CUSIP 매핑이 빨라집니다.
4. **Settings → Pages → Source: GitHub Actions**.
5. **Actions → update-13f → Run workflow**. 끝나면 `https://<아이디>.github.io/<저장소>/`.

## 로컬 실행
    python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
    SEC_USER_AGENT="이름 메일" python build.py      # docs/index.html 생성
    python -m pytest -q && node --test tests/js/    # 테스트

## 구조
- `investors.json` — 추적 투자자. `ciks`(법인 변경 시 여러 개), `expect`(EDGAR 등록명 확인), `tier: "A"` = 앵커군
- `build.py` — 진입점. `radar/` 모듈: `edgar`(13F 수집·파싱·병합), `classify`(변화 분류), `tickers`(OpenFIGI),
  `prices`(주가·검증·지표), `metrics`, `backtest`, `filings`(Form 4·13D/G)
- `data/` — 접수번호별 파싱 캐시, CUSIP→티커, 백테스트, 애널리스트 캐시(커밋됨). `docs/`는 빌드 산출물(배포만)

## 판정 규칙
- 매수 = 직전 분기 대비 신규 편입 또는 주식수 증가. 직전 13F 없는 투자자는 `첫13F`(매수로 안 셈)
- 수정신고: RESTATEMENT는 교체(주식수 같은 행은 원공시일 유지), NEW HOLDINGS는 합산(공개일 = 수정신고일)
- 같은 분기에 여러 CIK가 보고하면 평가액이 큰 쪽. 13F-NT로 다른 법인이 대신 보고하면 이름이 맞을 때 자동 추적
- value 단위(천달러/달러)는 평가액/주식수 중앙값으로 판정. 공시 합계·행 수와 대조해 불일치를 집계
- 옵션·PRN 제외. 모든 보유자 주식수가 같은 배수로 변하고 주가에도 분할 기록이 있으면 분할로 보고 매수에서 제외
- 티커 검증: 13F 평가가격과 분기말 실제 주가(분할 역산)가 0.8~1.25배 안이어야 백테스트·기대수익에 사용

## 기대수익 계산
과거 시그널(매수 1명+·보유 2명+)을 공시 다음 거래일 종가(배당 포함)에 샀다고 보고 5·21·252·756·1260거래일 수익률을 구합니다.
종목마다 공시 후 지난 거래일(0·21·63·126 격자)만큼 늦게 샀을 때로 다시 계산해 "지금 사면"을 만들고, 같은 인원 표본이
30건 미만이면 조건 전체 표본을 씁니다. 선택한 분기보다 이전 시그널만 사용(미래 정보 차단). 범위는 종목 1년 변동성 ±1σ.

## 한계
13F는 분기말 스냅샷(최대 45일 지연)이고 롱 포지션·미국 상장 증권만 보입니다. 상장폐지 종목이 빠져 수익률이 위로 치우칩니다(생존편향).
거래비용·세금·환율 변동 미반영. 기대수익은 과거 기저율이지 예측이 아닙니다. 투자 권유가 아닙니다.
```

- [ ] **Step 4: 전체 테스트 후 커밋**

Run: `cd ROOT && ~/.venvs/13f/bin/python -m pytest -q && node --test tests/js/core.test.mjs`
Expected: 모두 통과.
```bash
git add .github/workflows/update.yml README.md .gitignore
git commit -m "Deploy via GitHub Pages artifact with tests; update README"
```

- [ ] **Step 5: GitHub 저장소 연결(사용자 작업 포함)**
1. 사용자에게 GitHub 아이디를 묻고, https://github.com/new 에서 빈 Public 저장소 `13f-consensus` 생성을 요청(README 추가 안 함).
2. Run:
```bash
cd ROOT && git remote add origin https://github.com/<아이디>/13f-consensus.git && git config credential.helper "/mnt/c/Program\ Files/Git/mingw64/bin/git-credential-manager.exe" && git push -u origin main
```
Expected: Windows 브라우저 로그인 창 → 승인 후 push 완료. (명령이 대기에서 멈추면 사용자에게 `! git -C "ROOT" push -u origin main` 직접 실행을 안내)
3. 사용자에게 요청: Variables `SEC_USER_AGENT` = `13F-Consensus drchulfe@gmail.com`, Pages Source = GitHub Actions, Actions에서 `update-13f` → Run workflow.

- [ ] **Step 6: 원격 실행 확인**
- 사용자에게 워크플로 결과(성공/실패)를 받거나 공개 URL을 확인: `curl -s https://<아이디>.github.io/13f-consensus/ | grep -o '"generated_at":"[^"]*"'`
- Expected: 오늘 날짜의 `generated_at`. 실패면 Actions 로그의 첫 오류로 원인 확인(yfinance 차단이면 재시도·대체 소스 검토를 사용자와 상의).
```
