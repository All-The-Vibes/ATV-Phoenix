from solution import dedupe


def test_preserves_first_occurrence_order_ints():
    assert dedupe([3, 1, 2, 1, 3]) == [3, 1, 2]


def test_preserves_order_strings():
    assert dedupe(["b", "a", "b", "c"]) == ["b", "a", "c"]
