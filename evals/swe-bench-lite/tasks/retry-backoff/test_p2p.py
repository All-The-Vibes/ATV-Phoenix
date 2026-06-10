from solution import retry


def test_success_first_try():
    assert retry(lambda: 42, 3) == 42


def test_single_attempt_success():
    assert retry(lambda: "hi", 1) == "hi"
