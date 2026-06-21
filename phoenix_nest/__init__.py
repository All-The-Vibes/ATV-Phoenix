"""phoenix_nest — C2 Nest to Obsidian: emit OKF bundle to a vault folder (issue #3).

emit(graph_path, vault_dir, name) writes a conformant OKF v0.1 bundle to
vault_dir/name/ using the existing phoenix-okf export scripts.  The bundle is
anchored to the built_at_commit value in graph.json, which callers set to the
phoenix trace hash so it is retrievable by TMX signature.  Re-emitting the
same graph produces identical output (idempotent by construction: same graph
JSON -> same deterministic OKF build).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple

# Locate the phoenix-okf scripts alongside this package (they live in
# skills/phoenix-okf/scripts/ relative to the repo root).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO_ROOT / "skills" / "phoenix-okf" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import okf_export  # noqa: E402  (path injection above)


def emit(
    graph_path: Path | str,
    vault_dir: Path | str,
    name: str,
) -> Tuple[Path, dict]:
    """Emit an OKF v0.1 bundle for *graph_path* into *vault_dir*/*name*/.

    Parameters
    ----------
    graph_path : path to a graphify/TokenMasterX graph.json.  The
        ``built_at_commit`` field in this file is used as the TMX signature
        that anchors the bundle (set it to the phoenix trace hash before
        calling).
    vault_dir  : destination root (the Obsidian vault folder, or any dir).
        The bundle lands at ``vault_dir/name/`` so multiple repos can coexist.
    name       : repository / bundle name, used as the subdirectory and the
        OKF bundle title.

    Returns
    -------
    (bundle_path, stats) where ``bundle_path = vault_dir/name/`` and
    ``stats`` is the dict returned by ``okf_export.build``.
    """
    graph_path = Path(graph_path)
    vault_dir = Path(vault_dir)
    bundle_dir = vault_dir / name
    stats = okf_export.build(graph_path, bundle_dir, name)
    return bundle_dir, stats
