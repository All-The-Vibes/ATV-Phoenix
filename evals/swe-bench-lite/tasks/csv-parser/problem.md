# Bug: CSV parser splits on commas inside quoted fields

`parse_csv_line(line)` should split a single CSV line into fields, respecting double-quoted fields
that may themselves contain commas (e.g. `a,"b,c",d` → `["a", "b,c", "d"]`). It currently splits on
every comma, breaking quoted fields apart, and leaves the surrounding quotes in place.

Fix `solution.py` so quoted fields are kept intact and their surrounding quotes are stripped.
Keep the `parse_csv_line` signature.
