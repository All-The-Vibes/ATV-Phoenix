from solution import LRUCache


def test_get_refreshes_recency():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1           # 'a' is now most-recently-used
    c.put("c", 3)                    # must evict 'b' (LRU), NOT 'a'
    assert c.get("a") == 1, "recently-used 'a' must survive"
    assert c.get("b") is None, "'b' should have been evicted"


def test_lru_order_after_multiple_gets():
    c = LRUCache(3)
    for k in ("a", "b", "c"):
        c.put(k, k)
    c.get("a")
    c.get("b")
    c.put("d", "d")                  # evict 'c' (least recently used)
    assert c.get("c") is None
    assert c.get("a") == "a"
    assert c.get("d") == "d"
