"""A skill library the agent writes to and reads from (issue #177).

Voyager's result, cited in our own Prime Agent analysis: an ever-growing library of
executable skills produced 3.3 times more unique items and hit milestones up to 15.3
times faster, and the skills generalized to a fresh world. Our agent had the opposite
property. It re-derived "action 1 moves left" every single turn and never kept anything.

A skill here is Python source with a name, the game it was learned on, and a record of
how often it has worked. Skills are executed into the agent's namespace at the start of
every turn, so a function proven on level 1 is simply callable on level 2.

The honest part, and the reason this is not just a cache: a skill that stops working gets
its failure recorded, and one that fails more than it succeeds is retired. That is the
same measured-gain discipline `phoenix_learn.gate` applies to prompts, applied to code
the agent wrote about itself.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

LIBRARY = Path(__file__).resolve().parents[2] / "eval" / "arc-results" / "skills.json"


@dataclass
class Skill:
    name: str
    game: str
    source: str
    description: str
    wins: int = 0
    losses: int = 0
    tags: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total else 0.5

    @property
    def retired(self) -> bool:
        """Failed enough times, with enough evidence, to stop being offered."""
        return self.wins + self.losses >= 4 and self.score < 0.34

    # Tags that mark a skill as a fact about the BENCHMARK rather than about one board.
    GENERAL_TAGS = frozenset({"general", "primitive", "transferable", "perception"})

    @property
    def transferable(self) -> bool:
        """May this skill be offered on a game it was not learned on?

        Two gates, because a solver that wins is still a solver. `solve_*` is the naming
        convention the agent already uses for "this finishes THIS game", so a skill has
        to both claim generality and not be named as one game's answer. Deliberately
        conservative: a wrongly-excluded skill costs a re-derivation, while a wrongly-
        included one spends actions on a board it cannot read -- and RHAE squares those.
        """
        if self.name.startswith("solve_"):
            return False
        return bool(set(self.tags) & self.GENERAL_TAGS)


class SkillLibrary:
    def __init__(self, path: Path = LIBRARY):
        self.path = path
        self.skills: dict[str, Skill] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        for entry in raw.get("skills", []):
            skill = Skill(**entry)
            self.skills[skill.name] = skill

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"skills": [asdict(s) for s in self.skills.values()]}, indent=2
            ),
            encoding="utf-8",
        )

    def add(self, name, game, source, description, tags=None) -> Skill:
        skill = Skill(
            name=name, game=game, source=source, description=description,
            tags=list(tags or []),
        )
        self.skills[name] = skill
        self.save()
        return skill

    def record(self, name: str, won: bool) -> None:
        skill = self.skills.get(name)
        if not skill:
            return
        if won:
            skill.wins += 1
        else:
            skill.losses += 1
        self.save()

    def available(self, game: str, tags: list[str] | None = None) -> list[Skill]:
        """Skills worth offering: this game's first, then anything TRANSFERABLE.

        Cross-game transfer is the point. "Read the board into connected components" and
        "find the drag mapping" are facts about this benchmark, not about one environment,
        and a library that only ever offers same-game skills compounds nothing across the
        corpus.

        Transfer needs TWO things, and the second was missing long enough to be dangerous.
        A skill must have won somewhere -- evidence it is correct -- AND be marked general,
        which is evidence it is about the benchmark rather than about one board. Winning
        on game A says a skill is right; it never says it is portable.

        The live library is why this is not theoretical. `sp80_generic` won on sp80, is
        tagged "deadly", and its body is
        `for i in range(5000): press(random.choice([1,2,2,3,4,6]))`. Under a wins-only
        rule that was offered on bp35, where it is not a lesson but a random-input loop
        that spends the action budget RHAE squares against you and walks into every hazard
        on the board. `solve_vc33_level` pressed action 6 against boards it never saw.

        A skill is general if it says so (`general`/`primitive`/`transferable` in tags) and
        is not named as a solver for one game. `solve_*` is the naming convention the agent
        already uses for "this finishes THIS game", so it is honoured rather than fought.
        """
        wanted = set(tags or [])
        out = []
        for skill in self.skills.values():
            if skill.retired:
                continue
            if skill.game == game:
                out.append(skill)
                continue
            if skill.wins <= 0 or not skill.transferable:
                continue
            if not wanted or wanted & set(skill.tags):
                out.append(skill)
        return sorted(out, key=lambda s: (s.game != game, -s.score, -s.wins))

    def install(self, namespace: dict, game: str, tags=None) -> list[str]:
        """Execute available skills into the namespace so they can be called."""
        installed = []
        for skill in self.available(game, tags):
            try:
                exec(skill.source, namespace)  # noqa: S102 - the agent's own code
                installed.append(skill.name)
            except Exception:
                self.record(skill.name, won=False)
        return installed

    def describe(self, game: str, tags=None) -> str:
        skills = self.available(game, tags)
        if not skills:
            return "(no skills learned yet)"
        lines = []
        for skill in skills:
            origin = "this game" if skill.game == game else f"learned on {skill.game}"
            lines.append(
                f"  {skill.name}() - {skill.description} "
                f"[{origin}, {skill.wins}W/{skill.losses}L]"
            )
        return "\n".join(lines)

    # ── learned mechanics ────────────────────────────────────────────────────────────
    #
    # Probe results are worth exactly as much on run 2 as on run 1 and cost real score to
    # re-acquire, because RHAE charges every action that alters the game. Storing the
    # summary makes the second run free.

    def mechanics_for(self, game: str) -> str:
        path = self.path.parent / "mechanics.json"
        if not path.exists():
            return ""
        try:
            return json.loads(path.read_text(encoding="utf-8")).get(game, "")
        except json.JSONDecodeError:
            return ""

    def remember_mechanics(self, game: str, summary: str) -> None:
        path = self.path.parent / "mechanics.json"
        known = {}
        if path.exists():
            try:
                known = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                known = {}
        known[game] = summary
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(known, indent=2), encoding="utf-8")
