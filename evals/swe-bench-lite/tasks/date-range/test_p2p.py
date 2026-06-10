from datetime import date
from solution import date_range


def test_start_included():
    r = date_range(date(2026, 1, 1), date(2026, 1, 3))
    assert r[0] == date(2026, 1, 1)


def test_is_a_list_of_dates():
    r = date_range(date(2026, 1, 1), date(2026, 1, 5))
    assert isinstance(r, list)
    assert all(isinstance(d, date) for d in r)
