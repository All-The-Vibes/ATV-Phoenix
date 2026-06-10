def parse_csv_line(line: str):
    """Split a CSV line into fields. Quoted fields may contain commas."""
    # BUG: naive split breaks quoted fields and keeps the quotes.
    return line.split(",")
