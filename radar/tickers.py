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
        body = [{"idType": "ID_CINS" if c[:1].isalpha() else "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in chunk]
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
