"""Acceptance check for C2 — Nest to Obsidian: phoenix_nest.emit (issue #3).

Verifies that emit(graph_path, vault_dir, name):
  - creates a valid OKF v0.1 bundle under vault_dir/name/
  - anchors the bundle to the trace hash in graph.json built_at_commit
  - is idempotent (calling twice produces the same conformant output)
  - the bundle is retrievable by TMX signature (the built_at_commit value)

Tests are deterministic, offline, zero-LLM.
Done-check: pytest tests/test_nest_emit.py exits 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "phoenix-okf" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import okf_freshness   # noqa: E402
import okf_ingest      # noqa: E402
import okf_validate    # noqa: E402

FIXTURE_GRAPH = {
    "built_at_commit": "abc123trace0001",
    "nodes": [
        {
            "id": "a:fn1", "label": "fn1", "norm_label": "fn1()",
            "source_file": "src/mod.py", "source_location": "L1",
            "file_type": "code", "community": 0,
        },
        {
            "id": "b:helper", "label": "helper", "norm_label": "helper()",
            "source_file": "src/util.py", "source_location": "L5",
            "file_type": "code", "community": 1,
        },
    ],
    "links": [
        {
            "source": "a:fn1", "target": "b:helper", "relation": "calls",
            "confidence": "INFERRED", "source_location": "L3",
        },
    ],
}


@pytest.fixture()
def graph_file(tmp_path: Path) -> Path:
    gf = tmp_path / "graph.json"
    gf.write_text(json.dumps(FIXTURE_GRAPH), encoding="utf-8")
    return gf


def test_emit_creates_valid_bundle(graph_file: Path, tmp_path: Path) -> None:
    """Emitted bundle passes okf_validate with zero errors."""
    from phoenix_nest import emit  # RED until implemented

    vault = tmp_path / "vault"
    bundle, stats = emit(graph_file, vault, "test-repo")
    errors, _warnings, s = okf_validate.validate(bundle)
    assert errors == [], f"emitted bundle must be conformant: {errors}"
    assert stats["concepts"] >= 1, "at least one concept expected"


def test_bundle_anchored_to_trace_hash(graph_file: Path, tmp_path: Path) -> None:
    """Bundle root index carries the trace hash from graph.json built_at_commit."""
    from phoenix_nest import emit

    vault = tmp_path / "vault"
    bundle, _ = emit(graph_file, vault, "test-repo")
    commit = okf_freshness.bundle_commit(bundle)
    assert commit == "abc123trace0001", (
        f"bundle must carry trace hash 'abc123trace0001', got {commit!r}"
    )


def test_emit_is_idempotent(graph_file: Path, tmp_path: Path) -> None:
    """Calling emit twice with the same inputs produces the same valid output."""
    from phoenix_nest import emit

    vault = tmp_path / "vault"
    bundle1, stats1 = emit(graph_file, vault, "test-repo")
    bundle2, stats2 = emit(graph_file, vault, "test-repo")
    assert bundle1 == bundle2, "emit must return the same bundle path"
    assert stats1 == stats2, "emit must return identical stats on re-run"
    errors, _, _ = okf_validate.validate(bundle2)
    assert errors == [], "re-emitted bundle must still be conformant"


def test_bundle_retrievable_by_tmx_signature(graph_file: Path, tmp_path: Path) -> None:
    """Bundle is discoverable by its TMX signature (built_at_commit) via okf_freshness."""
    from phoenix_nest import emit

    vault = tmp_path / "vault"
    bundle, _ = emit(graph_file, vault, "test-repo")
    sig = okf_freshness.bundle_commit(bundle)
    assert sig == "abc123trace0001"
    concepts = okf_ingest.load_concepts(bundle)
    assert len(concepts) >= 1, "at least one concept must be loadable"


def test_vault_subdirectory_is_named_after_repo(graph_file: Path, tmp_path: Path) -> None:
    """Bundle lands at vault_dir/<name>/, not at vault_dir/ directly."""
    from phoenix_nest import emit

    vault = tmp_path / "vault"
    bundle, _ = emit(graph_file, vault, "my-project")
    assert bundle == vault / "my-project", (
        f"bundle path must be vault/my-project, got {bundle}"
    )
