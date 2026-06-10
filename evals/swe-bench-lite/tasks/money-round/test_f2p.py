from solution import round_money


def test_half_up_2675():
    assert round_money(2.675) == 2.68


def test_half_up_0125():
    assert round_money(0.125) == 0.13


def test_half_up_1005():
    assert round_money(1.005) == 1.01
