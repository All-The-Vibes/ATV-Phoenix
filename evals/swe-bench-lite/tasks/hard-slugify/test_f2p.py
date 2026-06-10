from solution import slugify


def test_lowercase():
    assert slugify("Hello World") == "hello-world"


def test_strips_punctuation_and_collapses_spaces():
    assert slugify("Hello,  World!") == "hello-world"


def test_trims_edges():
    assert slugify("  Trim Me  ") == "trim-me"


def test_collapses_existing_separators():
    assert slugify("Already--Done") == "already-done"
