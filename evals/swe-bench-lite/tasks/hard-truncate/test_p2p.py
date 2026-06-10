from solution import truncate


def test_shorter_than_limit_unchanged():
    assert truncate("hi", 10) == "hi"


def test_exact_length_unchanged():
    assert truncate("exact!", 6) == "exact!"


def test_empty():
    assert truncate("", 5) == ""
