"""Shared helpers for the phoenix-okf scripts: OKF frontmatter read/write.

OKF v0.1 (GoogleCloudPlatform/knowledge-catalog/okf/SPEC.md): a concept document is a
UTF-8 markdown file whose body is preceded by a YAML frontmatter block delimited by `---`
lines. The only required key is `type`. Reserved filenames (`index.md`, `log.md`) are not
concept documents.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

try:  # PyYAML is preferred; fall back to a tiny tolerant parser if unavailable.
    import yaml  # type: ignore

    _HAVE_YAML = True
except Exception:  # pragma: no cover - exercised only without PyYAML
    _HAVE_YAML = False

RESERVED = {"index.md", "log.md"}


def slugify(text: str) -> str:
    out = []
    for ch in text.strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "_", "-", "/", "."):
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "item"


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return '""'
    s = str(value)
    # Quote when YAML could misread the scalar.
    if s == "" or s[0] in "!&*?{}[],#|>@`\"'%" or s.strip() != s or ": " in s or s.endswith(":"):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def dump_frontmatter(meta: dict[str, Any]) -> str:
    """Serialize frontmatter deterministically. Lists render as YAML flow sequences."""
    lines = ["---"]
    for key, value in meta.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            if not value:
                continue
            inner = ", ".join(_yaml_scalar(v) for v in value)
            lines.append(f"{key}: [{inner}]")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def write_concept(path: Path, meta: dict[str, Any], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dump_frontmatter(meta) + "\n\n" + body.rstrip() + "\n"
    path.write_text(text, encoding="utf-8")


def _parse_frontmatter_fallback(block: str) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#") or ":" not in line:
            continue
        if line[0] in (" ", "\t"):  # ignore nested mapping lines
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            items = [x.strip().strip("\"'") for x in val[1:-1].split(",") if x.strip()]
            meta[key] = items
        else:
            meta[key] = val.strip("\"'")
    return meta


def read_concept(path: Path) -> tuple[dict[str, Any] | None, str]:
    """Return (frontmatter_dict_or_None, body). None frontmatter means no parseable block."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, text
    # Split on the closing delimiter line.
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, text
    block = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1:])
    try:
        if _HAVE_YAML:
            meta = yaml.safe_load(io.StringIO(block)) or {}
            if not isinstance(meta, dict):
                return None, body
        else:
            meta = _parse_frontmatter_fallback(block)
    except Exception:
        return None, body
    return meta, body


def iter_concepts(root: Path):
    """Yield (path, is_reserved) for every .md file under root."""
    for p in sorted(root.rglob("*.md")):
        yield p, (p.name in RESERVED)
