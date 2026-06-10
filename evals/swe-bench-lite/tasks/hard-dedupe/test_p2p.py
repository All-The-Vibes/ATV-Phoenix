from solution import dedupe


def test_empty():
    assert dedupe([]) == []


def test_single():
    assert dedupe([1]) == [1]


def test_single_string():
    assert dedupe(["x"]) == ["x"]
