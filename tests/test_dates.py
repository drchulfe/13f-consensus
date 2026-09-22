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
