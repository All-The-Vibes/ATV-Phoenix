def truncate(s, limit):
    if len(s) > limit:
        return s[:limit] + "..."
    return s
