"""Acceptance checks for the pinned TokenMasterX upstream integration."""

import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "vendor" / "token-master" / "skills" / "token-master"
UPSTREAM_REVISION = "426fc853389ddba4bc6e1dd35a28179a895c064f"
GRAPH_SHA256 = "08def16001f25ab085f35f04faae416c7a9b104d8fadd6a60d5b8808be419066"


class _FastMCP:
    def __init__(self, name):
        self.name = name

    def tool(self):
        return lambda function: function


def _load_script(name, path, monkeypatch):
    for module_name in ("mcp", "mcp.server", "mcp.server.fastmcp"):
        module = types.ModuleType(module_name)
        if module_name == "mcp.server.fastmcp":
            module.FastMCP = _FastMCP
        monkeypatch.setitem(sys.modules, module_name, module)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def navigation(tmp_path, monkeypatch):
    nodes = [
        {"id": "base", "label": "Trait", "file_type": "code"},
        {"id": "rust", "label": "RustType", "file_type": "code"},
        {"id": "class", "label": "Subclass", "file_type": "code"},
        {"id": "method", "label": "execute", "file_type": "code"},
        {"id": "caller", "label": "UnrelatedCaller", "file_type": "code"},
    ]
    for node in nodes:
        node.update(source_file="fixture.rs", source_location="L1")
    links = [
        {"source": "rust", "target": "base", "relation": "implements"},
        {"source": "class", "target": "base", "relation": "inherits"},
        {"source": "rust", "target": "method", "relation": "method"},
        {"source": "caller", "target": "base", "relation": "calls"},
    ]
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"nodes": nodes, "links": links}), encoding="utf-8")
    monkeypatch.setenv("GRAPH_PATH", str(graph))
    return _load_script("tmx_navigation", SKILL / "graphify_mcp.py", monkeypatch)


def test_graph_navigator_matches_pinned_upstream():
    content = (SKILL / "graphify_mcp.py").read_text(encoding="utf-8")
    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == GRAPH_SHA256


def test_rust_trait_implementors_include_methods(navigation):
    result = navigation.inheritors("Trait")
    assert "RustType" in result
    assert "(implements)" in result
    assert "execute" in result
    assert "fixture.rs:L1" in result


def test_class_inheritance_is_preserved(navigation):
    result = navigation.inheritors("Trait")
    assert "Subclass" in result
    assert "(subclasses)" in result
    assert "UnrelatedCaller" not in result


def test_empty_and_unknown_subtype_queries_are_explicit(navigation):
    assert "No subtypes/implementors" in navigation.inheritors("RustType")
    assert "No type node found" in navigation.inheritors("Unknown")
