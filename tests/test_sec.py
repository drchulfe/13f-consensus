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
