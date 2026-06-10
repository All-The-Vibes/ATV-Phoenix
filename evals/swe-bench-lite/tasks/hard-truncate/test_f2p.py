from solution import truncate


def test_result_fits_within_limit():
    out = truncate("Hello World", 8)
    assert out == "Hello..."
    assert len(out) == 8


def test_short_limit():
    out = truncate("abcdefghij", 5)
    assert out == "ab..."
    assert len(out) == 5
