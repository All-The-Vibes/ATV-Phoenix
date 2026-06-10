# truncate returns text longer than the limit I asked for

`truncate(s, limit)` should shorten long text and append an ellipsis `"..."`.
The bug: when I truncate to a limit, the output comes back *longer* than the limit
because the `"..."` gets added on top of an already full-length string. The whole
point of a limit is that the result fits within it.

Please fix `solution.py`. Keep the `truncate` signature.
