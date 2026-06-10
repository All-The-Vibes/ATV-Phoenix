from datetime import date, timedelta


def date_range(start: date, end: date):
    """Return all dates from start to end INCLUSIVE."""
    days = []
    cur = start
    while cur < end:  # BUG: should be <= so the end date is included
        days.append(cur)
        cur += timedelta(days=1)
    return days
