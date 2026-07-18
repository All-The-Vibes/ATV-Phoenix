import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
PS_DRIVER = REPO / "dist" / "ralph" / "phoenix-ralph.ps1"
BASH_DRIVER = REPO / "dist" / "ralph" / "phoenix-ralph.sh"


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_tools(tmp_path: Path) -> tuple[Path, Path]:
    phoenix_py = _write_executable(
        tmp_path / "fake_phoenix.py",
        f"""#!{sys.executable}
import json, os, pathlib, shutil, sys
log = pathlib.Path(os.environ["RALPH_EVENT_LOG"])
event = {{"event": sys.argv[1], "args": sys.argv[2:]}}
with log.open("a", encoding="utf-8") as f:
    f.write(json.dumps(event) + "\\n")
command = sys.argv[1]
if command in ("contract-freeze", "contract-rescope"):
    baseline = pathlib.Path(sys.argv[2])
    check = pathlib.Path(sys.argv[3][1:])
    if baseline.is_absolute():
        raise SystemExit(2)
    if command == "contract-rescope" and os.environ.get("RALPH_REJECT_RESCOPE") == "1":
        raise SystemExit(1)
    if command == "contract-freeze" and baseline.exists():
        raise SystemExit(0 if baseline.read_bytes() == check.read_bytes() else 1)
    shutil.copyfile(check, baseline)
    raise SystemExit(0)
if command == "contract-validate":
    baseline = pathlib.Path(sys.argv[2])
    check = pathlib.Path(sys.argv[3][1:])
    raise SystemExit(0 if baseline.exists() and baseline.read_bytes() == check.read_bytes() else 1)
if command == "sense":
    raise SystemExit(0 if os.environ.get("RALPH_PREGREEN") == "1" else 1)
if command == "accept":
    print('{{"ok":false}}')
    raise SystemExit(1)
if command == "verify-trace":
    raise SystemExit(0)
raise SystemExit(2)
""",
    )
    copilot_py = _write_executable(
        tmp_path / "fake_copilot.py",
        f"""#!{sys.executable}
import json, os, pathlib, sys
log = pathlib.Path(os.environ["RALPH_EVENT_LOG"])
with log.open("a", encoding="utf-8") as f:
    f.write(json.dumps({{"event": "agent", "args": sys.argv[1:]}}) + "\\n")
root = pathlib.Path.cwd()
trace = root / ".phoenix" / "trace.jsonl"
trace.parent.mkdir(exist_ok=True)
trace.write_text(trace.read_text(encoding="utf-8") + "turn\\n" if trace.exists() else "turn\\n", encoding="utf-8")
(root / ".phoenix-ralph" / "backlog.json").write_text(log.read_text(encoding="utf-8"), encoding="utf-8")
if os.environ.get("RALPH_MUTATE_CONTRACT") == "1":
    (root / ".phoenix-ralph" / "done-check.json").write_text('{{"changed":true}}', encoding="utf-8")
raise SystemExit(0)
""",
    )
    if os.name != "nt":
        return phoenix_py, copilot_py

    def cmd_wrapper(name: str, target: Path) -> Path:
        return _write_executable(
            tmp_path / name,
            f'@"{sys.executable}" "{target}" %*\n',
        )

    return cmd_wrapper("fake-phoenix.cmd", phoenix_py), cmd_wrapper(
        "fake-copilot.cmd", copilot_py
    )


def _workspace(tmp_path: Path) -> Path:
    state = tmp_path / ".phoenix-ralph"
    state.mkdir()
    (state / "done-check.json").write_text('{"initial":true}', encoding="utf-8")
    (state / "PROMPT.md").write_text("perform one turn", encoding="utf-8")
    return tmp_path


def _available_drivers() -> list[str]:
    drivers = []
    if shutil.which("pwsh"):
        drivers.append("powershell")
    if _bash_executable():
        drivers.append("bash")
    return drivers


def _bash_executable() -> str | None:
    if os.name != "nt":
        return shutil.which("bash")
    git = shutil.which("git")
    if git:
        candidate = Path(git).parent.parent / "bin" / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def _run_driver(
    driver: str,
    workspace: Path,
    phoenix: Path,
    copilot: Path,
    *,
    loops: int,
    rescope: bool = False,
    mutate: bool = False,
    pregreen: bool = False,
    reject_rescope: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "RALPH_EVENT_LOG": str(workspace / "events.jsonl"),
            "RALPH_MUTATE_CONTRACT": "1" if mutate else "0",
            "RALPH_PREGREEN": "1" if pregreen else "0",
            "RALPH_REJECT_RESCOPE": "1" if reject_rescope else "0",
            "PHOENIX_BIN": str(phoenix),
            "COPILOT": str(copilot),
            "MAX_LOOPS": str(loops),
            "NO_PROGRESS_STOP": "10",
            "NO_TAG": "1",
        }
    )
    if driver == "powershell":
        command = [
            shutil.which("pwsh"),
            "-NoProfile",
            "-File",
            str(PS_DRIVER),
            "-PhoenixBin",
            str(phoenix),
            "-Copilot",
            str(copilot),
            "-MaxLoops",
            str(loops),
            "-NoProgressStop",
            "10",
            "-NoTag",
        ]
        if rescope:
            command.append("-ReScope")
    else:
        command = [_bash_executable(), str(BASH_DRIVER)]
        if rescope:
            command.append("--rescope")
    return subprocess.run(
        command,
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _events(workspace: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (workspace / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


@pytest.mark.parametrize("driver", _available_drivers())
def test_freezes_once_and_validates_before_every_accept_and_after_turns(
    tmp_path: Path, driver: str
):
    workspace = _workspace(tmp_path)
    phoenix, copilot = _fake_tools(tmp_path)

    result = _run_driver(driver, workspace, phoenix, copilot, loops=2)

    assert result.returncode == 1, result.stdout + result.stderr
    events = _events(workspace)
    names = [event["event"] for event in events]
    assert names.count("contract-freeze") == 1
    assert names.count("agent") == 2
    assert names.count("accept") == 3
    assert names.count("contract-validate") == 5
    for index, name in enumerate(names):
        if name == "accept":
            assert names[index - 1] == "contract-validate"
        if name == "agent":
            assert names[index + 1] == "contract-validate"

    freeze = next(event for event in events if event["event"] == "contract-freeze")
    assert Path(freeze["args"][0]).name == "acceptance-contract.json"
    assert not Path(freeze["args"][0]).is_absolute()
    assert Path(freeze["args"][1][1:]) == (
        workspace / ".phoenix-ralph" / "done-check.json"
    )


@pytest.mark.parametrize("driver", _available_drivers())
def test_contract_mismatch_after_agent_turn_fails_closed(tmp_path: Path, driver: str):
    workspace = _workspace(tmp_path)
    phoenix, copilot = _fake_tools(tmp_path)

    result = _run_driver(
        driver, workspace, phoenix, copilot, loops=2, mutate=True
    )

    assert result.returncode == 2
    assert "acceptance contract mismatch after agent iteration 1" in (
        result.stdout + result.stderr
    )
    names = [event["event"] for event in _events(workspace)]
    assert names[-2:] == ["agent", "contract-validate"]
    assert names.count("accept") == 1
    assert "verify-trace" not in names


@pytest.mark.parametrize("driver", _available_drivers())
@pytest.mark.parametrize("rescope", [False, True])
def test_pre_green_abort_does_not_create_acceptance_contract(
    tmp_path: Path, driver: str, rescope: bool
):
    workspace = _workspace(tmp_path)
    phoenix, copilot = _fake_tools(tmp_path)

    result = _run_driver(
        driver, workspace, phoenix, copilot, loops=0, rescope=rescope, pregreen=True
    )

    assert result.returncode == 2
    assert "ALREADY GREEN" in result.stdout + result.stderr
    assert not (
        workspace / ".phoenix-ralph" / "acceptance-contract.json"
    ).exists()
    assert [event["event"] for event in _events(workspace)] == ["sense"]


@pytest.mark.parametrize("driver", _available_drivers())
def test_explicit_rescope_uses_contract_rescope_with_current_done_file(
    tmp_path: Path, driver: str
):
    workspace = _workspace(tmp_path)
    phoenix, copilot = _fake_tools(tmp_path)
    contract = workspace / ".phoenix-ralph" / "acceptance-contract.json"
    contract.write_text('{"old":true}', encoding="utf-8")

    result = _run_driver(
        driver, workspace, phoenix, copilot, loops=0, rescope=True
    )

    assert result.returncode == 1, result.stdout + result.stderr
    events = _events(workspace)
    names = [event["event"] for event in events]
    assert "contract-freeze" not in names
    rescope = next(event for event in events if event["event"] == "contract-rescope")
    assert Path(rescope["args"][0]) == (
        Path(".phoenix-ralph") / "acceptance-contract.json"
    )
    assert Path(rescope["args"][1][1:]) == (
        workspace / ".phoenix-ralph" / "done-check.json"
    )


@pytest.mark.parametrize("driver", _available_drivers())
def test_rejected_rescope_fails_closed_without_replacing_baseline(
    tmp_path: Path, driver: str
):
    workspace = _workspace(tmp_path)
    phoenix, copilot = _fake_tools(tmp_path)
    contract = workspace / ".phoenix-ralph" / "acceptance-contract.json"
    original = b'{"old":true}'
    contract.write_bytes(original)

    result = _run_driver(
        driver,
        workspace,
        phoenix,
        copilot,
        loops=0,
        rescope=True,
        reject_rescope=True,
    )

    assert result.returncode == 2
    assert "acceptance contract re-scope rejected" in result.stdout + result.stderr
    assert contract.read_bytes() == original
    assert [event["event"] for event in _events(workspace)] == [
        "sense",
        "contract-rescope",
    ]


def test_bash_exposes_only_explicit_rescope_path():
    script = BASH_DRIVER.read_text(encoding="utf-8")
    assert "--rescope) RESCOPE=1" in script
    assert (
        '"$PHOENIX_BIN" contract-rescope "$acceptance_contract_arg" "$done_arg"'
        in script
    )
