from datetime import date
from solution import date_range


def test_includes_end_date():
    r = date_range(date(2026, 1, 1), date(2026, 1, 3))
    assert r[-1] == date(2026, 1, 3), "end date must be included"
    assert len(r) == 3


def test_single_day_inclusive():
    r = date_range(date(2026, 6, 10), date(2026, 6, 10))
    assert r == [date(2026, 6, 10)]
