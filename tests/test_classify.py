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


def test_detect_split_survives_holders_who_also_traded():
    # 20:1 분할 분기: 한 명만 정확히 20배, 나머지는 분할 후 매매까지 함
    acts = [{"sh": 11560, "psh": 578}, {"sh": 598000, "psh": 33800}, {"sh": 1500000, "psh": 60000}]
    assert detect_split(acts) == 20
    # 분할이 아닌 실제 매수(1.5배·2.5배)는 분할로 보지 않는다
    assert detect_split([{"sh": 150, "psh": 100}, {"sh": 250, "psh": 100}]) is None


def test_buy_stocks_and_entry_date():
    P2 = {"filed": [], "stocks": [
        {"cusip": "A", "actions": [{"inv": "x", "t": "hold", "f": "2026-08-01"}]},
        {"cusip": "B", "actions": [{"inv": "x", "t": "new", "f": "2026-08-10"}, {"inv": "y", "t": "sold", "f": "2026-08-20"}]},
        {"cusip": "C", "split": 2, "actions": [{"inv": "x", "t": "hold", "t0": "add", "f": "2026-08-12"}]}]}
    assert [s["cusip"] for s in buy_stocks(P2)["stocks"]] == ["B", "C"]
    assert [s["cusip"] for s in buy_stocks(P2, use_t0=False)["stocks"]] == ["B"]
    assert entry_date(P2["stocks"][1]) == "2026-08-10"
