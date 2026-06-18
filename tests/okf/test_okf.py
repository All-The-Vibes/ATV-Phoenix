"""Deterministic test suite for the phoenix-okf lifecycle: export -> validate -> freshness ->
ingest, plus the external-bundle interop proof. No model is called; every assertion is objective.

Run from the repo root:
    python -m pytest tests/okf -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "phoenix-okf" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import okf_export  # noqa: E402
import okf_freshness  # noqa: E402
import okf_ingest  # noqa: E402
import okf_validate  # noqa: E402

CODE_BUNDLE = ROOT / "examples" / "okf-code-graph"
EXTERNAL_BUNDLE = ROOT / "examples" / "okf-external-demo"


def _toy_graph(commit: str = "deadbeefcafe0001") -> dict:
    """A minimal but schema-faithful graphify/TokenMasterX graph with one cross-file edge."""
    return {
        "built_at_commit": commit,
        "nodes": [
            {"id": "a:foo", "label": "foo", "norm_label": "foo()", "source_file": "src/a.py",
             "source_location": "L1", "file_type": "code", "community": 0},
            {"id": "a:helper", "label": "helper", "norm_label": "helper()", "source_file": "src/a.py",
             "source_location": "L9", "file_type": "code", "community": 0},
            {"id": "b:bar", "label": "bar", "norm_label": "bar()", "source_file": "src/b.py",
             "source_location": "L1", "file_type": "code", "community": 1},
        ],
        "links": [
            {"source": "a:foo", "target": "a:helper", "relation": "calls",
             "confidence": "EXTRACTED", "source_location": "L3"},
            {"source": "a:foo", "target": "b:bar", "relation": "calls",
             "confidence": "INFERRED", "source_location": "L4"},
        ],
    }


@pytest.fixture()
def exported(tmp_path: Path) -> Path:
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps(_toy_graph()), encoding="utf-8")
    out = tmp_path / "bundle"
    okf_export.build(graph, out, "toy")
    return out


# --- export ---------------------------------------------------------------------------------

def test_export_produces_conformant_bundle(exported: Path):
    errors, _warnings, stats = okf_validate.validate(exported)
    assert errors == [], f"freshly exported bundle must be conformant: {errors}"
    assert stats["concepts"] == 2, "two source files -> two concept docs"
    assert (exported / "index.md").exists() and (exported / "log.md").exists()


def test_export_anchors_commit_in_root_index(exported: Path):
    assert okf_freshness.bundle_commit(exported) == "deadbeefcafe0001"


def test_inferred_edge_flagged_candidate(exported: Path):
    body = (exported / "concepts" / "src" / "a.py.md").read_text(encoding="utf-8")
    assert "candidate" in body, "INFERRED cross-file edge must be flagged candidate"
    assert "/concepts/src/b.py.md" in body, "cross-file edge must be a bundle-relative link"


# --- validate -------------------------------------------------------------------------------

def test_validator_catches_missing_type(exported: Path):
    victim = exported / "concepts" / "src" / "b.py.md"
    text = victim.read_text(encoding="utf-8")
    victim.write_text(text.replace("type: Python Source\n", ""), encoding="utf-8")
    errors, _warnings, _stats = okf_validate.validate(exported)
    assert any("type" in e for e in errors), "stripping required `type` must produce an error"


def test_validator_catches_index_with_frontmatter(exported: Path):
    bad_index = exported / "concepts" / "src" / "index.md"
    bad_index.write_text("---\ntype: Nope\n---\n# nope\n", encoding="utf-8")
    errors, _warnings, _stats = okf_validate.validate(exported)
    assert any("index.md must not carry frontmatter" in e for e in errors)


def test_committed_code_bundle_is_conformant():
    errors, _warnings, stats = okf_validate.validate(CODE_BUNDLE)
    assert errors == [], f"committed code bundle drifted: {errors}"
    assert stats["concepts"] >= 50


# --- freshness ------------------------------------------------------------------------------

def test_freshness_fresh_when_commits_match(exported: Path, tmp_path: Path):
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps(_toy_graph("deadbeefcafe0001")), encoding="utf-8")
    assert okf_freshness.bundle_commit(exported) == okf_freshness.graph_commit(graph)


def test_freshness_stale_when_commit_differs(exported: Path, tmp_path: Path):
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps(_toy_graph("0000ffff1111aaaa")), encoding="utf-8")
    assert okf_freshness.bundle_commit(exported) != okf_freshness.graph_commit(graph)


# --- ingest ---------------------------------------------------------------------------------

def test_ingest_outline_counts(exported: Path):
    concepts = okf_ingest.load_concepts(exported)
    o = okf_ingest.outline(exported, concepts)
    assert o["concepts"] == 2
    assert str(o["okf_version"]) == "0.1"
    assert o["types"].get("Python Source") == 2


def test_ingest_full_round_trip(exported: Path):
    concepts = okf_ingest.load_concepts(exported)
    paths = {c["path"] for c in concepts}
    assert "concepts/src/a.py.md" in paths and "concepts/src/b.py.md" in paths


# --- interop: a foreign, hand-authored bundle ----------------------------------------------

def test_external_bundle_is_conformant_with_strict_links():
    errors, _warnings, stats = okf_validate.validate(EXTERNAL_BUNDLE, strict_links=True)
    assert errors == [], f"external bundle must be conformant even with --strict-links: {errors}"
    # Vocabulary is intentionally non-Phoenix -> proves the gate is vendor-neutral.
    assert set(stats["types"]) == {"Runbook", "Dataset", "Decision", "Glossary"}


def test_external_bundle_ingests_index_first():
    concepts = okf_ingest.load_concepts(EXTERNAL_BUNDLE)
    o = okf_ingest.outline(EXTERNAL_BUNDLE, concepts)
    assert str(o["okf_version"]) == "0.1"
    assert o["types"].get("Runbook") == 2
    assert any(c["path"].endswith("incident-rollback.md") for c in concepts)
