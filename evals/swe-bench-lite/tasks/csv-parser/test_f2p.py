from solution import parse_csv_line


def test_comma_inside_quotes():
    assert parse_csv_line('a,"b,c",d') == ["a", "b,c", "d"]


def test_quotes_stripped():
    assert parse_csv_line('"hello","world"') == ["hello", "world"]


def test_mixed_quoted_unquoted():
    assert parse_csv_line('1,"2,3",4,"5"') == ["1", "2,3", "4", "5"]
