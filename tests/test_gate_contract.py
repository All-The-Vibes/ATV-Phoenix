import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def phoenix_bin() -> Path:
    subprocess.run(
        ["cargo", "build", "--quiet", "--bin", "phoenix-mcp"],
        cwd=REPO,
        check=True,
    )
    name = "phoenix-mcp.exe" if os.name == "nt" else "phoenix-mcp"
    return REPO / "target" / "debug" / name


def write_check(path: Path, exit_code: int, cwd: str = ".") -> None:
    path.write_text(
        json.dumps(
            {
                "kind": "command_exit",
                "target": [
                    sys.executable,
                    "-c",
                    f"raise SystemExit({exit_code})",
                ],
                "expect": 0,
                "cwd": cwd,
            }
        ),
        encoding="utf-8",
    )


def run_contract(
    phoenix_bin: Path,
    workspace: Path,
    command: str,
    baseline: Path,
    check: Path,
    process_cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PHOENIX_WORKSPACE"] = str(workspace)
    return subprocess.run(
        [
            str(phoenix_bin),
            command,
            str(baseline.relative_to(workspace)),
            f"@{check}",
        ],
        cwd=process_cwd or workspace,
        env=env,
        capture_output=True,
        text=True,
    )


def test_contract_freezes_red_check_and_validates_same_spec(
    phoenix_bin: Path, tmp_path: Path
):
    state = tmp_path / ".phoenix-ralph"
    state.mkdir()
    baseline = state / "acceptance-contract.json"
    broad = state / "broad.json"
    write_check(broad, exit_code=1)

    frozen = run_contract(phoenix_bin, tmp_path, "contract-freeze", baseline, broad)
    assert frozen.returncode == 0, frozen.stderr + frozen.stdout
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert payload["check_digest"]
    assert payload["check_spec"]["target"] == [
        sys.executable,
        "-c",
        "raise SystemExit(1)",
    ]

    validated = run_contract(
        phoenix_bin, tmp_path, "contract-validate", baseline, broad
    )
    assert validated.returncode == 0, validated.stderr + validated.stdout
    verdict = json.loads(validated.stdout)
    assert verdict["ok"] is True
    assert verdict["baseline_digest"] == payload["check_digest"]
    assert verdict["current_digest"] == payload["check_digest"]


def test_contract_rejects_silent_replacement_or_narrowing(
    phoenix_bin: Path, tmp_path: Path
):
    state = tmp_path / ".phoenix-ralph"
    state.mkdir()
    baseline = state / "acceptance-contract.json"
    broad = state / "broad.json"
    narrowed = state / "narrowed.json"
    write_check(broad, exit_code=1)
    write_check(narrowed, exit_code=0)

    assert (
        run_contract(phoenix_bin, tmp_path, "contract-freeze", baseline, broad)
        .returncode
        == 0
    )
    original = baseline.read_bytes()

    rejected = run_contract(
        phoenix_bin, tmp_path, "contract-validate", baseline, narrowed
    )
    assert rejected.returncode != 0
    verdict = json.loads(rejected.stdout)
    assert verdict["ok"] is False
    assert "changed" in verdict["reason"].lower()
    assert baseline.read_bytes() == original


def test_contract_digest_includes_execution_context(
    phoenix_bin: Path, tmp_path: Path
):
    state = tmp_path / ".phoenix-ralph"
    state.mkdir()
    baseline = state / "acceptance-contract.json"
    original = state / "original.json"
    moved = state / "moved.json"
    write_check(original, exit_code=1, cwd=".")
    write_check(moved, exit_code=1, cwd=".phoenix-ralph")

    assert (
        run_contract(phoenix_bin, tmp_path, "contract-freeze", baseline, original)
        .returncode
        == 0
    )
    rejected = run_contract(
        phoenix_bin, tmp_path, "contract-validate", baseline, moved
    )
    assert rejected.returncode != 0
    assert json.loads(rejected.stdout)["ok"] is False

    timeout_changed = json.loads(original.read_text(encoding="utf-8"))
    timeout_changed["timeout_secs"] = 1
    moved.write_text(json.dumps(timeout_changed), encoding="utf-8")
    timeout_result = run_contract(
        phoenix_bin, tmp_path, "contract-validate", baseline, moved
    )
    assert timeout_result.returncode != 0


def test_malformed_check_and_path_traversal_are_rejected_without_crash(
    phoenix_bin: Path, tmp_path: Path
):
    state = tmp_path / ".phoenix-ralph"
    state.mkdir()
    malformed = state / "malformed.json"
    malformed.write_text(
        json.dumps(
            {
                "kind": "file_sha256",
                "target": [],
                "expect": "00",
            }
        ),
        encoding="utf-8",
    )

    malformed_result = run_contract(
        phoenix_bin,
        tmp_path,
        "contract-freeze",
        state / "acceptance-contract.json",
        malformed,
    )
    assert malformed_result.returncode != 0
    assert malformed_result.returncode != -1073740791  # Windows stack-buffer/panic code
    assert json.loads(malformed_result.stdout)["ok"] is False

    outside = tmp_path.parent / "outside-contract.json"
    traversal = run_contract(
        phoenix_bin,
        tmp_path,
        "contract-freeze",
        tmp_path / ".." / "outside-contract.json",
        malformed,
    )
    assert traversal.returncode != 0
    assert not outside.exists()


def test_interpreter_script_body_is_bound_to_contract(
    phoenix_bin: Path, tmp_path: Path
):
    state = tmp_path / ".phoenix-ralph"
    state.mkdir()
    baseline = state / "acceptance-contract.json"
    script = tmp_path / "verify.py"
    check = state / "script-check.json"
    script.write_text("raise SystemExit(1)\n", encoding="utf-8")
    check.write_text(
        json.dumps(
            {
                "kind": "command_exit",
                "target": [sys.executable, "verify.py"],
                "expect": 0,
                "cwd": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )

    assert (
        run_contract(phoenix_bin, tmp_path, "contract-freeze", baseline, check)
        .returncode
        == 0
    )
    script.write_text("# changed verifier\nraise SystemExit(1)\n", encoding="utf-8")
    changed = run_contract(
        phoenix_bin, tmp_path, "contract-validate", baseline, check
    )
    assert changed.returncode != 0
    assert "changed" in json.loads(changed.stdout)["reason"].lower()


def test_direct_script_and_ui_verifier_bodies_are_bound(
    phoenix_bin: Path, tmp_path: Path
):
    state = tmp_path / ".phoenix-ralph"
    state.mkdir()

    if os.name == "nt":
        direct = tmp_path / "direct.cmd"
        direct.write_text("@exit /b 1\n", encoding="utf-8")
    else:
        direct = tmp_path / "direct.sh"
        direct.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        direct.chmod(0o755)
    direct_check = state / "direct.json"
    direct_check.write_text(
        json.dumps(
            {
                "kind": "command_exit",
                "target": [str(direct)],
                "expect": 0,
                "cwd": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    direct_baseline = state / "direct-contract.json"
    assert (
        run_contract(
            phoenix_bin, tmp_path, "contract-freeze", direct_baseline, direct_check
        ).returncode
        == 0
    )
    direct.write_text(
        ("@rem changed\n@exit /b 1\n" if os.name == "nt" else "#!/bin/sh\n# changed\nexit 1\n"),
        encoding="utf-8",
    )
    assert (
        run_contract(
            phoenix_bin,
            tmp_path,
            "contract-validate",
            direct_baseline,
            direct_check,
        ).returncode
        != 0
    )

    if not shutil.which("node"):
        pytest.skip("node is required for ui_behavior verifier test")
    ui = tmp_path / "verify.mjs"
    ui.write_text('console.log(JSON.stringify({ok:false}))\n', encoding="utf-8")
    ui_check = state / "ui.json"
    ui_check.write_text(
        json.dumps(
            {
                "kind": "ui_behavior",
                "target": ["verify.mjs"],
                "cwd": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    ui_baseline = state / "ui-contract.json"
    assert (
        run_contract(phoenix_bin, tmp_path, "contract-freeze", ui_baseline, ui_check)
        .returncode
        == 0
    )
    ui.write_text(
        '// changed\nconsole.log(JSON.stringify({ok:false}))\n',
        encoding="utf-8",
    )
    assert (
        run_contract(
            phoenix_bin, tmp_path, "contract-validate", ui_baseline, ui_check
        ).returncode
        != 0
    )


def test_relative_direct_script_contract_is_launcher_directory_independent(
    phoenix_bin: Path, tmp_path: Path
):
    state = tmp_path / ".phoenix-ralph"
    scripts = tmp_path / "scripts"
    state.mkdir()
    scripts.mkdir()
    if os.name == "nt":
        direct = scripts / "gate.cmd"
        direct.write_text("@exit /b 1\n", encoding="utf-8")
    else:
        direct = scripts / "gate.sh"
        direct.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        direct.chmod(0o755)
    check = state / "relative-direct.json"
    check.write_text(
        json.dumps(
            {
                "kind": "command_exit",
                "target": [direct.name],
                "expect": 0,
                "cwd": "scripts",
            }
        ),
        encoding="utf-8",
    )
    baseline = state / "relative-direct-contract.json"

    frozen = run_contract(
        phoenix_bin,
        tmp_path,
        "contract-freeze",
        baseline,
        check,
        process_cwd=REPO,
    )
    assert frozen.returncode == 0, frozen.stderr + frozen.stdout
    validated = run_contract(
        phoenix_bin,
        tmp_path,
        "contract-validate",
        baseline,
        check,
        process_cwd=tmp_path.parent,
    )
    assert validated.returncode == 0, validated.stderr + validated.stdout


def test_red_baseline_executes_relative_cwd_from_workspace(
    phoenix_bin: Path, tmp_path: Path
):
    state = tmp_path / ".phoenix-ralph"
    gate_dir = tmp_path / "gatecwd"
    state.mkdir()
    gate_dir.mkdir()
    (gate_dir / "probe.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    check = state / "relative-cwd.json"
    check.write_text(
        json.dumps(
            {
                "kind": "command_exit",
                "target": [sys.executable, "probe.py"],
                "expect": 0,
                "cwd": "gatecwd",
            }
        ),
        encoding="utf-8",
    )

    result = run_contract(
        phoenix_bin,
        tmp_path,
        "contract-freeze",
        state / "relative-cwd-contract.json",
        check,
        process_cwd=REPO,
    )
    assert result.returncode != 0
    assert "red" in json.loads(result.stdout)["reason"].lower()


def test_relative_direct_executable_runs_the_file_bound_from_contract_cwd(
    phoenix_bin: Path, tmp_path: Path
):
    state = tmp_path / ".phoenix-ralph"
    gate_dir = tmp_path / "gatecwd"
    state.mkdir()
    gate_dir.mkdir()
    gate = gate_dir / ("bound-gate.exe" if os.name == "nt" else "bound-gate")
    shutil.copy2(sys.executable, gate)
    if os.name != "nt":
        gate.chmod(0o755)
    check = state / "relative-executable.json"
    check.write_text(
        json.dumps(
            {
                "kind": "command_exit",
                "target": [gate.name, "-c", "raise SystemExit(0)"],
                "expect": 0,
                "cwd": "gatecwd",
            }
        ),
        encoding="utf-8",
    )

    result = run_contract(
        phoenix_bin,
        tmp_path,
        "contract-freeze",
        state / "relative-executable-contract.json",
        check,
        process_cwd=REPO,
    )
    assert result.returncode != 0
    assert "red" in json.loads(result.stdout)["reason"].lower()


def test_default_expect_and_explicit_zero_are_same_contract(
    phoenix_bin: Path, tmp_path: Path
):
    state = tmp_path / ".phoenix-ralph"
    state.mkdir()
    baseline = state / "acceptance-contract.json"
    implicit = state / "implicit.json"
    explicit = state / "explicit.json"
    base = {
        "kind": "command_exit",
        "target": [sys.executable, "-c", "raise SystemExit(1)"],
        "cwd": ".",
    }
    implicit.write_text(json.dumps(base), encoding="utf-8")
    explicit.write_text(json.dumps({**base, "expect": 0}), encoding="utf-8")

    assert (
        run_contract(phoenix_bin, tmp_path, "contract-freeze", baseline, implicit)
        .returncode
        == 0
    )
    equivalent = run_contract(
        phoenix_bin, tmp_path, "contract-validate", baseline, explicit
    )
    assert equivalent.returncode == 0, equivalent.stderr + equivalent.stdout


@pytest.mark.parametrize(
    "command",
    ["contract-freeze", "contract-validate", "contract-rescope"],
)
def test_contract_cli_missing_arguments_returns_usage_without_panic(
    phoenix_bin: Path, command: str
):
    result = subprocess.run(
        [str(phoenix_bin), command],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert result.returncode != 101
    assert "usage" in (result.stdout + result.stderr).lower()


def test_contract_cli_malformed_json_returns_structured_failure(
    phoenix_bin: Path, tmp_path: Path
):
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    env = os.environ.copy()
    env["PHOENIX_WORKSPACE"] = str(tmp_path)
    result = subprocess.run(
        [
            str(phoenix_bin),
            "contract-freeze",
            ".phoenix-ralph/acceptance-contract.json",
            f"@{bad}",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "json" in payload["reason"].lower()


def test_self_modifying_red_verifier_is_not_frozen_or_rescoped(
    phoenix_bin: Path, tmp_path: Path
):
    state = tmp_path / ".phoenix-ralph"
    state.mkdir()
    script = tmp_path / "self_modify.py"
    check = state / "self-modifying.json"
    script.write_text(
        "from pathlib import Path\n"
        "p = Path(__file__)\n"
        "p.write_text(p.read_text() + '# changed\\n')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    check.write_text(
        json.dumps(
            {
                "kind": "command_exit",
                "target": [sys.executable, str(script)],
                "expect": 0,
                "cwd": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    baseline = state / "acceptance-contract.json"

    frozen = run_contract(
        phoenix_bin, tmp_path, "contract-freeze", baseline, check
    )
    assert frozen.returncode != 0
    assert not baseline.exists()
    assert "changed" in json.loads(frozen.stdout)["reason"].lower()

    stable = state / "stable.json"
    write_check(stable, exit_code=1)
    assert (
        run_contract(phoenix_bin, tmp_path, "contract-freeze", baseline, stable)
        .returncode
        == 0
    )
    before = baseline.read_bytes()
    script.write_text(
        "from pathlib import Path\n"
        "p = Path(__file__)\n"
        "p.write_text(p.read_text() + '# changed again\\n')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    rescoped = run_contract(
        phoenix_bin, tmp_path, "contract-rescope", baseline, check
    )
    assert rescoped.returncode != 0
    assert baseline.read_bytes() == before
    assert "changed" in json.loads(rescoped.stdout)["reason"].lower()


def test_rescope_requires_new_check_red_and_replaces_baseline_explicitly(
    phoenix_bin: Path, tmp_path: Path
):
    state = tmp_path / ".phoenix-ralph"
    state.mkdir()
    baseline = state / "acceptance-contract.json"
    broad = state / "broad.json"
    green_replacement = state / "green.json"
    red_replacement = state / "red.json"
    write_check(broad, exit_code=1)
    write_check(green_replacement, exit_code=0)
    write_check(red_replacement, exit_code=2)

    assert (
        run_contract(phoenix_bin, tmp_path, "contract-freeze", baseline, broad)
        .returncode
        == 0
    )
    original = baseline.read_bytes()

    pre_green = run_contract(
        phoenix_bin,
        tmp_path,
        "contract-rescope",
        baseline,
        green_replacement,
    )
    assert pre_green.returncode != 0
    assert "red" in json.loads(pre_green.stdout)["reason"].lower()
    assert baseline.read_bytes() == original

    rescoped = run_contract(
        phoenix_bin, tmp_path, "contract-rescope", baseline, red_replacement
    )
    assert rescoped.returncode == 0, rescoped.stderr + rescoped.stdout
    verdict = json.loads(rescoped.stdout)
    assert verdict["ok"] is True
    assert verdict["action"] == "rescoped"

    validated = run_contract(
        phoenix_bin, tmp_path, "contract-validate", baseline, red_replacement
    )
    assert validated.returncode == 0, validated.stderr + validated.stdout
