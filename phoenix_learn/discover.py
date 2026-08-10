"""Environment characterisation: find out what each action does before betting on a theory.

Issue #183. `evals/arc/` accumulated 34 Python files and most of them ask one question in a
domain-specific way: what does this action do, and what changed? Because the answer lived in an
eval directory, the next domain rebuilt it from scratch.

The failure this prevents was measured in the ARC traces. One run pressed a single action 56
times on an untested theory that it advanced a timer, then died; one press would have disproved
it. Another spent 2,075 actions in a single turn permuting 22 orderings of a theory it never
cheaply tested. A procedure that presses each available action once and diffs the state costs one
action per action and reports the mechanics directly.

The dependencies are two callables, `snapshot` and `apply`, so the same primitive covers a 64x64
ARC grid, a shell agent whose state is the filesystem and the process table, and anything else
with enumerable actions and observable state.

What this module refuses to guess is as important as what it reports. Without a `reset` callable
each action starts from wherever the previous one left the world, so the effects are
order-dependent and two actions that look alike may not be. In that case `aliases` is empty and
`aliases_known` is False rather than a list that reads as evidence.

Public surface:
    diff_regions(before, after) -> tuple of region descriptors
    characterise(actions, snapshot, apply, reset=None) -> Characterisation
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence


def _is_seq(obj: Any) -> bool:
    return isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray))


def _is_grid(obj: Any) -> bool:
    if not _is_seq(obj) or not len(obj):
        return False
    return all(_is_seq(row) for row in obj)


def _canon(obj: Any) -> Any:
    """Deterministic, hashable rendering of a state so two snapshots compare by value."""
    if isinstance(obj, Mapping):
        return tuple(sorted((str(k), _canon(v)) for k, v in obj.items()))
    if isinstance(obj, (set, frozenset)):
        return tuple(sorted(repr(_canon(v)) for v in obj))
    if _is_seq(obj):
        return tuple(_canon(v) for v in obj)
    return obj


def digest(state: Any) -> str:
    """Short stable digest of a state. Equal digests mean equal canonical values."""
    return hashlib.sha256(repr(_canon(state)).encode("utf-8")).hexdigest()[:16]


def diff_regions(before: Any, after: Any) -> tuple:
    """Say WHERE the state changed, not merely that it did.

    Grid states report the bounding box of the differing cells plus how many differ, because a
    64x64 grid that flips one cell must not read the same as one that repainted everything.
    Mappings report the keys that differ. Flat sequences report the indices. Anything else
    reports a single value region when the two are unequal.
    """
    if _canon(before) == _canon(after):
        return ()

    if isinstance(before, Mapping) and isinstance(after, Mapping):
        keys = set(before) | set(after)
        changed = sorted(
            str(k) for k in keys
            if _canon(before.get(k)) != _canon(after.get(k))
        )
        return tuple(("key", k) for k in changed)

    if _is_grid(before) and _is_grid(after) and len(before) == len(after):
        cells = []
        for r, (row_b, row_a) in enumerate(zip(before, after)):
            width = max(len(row_b), len(row_a))
            for c in range(width):
                vb = row_b[c] if c < len(row_b) else None
                va = row_a[c] if c < len(row_a) else None
                if _canon(vb) != _canon(va):
                    cells.append((r, c))
        if not cells:
            return ()
        rows = [r for r, _ in cells]
        cols = [c for _, c in cells]
        return (("cells", min(rows), min(cols), max(rows), max(cols), len(cells)),)

    if _is_seq(before) and _is_seq(after):
        width = max(len(before), len(after))
        changed = []
        for i in range(width):
            vb = before[i] if i < len(before) else None
            va = after[i] if i < len(after) else None
            if _canon(vb) != _canon(va):
                changed.append(i)
        return tuple(("index", i) for i in changed)

    return (("value",),)


@dataclass(frozen=True)
class Effect:
    """What one action did, measured once."""

    action: Any
    changed: bool
    regions: tuple
    before: str
    after: str


@dataclass(frozen=True)
class Characterisation:
    """The result of pressing every action once.

    `actions_spent` is the honest cost of the procedure. `inert` names the actions that changed
    nothing, which is the cheap disproof the traces show the agent never bought. `aliases` groups
    actions that landed on the same state, and it is trustworthy only when `aliases_known` is
    True, which requires a `reset`.
    """

    effects: tuple
    actions_spent: int
    independent: bool
    aliases_known: bool
    aliases: tuple

    @property
    def inert(self) -> tuple:
        return tuple(e.action for e in self.effects if not e.changed)

    @property
    def active(self) -> tuple:
        return tuple(e.action for e in self.effects if e.changed)

    def regions_for(self, action: Any) -> tuple:
        for e in self.effects:
            if e.action == action:
                return e.regions
        raise KeyError(action)


def characterise(
    actions: Iterable[Any],
    snapshot: Callable[[], Any],
    apply: Callable[[Any], Any],
    reset: Callable[[], Any] | None = None,
) -> Characterisation:
    """Press each action once, diff the state, and report what each one does.

    With `reset` every action is measured from the same starting state, so the effects are
    independent and two actions landing on the same digest are true aliases. Without it the
    actions run in sequence from whatever the previous one produced, `independent` is False, and
    no alias claim is made.
    """
    actions = list(actions)
    effects = []
    spent = 0

    for action in actions:
        if reset is not None:
            reset()
        before = snapshot()
        apply(action)
        spent += 1
        after = snapshot()
        effects.append(
            Effect(
                action=action,
                changed=_canon(before) != _canon(after),
                regions=diff_regions(before, after),
                before=digest(before),
                after=digest(after),
            )
        )

    independent = reset is not None
    groups: tuple = ()
    if independent:
        by_after: dict[str, list] = {}
        for e in effects:
            by_after.setdefault(e.after, []).append(e.action)
        groups = tuple(
            tuple(members) for members in by_after.values() if len(members) > 1
        )

    return Characterisation(
        effects=tuple(effects),
        actions_spent=spent,
        independent=independent,
        aliases_known=independent,
        aliases=groups,
    )
