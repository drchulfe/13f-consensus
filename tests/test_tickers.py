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
