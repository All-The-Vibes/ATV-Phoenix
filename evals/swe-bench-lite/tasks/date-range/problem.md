# Bug: date_range omits the end date

`date_range(start, end)` should return a list of `datetime.date` for every day from `start` to
`end` **inclusive**. It currently stops one day early — the end date is never included.

Fix `solution.py` so the range is inclusive of both endpoints. Do not change the function signature.
