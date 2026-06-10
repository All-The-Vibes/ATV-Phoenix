# Bug: LRUCache evicts the wrong item (it's FIFO, not LRU)

`LRUCache(capacity)` should evict the **least recently used** item when full. A `get` must count as a
use (refresh recency). Currently `get` does not update recency, so the cache behaves like FIFO and
evicts items that were just accessed.

Fix `solution.py` so that accessing an item with `get` marks it as most-recently-used, and eviction
removes the genuinely least-recently-used item. Keep the `LRUCache`, `get`, `put` interface.
