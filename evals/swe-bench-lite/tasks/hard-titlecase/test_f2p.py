from solution import titlecase


def test_two_words():
    assert titlecase("hello world") == "Hello World"


def test_apostrophe_word_not_broken():
    assert titlecase("don't stop me now") == "Don't Stop Me Now"


def test_many_words():
    assert titlecase("the quick brown fox") == "The Quick Brown Fox"
