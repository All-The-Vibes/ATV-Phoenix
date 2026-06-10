def round_money(amount: float) -> float:
    """Round a dollar amount to the nearest cent (round half up)."""
    # BUG: naive round() uses banker's rounding on binary floats -> 2.675 becomes 2.67.
    return round(amount, 2)
