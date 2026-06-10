from solution import titlecase


def test_empty():
    assert titlecase("") == ""


def test_single_word():
    assert titlecase("hello") == "Hello"


def test_single_letter():
    assert titlecase("a") == "A"
