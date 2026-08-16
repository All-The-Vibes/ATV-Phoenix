"""ARC skills as a typed view over the gated Phoenix memory store."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import ClassVar

from phoenix_learn.accept import Observation, verify_gate
from phoenix_learn.memory import Fact, Memory

LIBRARY = Path(__file__).resolve().parents[2] / "eval" / "arc-results" / "skills.json"
CORPUS_SCOPE = "arc:corpus"


@dataclass
class Skill:
    name: str
    game: str
    source: str
    description: str
    wins: int = 0
    losses: int = 0
    tags: list[str] = field(default_factory=list)
    when_to_invoke: str = ""
    scope: str = ""
    trials: list[bool] = field(default_factory=list)
    verdict: dict = field(default_factory=dict)

    GENERAL_TAGS: ClassVar[frozenset[str]] = frozenset(
        {"general", "primitive", "transferable", "perception"}
    )

    @property
    def score(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total else 0.5

    @property
    def retired(self) -> bool:
        """Failed enough times, with enough evidence, to stop being offered."""
        return self.wins + self.losses >= 4 and self.score < 0.34

    @property
    def transferable(self) -> bool:
        if self.name.startswith("solve_"):
            return False
        return bool(set(self.tags) & self.GENERAL_TAGS)

    def value(self) -> dict:
        data = asdict(self)
        data.pop("scope", None)
        data.pop("trials", None)
        data.pop("verdict", None)
        return data


class SkillLibrary:
    """ARC-facing API backed by ``phoenix_learn.memory.Memory`` admissions."""

    def __init__(self, path: Path = LIBRARY):
        self.path = path
        self.memory = Memory(scope=CORPUS_SCOPE)
        self.skills: dict[str, Skill] = {}
        self.pending: dict[str, Skill] = {}
        self._observations: dict[str, list[Observation]] = {}
        self.load()

    @staticmethod
    def _scope_for(skill: Skill) -> str:
        return CORPUS_SCOPE if skill.transferable else f"arc:game:{skill.game}"

    @staticmethod
    def _skill_from_entry(entry: dict) -> Skill:
        allowed = {f.name for f in fields(Skill)}
        data = {k: v for k, v in dict(entry).items() if k in allowed}
        data.setdefault("tags", [])
        data.setdefault("when_to_invoke", "")
        return Skill(**data)

    @staticmethod
    def _observations_from_entry(entry: dict, skill: Skill) -> list[Observation]:
        if "trials" in entry:
            out = []
            for trial in entry.get("trials") or []:
                if isinstance(trial, dict):
                    out.append(
                        Observation(
                            bool(trial.get("ok")),
                            trial.get("seed"),
                            trial.get("note", ""),
                        )
                    )
                else:
                    out.append(Observation(bool(trial)))
            return out
        return [Observation(False) for _ in range(skill.losses)] + [
            Observation(True) for _ in range(skill.wins)
        ]

    @staticmethod
    def _entry_from_fact(fact: Fact) -> dict | None:
        if not isinstance(fact.value, dict):
            return None
        value = dict(fact.value)
        value["scope"] = fact.scope
        value["trials"] = [trial.ok for trial in fact.trials]
        value["verdict"] = dict(fact.verdict)
        return value

    def _admit(self, skill: Skill, observations: list[Observation]) -> bool:
        verdict = verify_gate(observations)
        skill.trials = [trial.ok for trial in observations]
        skill.verdict = dict(verdict)
        skill.scope = self._scope_for(skill)
        if not verdict["ok"]:
            self.memory.facts.pop(skill.name, None)
            self.skills.pop(skill.name, None)
            self.pending[skill.name] = skill
            self._observations[skill.name] = observations
            return False

        out = self.memory.remember(skill.name, skill.value(), observations, scope=skill.scope)
        if not out["stored"]:
            self.pending[skill.name] = skill
            self._observations[skill.name] = observations
            return False
        skill.verdict = dict(out["fact"].verdict)
        self.skills[skill.name] = skill
        self.pending.pop(skill.name, None)
        self._observations[skill.name] = list(out["fact"].trials)
        return True

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return

        entries = list(raw.get("skills", []))
        if not entries:
            entries = [
                entry
                for fact in raw.get("facts", [])
                if (entry := self._entry_from_fact(
                    Fact(
                        key=fact.get("key", ""),
                        value=fact.get("value"),
                        scope=fact.get("scope"),
                        trials=[
                            Observation(bool(t.get("ok")), t.get("seed"), t.get("note", ""))
                            for t in fact.get("trials", [])
                        ],
                        verdict=fact.get("verdict", {}),
                    )
                ))
            ]

        for entry in entries:
            try:
                skill = self._skill_from_entry(entry)
            except TypeError:
                continue
            observations = self._observations_from_entry(entry, skill)
            self._admit(skill, observations)

    def _current_disk_skills(self) -> dict[str, Skill]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        out: dict[str, Skill] = {}
        for entry in raw.get("skills", []):
            try:
                skill = self._skill_from_entry(entry)
            except TypeError:
                continue
            observations = self._observations_from_entry(entry, skill)
            if verify_gate(observations)["ok"]:
                skill.trials = [trial.ok for trial in observations]
                skill.verdict = verify_gate(observations)
                skill.scope = self._scope_for(skill)
                out[skill.name] = skill
        return out

    @staticmethod
    def _merged_observations(mine: Skill, theirs: Skill | None) -> list[Observation]:
        if theirs is None:
            return [Observation(bool(ok)) for ok in mine.trials]
        wins = max(mine.wins, theirs.wins)
        losses = max(mine.losses, theirs.losses)
        return [Observation(False) for _ in range(losses)] + [
            Observation(True) for _ in range(wins)
        ]

    def save(self) -> None:
        """Write admitted skills, merging with peers and preserving the legacy shape."""
        merged = self._current_disk_skills()
        for name, mine in self.skills.items():
            theirs = merged.get(name)
            if theirs is not None:
                mine.wins = max(mine.wins, theirs.wins)
                mine.losses = max(mine.losses, theirs.losses)
            observations = self._merged_observations(mine, theirs)
            if verify_gate(observations)["ok"]:
                mine.trials = [trial.ok for trial in observations]
                mine.verdict = verify_gate(observations)
                mine.scope = self._scope_for(mine)
                merged[name] = mine

        memory = Memory(scope=CORPUS_SCOPE)
        admitted: list[Skill] = []
        for skill in merged.values():
            observations = [Observation(bool(ok)) for ok in skill.trials]
            out = memory.remember(skill.name, skill.value(), observations, scope=skill.scope)
            if out["stored"]:
                skill.verdict = dict(out["fact"].verdict)
                admitted.append(skill)

        self.skills = {skill.name: skill for skill in admitted}
        self.memory = memory
        document = {
            "scope": memory.scope,
            "facts": [
                {
                    "key": fact.key,
                    "value": fact.value,
                    "scope": fact.scope,
                    "trials": [
                        {"ok": t.ok, "seed": t.seed, "note": t.note} for t in fact.trials
                    ],
                    "verdict": fact.verdict,
                }
                for fact in memory.facts.values()
            ],
            "skills": [asdict(skill) for skill in admitted],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(document, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(
        self,
        name,
        game,
        source,
        description,
        tags=None,
        when_to_invoke="",
        trials=None,
    ) -> Skill:
        skill = Skill(
            name=name,
            game=game,
            source=source,
            description=description,
            tags=list(tags or []),
            when_to_invoke=str(when_to_invoke or "")[:200],
        )
        observations = [
            t if isinstance(t, Observation) else Observation(bool(t)) for t in (trials or [])
        ]
        if self._admit(skill, observations):
            self.save()
        return skill

    def record(self, name: str, won: bool) -> None:
        skill = self.skills.get(name) or self.pending.get(name)
        if not skill:
            return
        if won:
            skill.wins += 1
        else:
            skill.losses += 1
        observations = self._observations.get(name, [])
        observations.append(Observation(bool(won)))
        was_stored = name in self.skills
        is_stored = self._admit(skill, observations)
        if was_stored or is_stored:
            self.save()

    def evidence(self, name: str) -> dict | None:
        if ev := self.memory.evidence(name):
            return ev
        skill = self.pending.get(name)
        if skill is None:
            return None
        return {
            "key": name,
            "scope": skill.scope,
            "trials": list(skill.trials),
            "verdict": dict(skill.verdict),
        }

    def available(self, game: str, tags: list[str] | None = None) -> list[Skill]:
        """Skills worth offering: this game's first, then earned transferable skills."""
        wanted = set(tags or [])
        out = []
        for skill in self.skills.values():
            if skill.retired:
                continue
            if skill.game == game and skill.scope == f"arc:game:{game}":
                out.append(skill)
                continue
            if skill.game == game and skill.scope == CORPUS_SCOPE:
                out.append(skill)
                continue
            if skill.wins <= 0 or skill.scope != CORPUS_SCOPE or not skill.transferable:
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
            if skill.when_to_invoke:
                lines.append(f"      USE WHEN: {skill.when_to_invoke}")
        return "\n".join(lines)

    # ── learned mechanics ────────────────────────────────────────────────────────────

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
