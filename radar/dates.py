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
