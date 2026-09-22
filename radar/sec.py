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
