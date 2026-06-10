from solution import round_money


def test_already_two_dp():
    assert round_money(3.14) == 3.14


def test_whole_dollar():
    assert round_money(10.0) == 10.0


def test_simple_round_down():
    assert round_money(1.231) == 1.23
