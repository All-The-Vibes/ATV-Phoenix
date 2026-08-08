"""Policies for the ARC-AGI-3 meter (issue #177).

These are deliberately model-free. The point of step 1 is to establish an honest
floor: what a policy with no reasoning achieves, so any later agent is measured
against something rather than against zero.

Three policies:

* ``null``    - always the first available action. The do-nothing control.
* ``random``  - uniform over the action space, seeded.
* ``novelty`` - count-based exploration. Prefers the least-tried action from the
  current frame, which is the cheapest thing that is not random.

Click games matter here. Environments tagged ``click`` or ``keyboard_click``
expose ACTION6, which is a coordinate click and raises ``KeyError: 'x'`` when
stepped without ``data``. The scan that found this was stepping ACTION6 bare and
losing four environments to it. Coordinates are chosen on a coarse grid because
64x64 gives 4096 targets, and counting novelty over 4096 cells learns nothing
inside a realistic budget.
"""
from __future__ import annotations

import hashlib
import random

import numpy as np

CLICK_ACTION = 6
GRID_STEP = 8  # 64 // 8 -> 64 candidate click targets rather than 4096


def frame_key(frame_data) -> bytes:
    """Stable digest of a frame, used as the exploration state key."""
    frame = getattr(frame_data, "frame", None)
    if frame is None:
        return b""
    return hashlib.blake2b(
        np.array(frame, dtype=np.int8).tobytes(), digest_size=8
    ).digest()


def click_targets(step: int = GRID_STEP) -> list[tuple[int, int]]:
    return [(x, y) for x in range(0, 64, step) for y in range(0, 64, step)]


class Policy:
    """Chooses (action, data) pairs. `data` is None for everything but a click.

    ``config`` holds the knobs a proposer is allowed to move:

    * ``grid_step``  - click-target coarseness. 8 gives 64 targets, 4 gives 256.
    * ``strategy``   - ``count`` prefers the least-tried action from this frame.
      ``change`` prefers actions with the highest historical rate of actually
      altering the frame, which is a different bet: that a no-op action is worth
      less than an untried one.
    """

    def __init__(self, name: str, action_space, seed: int = 0, config: dict | None = None):
        self.name = name
        self.actions = list(action_space)
        self.rng = random.Random(seed)
        self.seen: dict[bytes, dict] = {}
        self.clicks: dict[bytes, dict] = {}
        cfg = config or {}
        self.strategy = cfg.get("strategy", "count")
        self.targets = click_targets(cfg.get("grid_step", GRID_STEP))
        self.changed: dict = {a: [0, 0] for a in self.actions}  # action -> [changes, tries]
        self._last_key: bytes | None = None
        self._last_action = None

    def _click_data(self, key: bytes) -> dict[str, int]:
        tried = self.clicks.setdefault(key, {t: 0 for t in self.targets})
        low = min(tried.values())
        target = self.rng.choice([t for t in tried if tried[t] == low])
        tried[target] += 1
        return {"x": target[0], "y": target[1]}

    def observe(self, frame_data) -> None:
        """Record whether the previous action changed the frame."""
        if self._last_action is None:
            return
        key = frame_key(frame_data)
        stats = self.changed[self._last_action]
        stats[1] += 1
        if key != self._last_key:
            stats[0] += 1

    def act(self, frame_data):
        key = frame_key(frame_data)
        if self.name == "null":
            action = self.actions[0]
        elif self.name == "random":
            action = self.rng.choice(self.actions)
        elif self.strategy == "change":
            # Optimistic on untried actions, then by observed change rate.
            def rate(a):
                changes, tries = self.changed[a]
                return 1.0 if tries == 0 else changes / tries
            high = max(rate(a) for a in self.actions)
            action = self.rng.choice([a for a in self.actions if rate(a) == high])
        else:
            tried = self.seen.setdefault(key, {a: 0 for a in self.actions})
            low = min(tried.values())
            action = self.rng.choice([a for a in tried if tried[a] == low])
            tried[action] += 1

        data = None
        if int(getattr(action, "value", action)) == CLICK_ACTION:
            data = self._click_data(key)

        self._last_key = key
        self._last_action = action
        return action, data
