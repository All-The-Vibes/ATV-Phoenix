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
        """Skills worth offering: this game's first, then transferable ones."""
        wanted = set(tags or [])
        out = []
        for skill in self.skills.values():
            if skill.retired:
                continue
            if skill.game == game or (wanted and wanted & set(skill.tags)):
                out.append(skill)
        return sorted(out, key=lambda s: (s.game != game, -s.score))

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
