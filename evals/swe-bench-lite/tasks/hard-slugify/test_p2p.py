from solution import slugify


def test_empty():
    assert slugify("") == ""


def test_single_word():
    assert slugify("python") == "python"


def test_simple_two_words():
    assert slugify("a b") == "a-b"
