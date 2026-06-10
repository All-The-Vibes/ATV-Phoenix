import pytest
from solution import retry


def test_retries_until_success():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return "ok"

    assert retry(flaky, 5) == "ok"
    assert calls["n"] == 3


def test_raises_after_all_attempts_fail():
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        retry(always_fail, 4)
    assert calls["n"] == 4
