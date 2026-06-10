# Bug: retry() gives up after the first failure

`retry(fn, attempts)` should call `fn` up to `attempts` times, returning the first successful result,
and only raising if **all** attempts fail. It currently re-raises on the first exception, so transient
failures are never retried.

Fix `solution.py` so it retries up to `attempts` times and returns the first success; if every attempt
raises, re-raise the last exception. Keep the `retry` signature.
