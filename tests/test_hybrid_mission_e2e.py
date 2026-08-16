"""End-to-end proof for issue #86: a genuinely mixed local+cloud Phoenix mission.

Non-vacuity contract (issues #139 / #143). PR #130 closed #86 with a test that constructed
`Event(INTEGRATION_COMPLETED, ok=True)` and then asserted that event was present. It ran no
part of Phoenix and still collected a valid failure-first trace, because RED came from the
file not existing rather than from a property being false.

This proof is built to be incapable of that:

* It reaches the system under test only through `subprocess`, driving the real
  `phoenix_mission` binary.
* Every assertion reads evidence Phoenix produced -- the run ledger it wrote and the trace
  chains verified by `phoenix-mcp verify-trace`. Nothing asserted here is constructed here.
* The cloud leg drives the real `HttpCloudClient` over real HTTP against a local stub, so the
  cloud code path genuinely executes. `from_env()` honours COPILOT_API_URL / GITHUB_API_URL,
  which is the seam that makes this possible without a live Copilot job.

The stub speaks the wire contract recorded in src/cloud_backend.rs:
    submit : POST {COPILOT_API_URL}/agents/swe/v1/jobs/{owner}/{repo}  -> {"job_id": ...}
    poll   : GET  {GITHUB_API_URL}/agents/repos/{owner}/{repo}/tasks/{id} -> {"state": ...}
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OWNER, REPO = "All-The-Vibes", "ATV-Phoenix"

# Backend names exactly as Phoenix records them: LOCAL_BACKEND_NAME in src/execution_backend.rs
# and CLOUD_BACKEND_NAME in src/cloud_backend.rs. Spelled out rather than inferred so a rename
# on either constant fails this proof loudly instead of silently matching nothing.
LOCAL, CLOUD = "local", "copilot_cloud"

# Which backend each goal in the phoenix_mission diamond must run on. The point of the whole
# proof is that these are not all the same value: goal "b" runs in the cloud while "a", "c"
# and "d" run locally, and "d" depends on both a cloud goal ("b") and a local one ("c").
EXPECTED_ROUTE = {"a": LOCAL, "b": CLOUD, "c": LOCAL, "d": LOCAL}


def _bin(name: str) -> Path:
    exe = f"{name}.exe" if os.name == "nt" else name
    return REPO_ROOT / "target" / "debug" / exe


@pytest.fixture(scope="module")
def binaries() -> dict[str, Path]:
    """Build the binaries under test.

    Deliberately builds rather than skipping when absent. A proof that quietly skips when the
    system under test is not present is the same vacuity this file exists to avoid.
    """
    if shutil.which("cargo") is None:
        pytest.fail("cargo is required to build the system under test for this proof")
    subprocess.run(
        ["cargo", "build", "--quiet", "--bin", "phoenix_mission", "--bin", "phoenix-mcp"],
        cwd=REPO_ROOT,
        check=True,
    )
    built = {"mission": _bin("phoenix_mission"), "mcp": _bin("phoenix-mcp")}
    for label, path in built.items():
        assert path.exists(), f"{label} binary missing after build: {path}"
    return built


class _CopilotStub(BaseHTTPRequestHandler):
    """Minimal Copilot jobs API. Records what it was asked so the test can prove it was used."""

    submits: list[dict] = []
    polls: list[str] = []

    def log_message(self, *args):  # silence stderr noise
        return

    def _reply(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode() if length else "{}"
        expected = f"/agents/swe/v1/jobs/{OWNER}/{REPO}"
        if self.path != expected:
            self._reply({"message": f"unexpected submit path {self.path}"}, 404)
            return
        body = json.loads(raw)
        type(self).submits.append(body)
        # Task id is derived from the submitted work so poll can stay stateless.
        self._reply({"job_id": f"task-{len(type(self).submits)}"}, 201)

    def do_GET(self):
        prefix = f"/agents/repos/{OWNER}/{REPO}/tasks/"
        if not self.path.startswith(prefix):
            self._reply({"message": f"unexpected poll path {self.path}"}, 404)
            return
        task_id = self.path[len(prefix):]
        type(self).polls.append(task_id)
        self._reply({
            "state": "completed",
            "sessions": [],
            "artifacts": [],
            "model": "stub-model",
            "input_tokens": 1,
            "output_tokens": 1,
            "cost_micros": 0,
        })


@pytest.fixture
def stub_copilot():
    _CopilotStub.submits = []
    _CopilotStub.polls = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CopilotStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", _CopilotStub
    finally:
        server.shutdown()
        server.server_close()


def run_mixed_mission(binaries, base_url: str, workspace: Path) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "GITHUB_TOKEN": "stub-token",
        "GITHUB_REPOSITORY": f"{OWNER}/{REPO}",
        "COPILOT_API_URL": base_url,
        "GITHUB_API_URL": base_url,
    }
    return subprocess.run(
        [str(binaries["mission"]), "--backend", "mixed", "--workspace", str(workspace)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def read_ledger(workspace: Path) -> list[dict]:
    ledger = workspace / "run-ledger.jsonl"
    assert ledger.exists(), f"phoenix wrote no run ledger at {ledger}"
    entries = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def verify_trace(binaries, workspace: Path) -> dict:
    """Ask Phoenix to audit its own trace chain. The verdict is Phoenix's, not this test's."""
    result = subprocess.run(
        [str(binaries["mcp"]), "verify-trace"],
        cwd=REPO_ROOT,
        env={**os.environ, "PHOENIX_WORKSPACE": str(workspace)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"verify-trace failed:\n{result.stdout}\n{result.stderr}"
    return json.loads(result.stdout)


def test_mixed_mission_runs_goals_on_two_different_backends(binaries, stub_copilot, tmp_path):
    """The load-bearing property: one mission, two backends, recorded by Phoenix itself."""
    base_url, stub = stub_copilot
    workspace = tmp_path / "mission"

    result = run_mixed_mission(binaries, base_url, workspace)
    assert result.returncode == 0, (
        f"mixed mission failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    entries = read_ledger(workspace)
    observed = {entry["goal"]: entry["backend"] for entry in entries}
    assert observed == EXPECTED_ROUTE, (
        "the mission did not route goals across two backends; "
        f"expected {EXPECTED_ROUTE}, ledger recorded {observed}"
    )
    assert len({entry["backend"] for entry in entries}) >= 2, (
        "every goal ran on the same backend, so this mission was not hybrid"
    )


def test_the_cloud_leg_actually_reached_the_cloud_client(binaries, stub_copilot, tmp_path):
    """Guards against a 'cloud' backend that never makes a request and reports success anyway."""
    base_url, stub = stub_copilot
    workspace = tmp_path / "mission"

    result = run_mixed_mission(binaries, base_url, workspace)
    assert result.returncode == 0, f"mixed mission failed\n{result.stdout}\n{result.stderr}"

    assert stub.submits, "no job was ever submitted, so the cloud backend never ran"
    assert stub.polls, "a job was submitted but never polled, so its result was never read"
    cloud_goals = [g for g, b in EXPECTED_ROUTE.items() if b == CLOUD]
    assert len(stub.submits) == len(cloud_goals), (
        f"expected exactly {len(cloud_goals)} cloud submit(s), saw {len(stub.submits)}"
    )


def test_every_goal_is_shipped_exactly_once(binaries, stub_copilot, tmp_path):
    """Durable execution requires no duplicate shipping side effect."""
    base_url, _ = stub_copilot
    workspace = tmp_path / "mission"

    result = run_mixed_mission(binaries, base_url, workspace)
    assert result.returncode == 0, f"mixed mission failed\n{result.stdout}\n{result.stderr}"

    goals = [entry["goal"] for entry in read_ledger(workspace)]
    duplicates = {goal for goal in goals if goals.count(goal) > 1}
    assert not duplicates, f"these goals were shipped more than once: {sorted(duplicates)}"
    assert sorted(goals) == sorted(EXPECTED_ROUTE), (
        f"expected every goal exactly once, ledger recorded {sorted(goals)}"
    )


def test_the_mission_trace_verifies_intact(binaries, stub_copilot, tmp_path):
    """Phoenix must be able to audit its own hybrid run afterwards."""
    base_url, _ = stub_copilot
    workspace = tmp_path / "mission"

    result = run_mixed_mission(binaries, base_url, workspace)
    assert result.returncode == 0, f"mixed mission failed\n{result.stdout}\n{result.stderr}"

    report = verify_trace(binaries, workspace)
    assert report.get("ok") is True, f"trace did not verify intact: {report}"
    assert report.get("broken_at") is None, f"trace broke at row {report.get('broken_at')}"
