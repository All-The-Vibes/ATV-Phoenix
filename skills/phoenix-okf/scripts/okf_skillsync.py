#!/usr/bin/env python3
"""okf_skillsync.py — make a `skills/` directory a conformant OKF v0.1 bundle.

Phoenix skills are already markdown + YAML frontmatter (the agentskills.io `SKILL.md` shape),
so they are one required key away from OKF concept documents. This script:

  1. Surgically inserts `type: Phoenix Skill` into every `*/SKILL.md` frontmatter that lacks a
     `type` (idempotent; no other line is touched, keeping git diffs minimal). OKF permits extra
     frontmatter keys and agentskills.io ignores unknown keys, so this is non-breaking.
  2. Generates a bundle-root `skills/index.md` enumerating the skills for progressive disclosure.

After running, `okf_validate.py skills/` should report CONFORMANT.

Usage:
    python okf_skillsync.py [SKILLS_DIR]   (default: ./skills)
"""
from __future__ import annotations

import sys
from pathlib import Path

from okf_common import read_concept

DEFAULT_TYPE = "Phoenix Skill"


def ensure_type(skill_md: Path, type_value: str = DEFAULT_TYPE) -> bool:
    """Insert `type:` after the opening frontmatter delimiter if absent. Returns True if changed."""
    text = skill_md.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=False)
    if not lines or lines[0].strip() != "---":
        return False
    # Find closing delimiter.
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return False
    fm = lines[1:end]
    if any(l.split(":", 1)[0].strip() == "type" for l in fm if ":" in l):
        return False  # already has a type
    new_lines = [lines[0], f"type: {type_value}"] + lines[1:]
    skill_md.write_text("\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    return True


def build_index(skills_dir: Path) -> str:
    entries = []
    for sub in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        md = sub / "SKILL.md"
        if not md.exists():
            continue
        meta, _ = read_concept(md)
        name = (meta or {}).get("name", sub.name)
        desc = (meta or {}).get("description", "")
        # Keep index entries to a single line.
        desc = " ".join(str(desc).split())
        if len(desc) > 200:
            desc = desc[:197].rstrip() + "..."
        entries.append((sub.name, name, desc))

    out = [
        "---",
        "okf_version: 0.1",
        "title: Phoenix skill pack",
        "---",
        "",
        "# Phoenix skill pack — OKF bundle",
        "",
        "The Phoenix verification-gated skill library as an OKF v0.1 knowledge bundle. Each skill "
        "is a concept document (`<skill>/SKILL.md`); this index supports progressive disclosure — "
        "scan names and descriptions here, open the full instructions only on a match.",
        "",
        "# Skills",
        "",
    ]
    for folder, name, desc in entries:
        out.append(f"* [{name}]({folder}/SKILL.md) - {desc}")
    out.append("")
    return "\n".join(out)


def main() -> None:
    skills_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("skills")
    if not skills_dir.is_dir():
        print(f"ERROR: not a directory: {skills_dir}", file=sys.stderr)
        sys.exit(2)

    changed = []
    for sub in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        md = sub / "SKILL.md"
        if md.exists() and ensure_type(md):
            changed.append(sub.name)

    index_text = build_index(skills_dir)
    (skills_dir / "index.md").write_text(index_text, encoding="utf-8")

    print(f"Added `type` to {len(changed)} SKILL.md file(s): {', '.join(changed) or '(none — all already typed)'}")
    print(f"Wrote {skills_dir / 'index.md'}")


if __name__ == "__main__":
    main()
