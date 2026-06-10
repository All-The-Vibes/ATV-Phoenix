def retry(fn, attempts: int):
    """Call fn up to `attempts` times; return first success, raise if all fail."""
    # BUG: only tries once — re-raises on the first failure instead of retrying.
    try:
        return fn()
    except Exception:
        raise
