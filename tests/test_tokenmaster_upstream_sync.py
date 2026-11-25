"""Acceptance checks for the pinned TokenMasterX upstream integration."""

import hashlib
import importlib.util
import json
import shlex
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "vendor" / "token-master" / "skills" / "token-master"
UPSTREAM_REVISION = "426fc853389ddba4bc6e1dd35a28179a895c064f"
GRAPH_SHA256 = "08def16001f25ab085f35f04faae416c7a9b104d8fadd6a60d5b8808be419066"
BRAINSPACE_SHA256 = {
    "brainspace/__init__.py": "6e64907153a64b2904abaf0e4916f0f9b0545640a06f83c54405d476c1325c3a",
    "brainspace/benchmark.py": "f39a50dbfb2ca25f45048e128417bf8e4c02056bb1aaaf6e4722cd5a9b9929a2",
    "brainspace/ccr.py": "6dcac4b43683711eb0a3bf7a6575a8adeb562654628f675b2e9b39d718a451b5",
    "brainspace/compressors/__init__.py": "61134869fdc4928a99a0f15cd6082b66962618264df07143a237be9e4966df09",
    "brainspace/compressors/code_compressor.py": "c8ba617edbfee438d586a0fe23948edf73a77eb8fd2354f65ddbc74418d47879",
    "brainspace/compressors/json_compressor.py": "f34f42736d5b71e173b2a3f0b886898815c7578094d0a7ad5bed0dc68cd0d043",
    "brainspace/compressors/logs_compressor.py": "47a08e43709fe7312b8861aeebdd64d2b2bb103ad324461d77b5571ff40cd64e",
    "brainspace/compressors/prose_compressor.py": "4eee4b6d7b418e0be0e38adf06f5d92829f64bc053bc5bb0c9e29a46318a3d2d",
    "brainspace/router.py": "5e8c76e64b83229abc7748a7cf10370d6cac687e9cfec57c15885bdd35ed1dbe",
    "brainspace/tokens.py": "ad790c6d40dca7c4ee3b9fdd2ff6fcd3b44ea4325019d7b976e7fe6d28d2e331",
    "brainspace_benchmark.py": "e5a231070a77a5cc4010ecb790d32d8288499c47e34c30ff76dfe005951fa1be",
    "brainspace_mcp.py": "c775d8701c4bef1bae42c39837445f76f1ed7f4d346f761e08ae10cc0824b38c",
    "brainspace_posttooluse.py": "960f96f7072a6155c63f0170cf5b82e220dd192f569037dd02ac90f6c61ec1b2",
    # Approved local patch: constrain MCP to v1 and quote shell launch arguments.
    "brainspace_setup.py": "d4171561a848b308ff0588321e4edf9a19cdb367c869185df232bce733d8dd85",
}


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


@pytest.mark.parametrize(
    "relative,digest", BRAINSPACE_SHA256.items(), ids=BRAINSPACE_SHA256
)
def test_brainspace_sources_match_upstream(relative, digest):
    """Match pinned upstream except the documented installer compatibility patch."""
    content = (SKILL / relative).read_text(encoding="utf-8")
    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == digest


@pytest.fixture
def brainspace(monkeypatch):
    monkeypatch.syspath_prepend(str(SKILL))
    from brainspace import ccr, router, tokens

    return ccr, router, tokens


def test_brainspace_json_elision_recovers_every_record(brainspace, tmp_path):
    ccr, router, tokens = brainspace
    store = ccr.CCR(tmp_path / "ccr.sqlite")
    rows = [{"id": index, "value": "sample value " * 8} for index in range(60)]
    original = json.dumps({"items": rows, "count": len(rows)})
    compressed, _ = router.route_typed(original, "fixture.json", stash=store.stash)
    assert tokens.estimate(compressed) < tokens.estimate(original)
    shown = json.loads(compressed)
    hashes = ccr.parse_placeholders(shown["items"][2])
    assert len(hashes) == 1
    recovered = store.retrieve(hashes[0])
    assert recovered is not None
    assert shown["items"][:2] + json.loads(recovered) + shown["items"][-1:] == rows
    assert shown["count"] == len(rows)


def test_brainspace_log_recovery_and_determinism(brainspace, tmp_path):
    ccr, router, tokens = brainspace
    store = ccr.CCR(tmp_path / "ccr.sqlite")
    original = "DEBUG repeated diagnostic line\n" * 80 + "ERROR meaningful failure\n"
    compressed, _ = router.route_typed(original, "build.log", stash=store.stash)
    assert tokens.estimate(compressed) < tokens.estimate(original)
    assert "ERROR meaningful failure" in compressed
    hashes = ccr.parse_placeholders(compressed)
    assert len(hashes) == 1
    assert store.retrieve(hashes[0]) == original
    assert router.route_typed(original, "build.log", stash=store.stash)[0] == compressed
    assert store.stats()["entries"] == 1


def test_brainspace_failed_log_stash_preserves_original(brainspace):
    _, router, _ = brainspace
    original = "DEBUG repeated diagnostic line\n" * 80 + "ERROR meaningful failure\n"
    for stash in (None, lambda *args, **kwargs: None):
        assert router.route_typed(original, "build.log", stash=stash)[0] == original


def test_brainspace_tiny_content_is_unchanged(brainspace):
    _, router, _ = brainspace
    assert router.route_typed("ok", "sample.py")[0] == "ok"


def test_brainspace_mcp_noop_and_retrieval(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(SKILL))
    monkeypatch.setenv("BRAINSPACE_CCR", str(tmp_path / "ccr.sqlite"))
    server = _load_script("tmx_brainspace_mcp", SKILL / "brainspace_mcp.py", monkeypatch)
    assert server.brainspace_compress("ok", "sample.py") == "ok"
    original = "DEBUG repeated diagnostic line\n" * 80 + "ERROR meaningful failure\n"
    compressed = server.brainspace_compress(original, "build.log")
    from brainspace.ccr import PLACEHOLDER_RE

    placeholders = list(PLACEHOLDER_RE.finditer(compressed))
    assert placeholders
    assert server.brainspace_retrieve(placeholders[0].group(0)) == original
    assert "brainspace CCR store:" in server.brainspace_stats()
    assert "entries:        1" in server.brainspace_stats()


@pytest.fixture
def phoenix_setup(tmp_path, monkeypatch):
    home = tmp_path / "copilot"
    monkeypatch.setenv("COPILOT_HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "fallback"))
    setup = _load_script(
        "phoenix_setup",
        ROOT / ".copilot-plugin" / "skills" / "phoenix-setup" / "setup.py",
        monkeypatch,
    )
    return setup, home


def test_phoenix_home_honors_isolated_override(phoenix_setup):
    setup, home = phoenix_setup
    assert setup.copilot_home() == home


def test_phoenix_attempts_both_companions_when_graph_is_unavailable(
    phoenix_setup, monkeypatch, capsys
):
    setup, _ = phoenix_setup
    calls = []
    monkeypatch.setattr(setup, "install_tokenmaster", lambda repo: calls.append("graph") or False)
    monkeypatch.setattr(setup, "install_brainspace", lambda repo: calls.append("brainspace") or True)
    assert setup.check_companions(ROOT) is False
    assert calls == ["graph", "brainspace"]
    output = capsys.readouterr().out
    assert "graph=unavailable" in output
    assert "brainspace=installed" in output


def test_phoenix_brainspace_install_preserves_config_and_is_idempotent(
    phoenix_setup, monkeypatch
):
    setup, home = phoenix_setup
    assert hasattr(setup, "install_brainspace")
    home.mkdir()
    config_path = home / "mcp-config.json"
    existing = {
        "mcpServers": {
            "phoenix": {"type": "stdio", "command": "phoenix-mcp"},
            "external": {"type": "stdio", "command": "external-tool"},
        },
        "otherSetting": True,
    }
    config_path.write_text(json.dumps(existing), encoding="utf-8")
    monkeypatch.setattr(setup.shutil, "which", lambda name: sys.executable if name == "uv" else None)
    calls = []

    def run_installer(argv, **kwargs):
        calls.append(argv)
        assert Path(argv[1]) == SKILL / "brainspace_setup.py"
        assert argv[-1] == "--host=copilot"
        assert kwargs["env"]["COPILOT_HOME"] == str(home)
        assert kwargs["timeout"] > 0
        installer = _load_script("brainspace_setup", SKILL / "brainspace_setup.py", monkeypatch)
        monkeypatch.setattr(sys, "argv", argv[1:])
        result = installer.main()
        return subprocess.CompletedProcess(argv, result, stdout="MCP-ONLY (opt-in)", stderr="")

    monkeypatch.setattr(setup.subprocess, "run", run_installer)
    assert setup.install_brainspace(ROOT) is True
    first_config = config_path.read_bytes()
    assert setup.install_brainspace(ROOT) is True
    assert config_path.read_bytes() == first_config
    assert len(calls) == 2
    setup.register_mcp(Path("phoenix-mcp"))
    installed = json.loads(first_config)
    assert json.loads(config_path.read_text(encoding="utf-8")) == installed
    assert installed["otherSetting"] is True
    for name, entry in existing["mcpServers"].items():
        assert installed["mcpServers"][name] == entry
    server = installed["mcpServers"]["brainspace"]
    assert server["type"] == "stdio"
    for dependency in ("mcp>=1,<2", "tree-sitter", "tree-sitter-python", "tree-sitter-rust", "tiktoken"):
        assert ["--with", dependency] in [
            server["args"][index:index + 2] for index in range(len(server["args"]) - 1)
        ]
    assert Path(server["args"][-1]).is_file()
    assert (home / "token-master" / "brainspace" / "ccr.py").is_file()
    assert not (home / "settings.json").exists()


@pytest.mark.parametrize("original", ["{", "[]", '{"mcpServers": []}'])
def test_phoenix_brainspace_rejects_invalid_config_without_overwriting(
    phoenix_setup, monkeypatch, capsys, original
):
    setup, home = phoenix_setup
    assert hasattr(setup, "install_brainspace")
    home.mkdir()
    config_path = home / "mcp-config.json"
    config_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(setup.shutil, "which", lambda name: sys.executable)
    calls = []
    monkeypatch.setattr(setup.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    assert setup.install_brainspace(ROOT) is False
    assert config_path.read_text(encoding="utf-8") == original
    assert calls == []
    assert "ERROR" in capsys.readouterr().out
    with pytest.raises(ValueError):
        setup.register_mcp(Path("phoenix-mcp"))
    assert config_path.read_text(encoding="utf-8") == original


def test_phoenix_brainspace_subprocess_failure_is_reported(
    phoenix_setup, monkeypatch, capsys
):
    setup, _ = phoenix_setup
    monkeypatch.setattr(setup.shutil, "which", lambda name: sys.executable)
    monkeypatch.setattr(
        setup.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 7, stdout="", stderr="installer-error"),
    )
    assert setup.install_brainspace(ROOT) is False
    output = capsys.readouterr().out
    assert "ERROR" in output
    assert "installer-error" in output


def test_phoenix_brainspace_missing_uv_is_reported(
    phoenix_setup, monkeypatch, capsys
):
    setup, _ = phoenix_setup
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)
    assert setup.install_brainspace(ROOT) is False
    output = capsys.readouterr().out
    assert "uv" in output
    assert "brainspace_setup.py" in output


def test_phoenix_brainspace_timeout_is_reported(phoenix_setup, monkeypatch, capsys):
    setup, _ = phoenix_setup
    monkeypatch.setattr(setup.shutil, "which", lambda name: sys.executable)

    def timed_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(setup.subprocess, "run", timed_out)
    assert setup.install_brainspace(ROOT) is False
    assert "ERROR" in capsys.readouterr().out


def test_brainspace_both_launch_forms_use_quoted_mcp_v1(monkeypatch):
    installer = _load_script("brainspace_launch", SKILL / "brainspace_setup.py", monkeypatch)
    script = "C:/Program Files/tools/brainspace_mcp.py"
    uv = "C:/Program Files/tools/uv.exe"
    arguments = installer._uv_run_args(script)
    assert arguments[:3] == ["run", "--with", "mcp>=1,<2"]
    command = installer._uv_run_cmd(uv, script)
    assert '--with "mcp>=1,<2"' in command
    assert shlex.split(command) == [uv] + arguments


def test_graph_both_hosts_launch_mcp_v1(monkeypatch, tmp_path):
    template = (SKILL / "agent.template.copilot.md").read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(template.split("---", 2)[1])
    args = frontmatter["mcp-servers"]["graphify-nav"]["args"]
    assert args[:3] == ["run", "--with", "mcp>=1,<2"]
    installer = _load_script("graph_launch", SKILL / "setup.py", monkeypatch)
    config_path = tmp_path / "claude-mcp.json"
    config_path.write_text('{"mcpServers":{"external":{"command":"external-tool"}}}', encoding="utf-8")
    monkeypatch.setattr(installer, "_claude_mcp_config_path", lambda: config_path)
    installer._write_claude_mcp_servers("uv", "graphify_mcp.py", None, None)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["mcpServers"]["graphify-nav"]["args"][:3] == ["run", "--with", "mcp>=1,<2"]
    assert config["mcpServers"]["external"] == {"command": "external-tool"}


@pytest.mark.parametrize(
    "relative,pinned_literal,original_literal,upstream_digest",
    [
        (
            "setup.py", '"mcp>=1,<2"', '"mcp"',
            "aa98580a8ccd522392b2e38e152567b5591098e82a2e627a374b6d94a2676179",
        ),
        (
            "agent.template.copilot.md", "'mcp>=1,<2'", "'mcp'",
            "7734ba8f8a770744962cdb4172c32795b5fffbfc2033cf80369a34d379627bd5",
        ),
    ],
)
def test_graph_compatibility_patch_changes_only_launch_dependency(
    relative, pinned_literal, original_literal, upstream_digest
):
    content = (SKILL / relative).read_text(encoding="utf-8")
    assert content.count(pinned_literal) == 1
    original = content.replace(pinned_literal, original_literal)
    assert hashlib.sha256(original.encode("utf-8")).hexdigest() == upstream_digest
