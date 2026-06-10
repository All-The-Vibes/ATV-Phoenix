from solution import LRUCache


def test_basic_put_get():
    c = LRUCache(2)
    c.put("a", 1)
    assert c.get("a") == 1


def test_missing_key_returns_none():
    c = LRUCache(2)
    assert c.get("nope") is None


def test_capacity_enforced():
    c = LRUCache(1)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("b") == 2
