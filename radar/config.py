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
