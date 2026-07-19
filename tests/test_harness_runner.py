import hashlib
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "evals" / "harness-eval" / "run_harness.ps1"
VERIFIERS = ROOT / "evals" / "harness-eval" / "verifiers.py"
PROTOCOL = ROOT / "evals" / "harness-eval" / "protocol.json"
TASK_FIXTURES = ROOT / "evals" / "swe-bench-lite" / "tasks"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
TASK_IDS = [
    "cache-lru",
    "csv-parser",
    "date-range",
    "hard-dedupe",
    "hard-slugify",
    "hard-titlecase",
    "hard-truncate",
    "money-round",
    "retry-backoff",
]


def load_verifiers():
    spec = importlib.util.spec_from_file_location("harness_verifiers", VERIFIERS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def make_task(base: Path, broken: bool = True) -> Path:
    task = base / "cache-lru"
    task.mkdir(parents=True)
    (task / "problem.md").write_text("Implement a true LRU cache.\n", encoding="utf-8")
    source = (
        "class LRUCache:\n"
        "    def __init__(self, capacity): self.capacity, self.data = capacity, {}\n"
        "    def get(self, key): return self.data.get(key)\n"
        "    def put(self, key, value): self.data[key] = value\n"
    )
    if not broken:
        source = correct_lru()
    (task / "solution.py").write_text(source, encoding="utf-8")
    (task / "test_f2p.py").write_text(
        "from solution import LRUCache\n"
        "def test_lru():\n"
        " c=LRUCache(2); c.put('a',1); c.put('b',2); assert c.get('a')==1;"
        " c.put('c',3); assert c.get('b') is None\n",
        encoding="utf-8",
    )
    (task / "test_p2p.py").write_text(
        "from solution import LRUCache\n"
        "def test_basic():\n c=LRUCache(1); c.put('x',7); assert c.get('x')==7\n",
        encoding="utf-8",
    )
    return task


def correct_lru() -> str:
    return (
        "from collections import OrderedDict\n"
        "class LRUCache:\n"
        "    def __init__(self, capacity):\n"
        "        self.capacity=capacity; self.data=OrderedDict()\n"
        "    def get(self, key):\n"
        "        if key not in self.data: return None\n"
        "        self.data.move_to_end(key); return self.data[key]\n"
        "    def put(self, key, value):\n"
        "        if key in self.data: self.data.move_to_end(key)\n"
        "        self.data[key]=value\n"
        "        if len(self.data)>self.capacity: self.data.popitem(last=False)\n"
    )


CORRECT_SOLUTIONS = {
    "cache-lru": correct_lru(),
    "csv-parser": (
        "import csv\n"
        "def parse_csv_line(line):\n"
        "    return next(csv.reader([line]))\n"
    ),
    "date-range": (
        "from datetime import timedelta\n"
        "def date_range(start, end):\n"
        "    result=[]\n"
        "    while start <= end:\n"
        "        result.append(start); start += timedelta(days=1)\n"
        "    return result\n"
    ),
    "hard-dedupe": (
        "def dedupe(items):\n"
        "    result=[]\n"
        "    for item in items:\n"
        "        if item not in result: result.append(item)\n"
        "    return result\n"
    ),
    "hard-slugify": (
        "import re\n"
        "def slugify(title):\n"
        "    value=re.sub(r'[^a-z0-9\\s-]', '', title.lower())\n"
        "    return re.sub(r'[-\\s]+', '-', value).strip('-')\n"
    ),
    "hard-titlecase": (
        "import re\n"
        "def titlecase(s):\n"
        "    return re.sub(r'\\S+', lambda m: m.group(0)[0].upper() + "
        "m.group(0)[1:].lower(), s)\n"
    ),
    "hard-truncate": (
        "def truncate(s, limit):\n"
        "    if len(s) <= limit: return s\n"
        "    if limit <= 3: return '.' * max(0, limit)\n"
        "    return s[:limit-3] + '...'\n"
    ),
    "money-round": (
        "from decimal import Decimal, ROUND_HALF_UP\n"
        "def round_money(amount):\n"
        "    return float(Decimal(str(amount)).quantize(Decimal('0.01'), "
        "rounding=ROUND_HALF_UP))\n"
    ),
    "retry-backoff": (
        "def retry(fn, attempts):\n"
        "    for index in range(attempts):\n"
        "        try: return fn()\n"
        "        except Exception:\n"
        "            if index == attempts - 1: raise\n"
    ),
}


def make_fake_copilot(path: Path) -> Path:
    script = path / "fake-copilot.ps1"
    solution = correct_lru().replace("'", "''")
    script.write_text(
        "$items=@($args)\n"
        "$wi=[Array]::IndexOf($items,'-C'); $work=$items[$wi+1]\n"
        "$pi=[Array]::IndexOf($items,'-p'); $prompt=$items[$pi+1]\n"
        "$before=@(Get-ChildItem -LiteralPath $work -File | % Name | Sort-Object)\n"
        f"Set-Content -LiteralPath (Join-Path $work 'solution.py') -Value '{solution}'\n"
        "$entry=[ordered]@{args=$items;workspace=$work;files=$before;prompt=$prompt}\n"
        "$entry|ConvertTo-Json -Compress|Add-Content -LiteralPath $env:FAKE_COPILOT_LOG\n"
        "Write-Output '{\"message\":\"DONE\"}'\n"
        "exit 0\n",
        encoding="utf-8",
    )
    return script


def run_runner(
    tasks: Path,
    output: Path,
    fake: Path,
    seeds=(104729, 130363),
    extra=(),
    env=None,
):
    assert POWERSHELL
    command = [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RUNNER),
        "-TasksDir",
        str(tasks),
        "-OutputDir",
        str(output),
        "-CopilotCommand",
        str(fake),
        "-Seeds",
        ",".join(map(str, seeds)),
        *extra,
    ]
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(command, capture_output=True, text=True, env=merged, timeout=90)


def make_production_fixture(base: Path, name: str):
    fixture_root = base / name
    harness = fixture_root / "evals" / "harness-eval"
    harness.mkdir(parents=True)
    shutil.copy2(VERIFIERS, harness / VERIFIERS.name)
    runner = harness / RUNNER.name
    runner_text = RUNNER.read_text(encoding="utf-8")
    runner_text = runner_text.replace(
        '$Seeds = "104729,130363,155921,181081,205759"',
        '$Seeds = "7"',
    )
    runner_text = runner_text.replace(
        '$DefaultSeeds = @(104729, 130363, 155921, 181081, 205759)',
        "$DefaultSeeds = @(7)",
    )
    expected_tasks = (
        '$ExpectedTasks = @("cache-lru", "csv-parser", "date-range", "hard-dedupe",\n'
        '    "hard-slugify", "hard-titlecase", "hard-truncate", "money-round", '
        '"retry-backoff")'
    )
    runner_text = runner_text.replace(expected_tasks, '$ExpectedTasks = @("cache-lru")')
    runner_text = runner_text.replace(
        "$Execution.min_repetitions -ne 5 -or "
        "$Execution.repetitions_per_task -ne 5",
        "$Execution.min_repetitions -ne 1 -or "
        "$Execution.repetitions_per_task -ne 1",
    )
    runner_text = runner_text.replace(
        '$RepoRoot = (Resolve-Path (Join-Path $HarnessDir "..\\..")).Path',
        f"$RepoRoot = '{str(ROOT).replace(chr(39), chr(39) * 2)}'",
    )
    fixture_tasks = fixture_root / "evals" / "swe-bench-lite" / "tasks"
    runner_text = runner_text.replace(
        '$DefaultTasksDir = Join-Path $RepoRoot "evals\\swe-bench-lite\\tasks"',
        f"$DefaultTasksDir = '{str(fixture_tasks).replace(chr(39), chr(39) * 2)}'",
    )
    assert '$Seeds = "7"' in runner_text
    assert "$DefaultSeeds = @(7)" in runner_text
    assert '$ExpectedTasks = @("cache-lru")' in runner_text
    assert "$Execution.min_repetitions -ne 1" in runner_text
    assert f"$DefaultTasksDir = '{fixture_tasks}'" in runner_text
    runner.write_text(runner_text, encoding="utf-8")

    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    protocol["pinning"]["seeds"]["values"] = [7]
    protocol["execution"]["min_repetitions"] = 1
    protocol["execution"]["repetitions_per_task"] = 1
    (harness / PROTOCOL.name).write_text(json.dumps(protocol), encoding="utf-8")
    make_task(fixture_tasks)
    return fixture_root, harness, runner


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell unavailable")
def test_runner_executes_paired_isolated_counterbalanced_runs(tmp_path):
    tasks = tmp_path / "tasks"
    make_task(tasks)
    fake = make_fake_copilot(tmp_path)
    output = tmp_path / "output"
    log = tmp_path / "fake.jsonl"

    completed = run_runner(
        tasks, output, fake, env={"FAKE_COPILOT_LOG": str(log)}
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout

    rows = [
        json.loads(line)
        for line in (output / "raw-runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(rows) == len(calls) == 4
    assert {(r["seed"], r["arm"]) for r in rows} == {
        (seed, arm)
        for seed in (104729, 130363)
        for arm in ("control", "phoenix")
    }
    for seed in (104729, 130363):
        expected_first = (
            "control"
            if int(hashlib.sha256(f"cache-lru{seed}".encode()).hexdigest()[-2:], 16)
            % 2
            == 0
            else "phoenix"
        )
        assert next(r["arm"] for r in rows if r["seed"] == seed) == expected_first

    workspaces = [Path(call["workspace"]) for call in calls]
    assert len(set(workspaces)) == 4
    assert all(not workspace.exists() for workspace in workspaces)
    for call, row in zip(calls, rows):
        args = call["args"]
        assert args.count("--add-dir") == 1
        assert args[args.index("--add-dir") + 1] == call["workspace"]
        assert args[args.index("-C") + 1] == call["workspace"]
        assert "--allow-all-paths" not in args
        for flag in (
            "--no-custom-instructions",
            "--no-remote",
            "--no-remote-export",
            "--no-auto-update",
            "--allow-all-tools",
        ):
            assert flag in args
        assert args[args.index("--model") + 1] == "gpt-5.6-sol"
        assert args[args.index("--output-format") + 1] == "json"
        assert "Task cache-lru" in call["prompt"]
        assert f"seed {row['seed']}" in call["prompt"]
        assert "verifier" not in call["prompt"].lower()
        assert "verifiers.py" not in call["files"]
        if row["arm"] == "control":
            assert args[-2:] == ["--disable-mcp-server", "phoenix"]
            assert call["files"] == ["problem.md", "solution.py"]
            assert "phoenix_sense" not in call["prompt"]
        else:
            assert "--disable-mcp-server" not in args
            assert call["files"] == [
                "problem.md",
                "solution.py",
                "test_f2p.py",
                "test_p2p.py",
            ]
            assert "phoenix MCP tools" in call["prompt"]
            assert "phoenix_sense" in call["prompt"]
            assert "python -m pytest test_f2p.py test_p2p.py -q" in call["prompt"]
        assert row["cost_units"] == 1
        assert row["claimed_done"] is True
        assert row["level1_pass"] is True
        assert row["level2_pass"] is True
        assert row["objective_pass"] is True
        for field in ("prompt_sha256", "transcript_sha256", "final_solution_sha256"):
            assert len(row[field]) == 64
        assert "transcript" not in row

    manifest = json.loads((output / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1.0"
    assert manifest["protocol_status"] == "preregistered"
    assert manifest["execution_status"] == "mechanics_only"
    assert manifest["evidence_classification"] == "mechanics_only"
    assert manifest["tasks"] == ["cache-lru"]
    assert manifest["pins"]["seeds"] == {
        "state": "pinned",
        "values": [104729, 130363],
    }
    assert len(manifest["pins"]["phoenix_source_commit"]["value"]) == 40
    assert manifest["pins"]["model_id"] == {
        "state": "pinned",
        "value": "gpt-5.6-sol",
    }
    assert manifest["pins"]["runner_hash"] == hashlib.sha256(RUNNER.read_bytes()).hexdigest()
    assert manifest["pins"]["runner_sha256"] == manifest["pins"]["runner_hash"]
    assert manifest["pins"]["raw_jsonl_hash"] == hashlib.sha256(
        (output / "raw-runs.jsonl").read_bytes()
    ).hexdigest()
    verifiers = load_verifiers()
    level1_hash = hashlib.sha256(inspect.getsource(verifiers.level1_sealed).encode()).hexdigest()
    level2_hash = hashlib.sha256(
        inspect.getsource(verifiers.level2_adversarial).encode()
    ).hexdigest()
    assert level1_hash != level2_hash
    assert manifest["pins"]["level_1_sealed_verifier_hash"]["value"] == (
        f"sha256:{level1_hash}"
    )
    assert manifest["pins"]["level_2_adversarial_verifier_hash"]["value"] == (
        f"sha256:{level2_hash}"
    )
    task_files = manifest["task_manifest"][0]["files"]
    for name, digest in task_files.items():
        assert digest == hashlib.sha256((tasks / "cache-lru" / name).read_bytes()).hexdigest()
    canonical_task_manifest = json.dumps(
        manifest["task_manifest"], separators=(",", ":"), ensure_ascii=False
    )
    assert manifest["pins"]["task_set_hash"]["value"] == hashlib.sha256(
        canonical_task_manifest.encode()
    ).hexdigest()
    canonical_environment = json.dumps(
        manifest["environment"], separators=(",", ":"), ensure_ascii=False
    )
    assert manifest["pins"]["environment_manifest_hash"]["value"] == hashlib.sha256(
        canonical_environment.encode()
    ).hexdigest()
    environment_text = json.dumps(manifest["environment"]).lower()
    assert "username" not in environment_text
    assert str(Path.home()).lower() not in environment_text
    assert manifest["environment"]["dependencies"]["pytest"] == pytest.__version__
    assert manifest["environment"]["resource_limits"] == {
        "enforcement": "none",
        "windows_job_object": "not_configured",
        "process_memory": "os_managed",
        "cpu_time": "os_managed",
        "processor_count": os.cpu_count(),
    }
    assert all(
        "PREREGISTRATION_PLACEHOLDER" not in str(value)
        for value in manifest["pins"].values()
    )
    artifacts = (output / "raw-runs.jsonl").read_text() + (
        output / "run-manifest.json"
    ).read_text()
    assert '{"message":"DONE"}' not in artifacts
    assert "objective checks failed" not in artifacts
    assert "adversarial checks failed" not in artifacts


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell unavailable")
def test_runner_refuses_overwrite_without_explicit_force(tmp_path):
    tasks = tmp_path / "tasks"
    make_task(tasks)
    fake = make_fake_copilot(tmp_path)
    output = tmp_path / "output"
    env = {"FAKE_COPILOT_LOG": str(tmp_path / "fake.jsonl")}
    first = run_runner(tasks, output, fake, seeds=(7,), env=env)
    assert first.returncode == 0, first.stderr
    original = (output / "run-manifest.json").read_bytes()

    refused = run_runner(tasks, output, fake, seeds=(7,), env=env)
    assert refused.returncode != 0
    assert "use -Force" in refused.stderr
    assert (output / "run-manifest.json").read_bytes() == original

    replaced = run_runner(tasks, output, fake, seeds=(7,), extra=("-Force",), env=env)
    assert replaced.returncode == 0, replaced.stderr


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell unavailable")
def test_duplicate_seeds_are_rejected_before_any_run(tmp_path):
    tasks = tmp_path / "tasks"
    make_task(tasks)
    fake = make_fake_copilot(tmp_path)
    output = tmp_path / "output"
    log = tmp_path / "fake.jsonl"
    completed = run_runner(
        tasks,
        output,
        fake,
        seeds=(7, 7),
        env={"FAKE_COPILOT_LOG": str(log)},
    )
    assert completed.returncode != 0
    assert "unique integers" in completed.stderr
    assert not log.exists()
    assert not (output / "run-manifest.json").exists()


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell unavailable")
@pytest.mark.parametrize("missing", ["solution.py"])
def test_incomplete_task_packages_are_rejected_before_any_run(tmp_path, missing):
    tasks = tmp_path / "tasks"
    task = make_task(tasks)
    (task / missing).unlink()
    fake = make_fake_copilot(tmp_path)
    output = tmp_path / "output"
    log = tmp_path / "fake.jsonl"
    completed = run_runner(
        tasks,
        output,
        fake,
        seeds=(7,),
        env={"FAKE_COPILOT_LOG": str(log)},
    )
    assert completed.returncode != 0
    assert "task package is incomplete" in completed.stderr
    assert not log.exists()
    assert not (output / "run-manifest.json").exists()


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell unavailable")
def test_default_production_requires_build_stamp_before_calls(tmp_path):
    appdata = tmp_path / "appdata"
    (appdata / "npm").mkdir(parents=True)
    fake = appdata / "npm" / "copilot.cmd"
    fake.write_text("@echo called>\"%FAKE_COPILOT_LOG%\"\n@exit /b 99\n", encoding="ascii")
    log = tmp_path / "fake.jsonl"
    completed = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(RUNNER),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        env={
            **os.environ,
            "APPDATA": str(appdata),
            "FAKE_COPILOT_LOG": str(log),
        },
    )
    assert fake.exists()
    assert completed.returncode != 0
    assert "PHOENIX_BUILD_STAMP is required" in completed.stderr
    assert not log.exists()


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell unavailable")
def test_production_requires_frozen_pins_before_calls(tmp_path):
    _, harness, runner = make_production_fixture(tmp_path, "unfrozen")
    appdata = tmp_path / "appdata"
    fake_dir = appdata / "npm"
    fake_dir.mkdir(parents=True)
    log = tmp_path / "fake.jsonl"
    (fake_dir / "copilot.cmd").write_text(
        '@echo called>>"%FAKE_COPILOT_LOG%"\n@exit /b 99\n', encoding="ascii"
    )
    completed = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(runner)],
        capture_output=True,
        text=True,
        timeout=90,
        env={
            **os.environ,
            "APPDATA": str(appdata),
            "PHOENIX_BUILD_STAMP": "synthetic-unfrozen-build",
            "FAKE_COPILOT_LOG": str(log),
        },
    )
    assert completed.returncode != 0
    assert "pinned protocol is required" in completed.stderr
    assert not log.exists()
    assert not (harness / "results" / "run-manifest.json").exists()


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell unavailable")
def test_production_evidence_schema_matches_program_gate(tmp_path):
    required_pins = {
        "phoenix_source_commit",
        "phoenix_build_stamp",
        "model_id",
        "runner_version",
        "environment_manifest_hash",
        "task_set_hash",
        "seeds",
        "level_1_sealed_verifier_hash",
        "level_2_adversarial_verifier_hash",
    }
    row_fields = {
        "run_id",
        "task_id",
        "seed",
        "arm",
        "order",
        "started_utc",
        "completed_utc",
        "exit_code",
        "claimed_done",
        "model_id",
        "runner_sha256",
        "prompt_sha256",
        "transcript_sha256",
        "final_solution_sha256",
        "cost_units",
        "level1_pass",
        "level2_pass",
        "objective_pass",
        "mock_run",
    }

    appdata = tmp_path / "appdata"
    fake_dir = appdata / "npm"
    fake_dir.mkdir(parents=True)
    fake_python = tmp_path / "fake_copilot.py"
    fake_python.write_text(
        "import json, os, pathlib, subprocess, sys\n"
        "manifest_path = pathlib.Path(os.environ['EXPECTED_MANIFEST'])\n"
        "assert manifest_path.name == 'run-manifest.json'\n"
        "assert not manifest_path.with_name('manifest.json').exists()\n"
        "manifest = json.loads(manifest_path.read_text(encoding='utf-8'))\n"
        "assert manifest['execution_status'] == os.environ['EXPECTED_STATUS']\n"
        "assert manifest['evidence_classification'] == os.environ['EXPECTED_CLASSIFICATION']\n"
        f"required = {required_pins!r}\n"
        "assert required <= manifest['pins'].keys()\n"
        "for name in required:\n"
        "    pin = manifest['pins'][name]\n"
        "    key = 'values' if name == 'seeds' else 'value'\n"
        "    assert set(pin) == {'state', key} and pin['state'] == 'pinned'\n"
        "    assert 'PREREGISTRATION_PLACEHOLDER' not in str(pin[key])\n"
        "with open(os.environ['FAKE_COPILOT_LOG'], 'a', encoding='utf-8') as log:\n"
        "    log.write(json.dumps(manifest, separators=(',', ':')) + '\\n')\n"
        "if os.environ.get('INTERRUPT_RUN') == '1':\n"
        "    subprocess.run(['powershell', '-NoProfile', '-Command', "
        "\"$p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + "
        "(Get-CimInstance Win32_Process -Filter ('ProcessId=' + $PID))."
        "ParentProcessId); while ($p -and $p.Name -notmatch "
        "'^(powershell|pwsh)(\\.exe)?$') {$p=Get-CimInstance Win32_Process "
        "-Filter ('ProcessId=' + $p.ParentProcessId)}; "
        "if ($p) {Stop-Process -Id $p.ProcessId -Force}\"], check=False)\n"
        "    os._exit(86)\n"
        "args = sys.argv[1:]\n"
        "workspace = pathlib.Path(args[args.index('-C') + 1])\n"
        f"(workspace / 'solution.py').write_text({correct_lru()!r}, encoding='utf-8')\n"
        "print('{\"message\":\"DONE\"}')\n",
        encoding="utf-8",
    )
    (fake_dir / "copilot.cmd").write_text(
        f'@"{sys.executable}" "{fake_python}" %*\n', encoding="ascii"
    )

    def invoke(runner, env, extra=()):
        return subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(runner),
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=90,
            env={**os.environ, "APPDATA": str(appdata), **env},
        )

    def assert_completed(harness, classification, mock_run):
        manifest_path = harness / "results" / "run-manifest.json"
        assert manifest_path.is_file()
        assert not (harness / "results" / "manifest.json").exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["execution_status"] == (
            "mechanics_only" if mock_run else "completed"
        )
        assert manifest["evidence_classification"] == classification
        assert set(manifest) == {
            "schema_version",
            "protocol_id",
            "protocol_status",
            "execution_status",
            "evidence_classification",
            "tasks",
            "environment",
            "pins",
            "task_manifest",
            "run_count",
        }
        assert manifest["schema_version"] == "1.0"
        assert manifest["protocol_status"] == "preregistered"
        assert manifest["tasks"] == ["cache-lru"]
        assert set(manifest["pins"]) == required_pins | {
            "runner_hash",
            "raw_jsonl_hash",
            "runner_sha256",
            "completion_utc",
        }
        for name in required_pins:
            pin = manifest["pins"][name]
            key = "values" if name == "seeds" else "value"
            assert set(pin) == {"state", key}
            assert pin["state"] == "pinned"
            assert "PREREGISTRATION_PLACEHOLDER" not in str(pin[key])

        raw_path = harness / "results" / "raw-runs.jsonl"
        runner_sha = hashlib.sha256((harness / RUNNER.name).read_bytes()).hexdigest()
        assert manifest["pins"]["runner_hash"] == runner_sha
        assert manifest["pins"]["runner_sha256"] == runner_sha
        assert manifest["pins"]["raw_jsonl_hash"] == hashlib.sha256(
            raw_path.read_bytes()
        ).hexdigest()
        completion = datetime.fromisoformat(
            manifest["pins"]["completion_utc"].replace("Z", "+00:00")
        )
        assert completion.tzinfo is not None and completion.utcoffset() is not None

        rows = [
            json.loads(line)
            for line in raw_path.read_text(encoding="utf-8").splitlines()
        ]
        assert len(rows) == manifest["run_count"] == 2
        assert len({row["run_id"] for row in rows}) == 2
        for row in rows:
            assert set(row) == row_fields
            assert row["run_id"]
            assert row["model_id"] == manifest["pins"]["model_id"]["value"]
            assert row["runner_sha256"] == runner_sha
            assert row["mock_run"] is mock_run
            assert row["task_id"] == "cache-lru"
            assert row["seed"] == 7
            assert row["objective_pass"] is (
                row["level1_pass"] and row["level2_pass"]
            )
        return manifest

    _, production_harness, production_runner = make_production_fixture(
        tmp_path, "production"
    )
    production_log = tmp_path / "production-log.jsonl"
    production_env = {
        "PHOENIX_BUILD_STAMP": "synthetic-production-build",
        "EXPECTED_MANIFEST": str(production_harness / "results" / "run-manifest.json"),
        "EXPECTED_CLASSIFICATION": "benchmark",
        "EXPECTED_STATUS": "running",
        "FAKE_COPILOT_LOG": str(production_log),
    }
    frozen = invoke(
        production_runner,
        production_env,
        ("-FreezePins",),
    )
    assert frozen.returncode == 0, frozen.stderr + frozen.stdout
    assert not production_log.exists()
    production_results = production_harness / "results"
    pinned_path = production_results / "protocol-pinned.json"
    frozen_manifest_path = production_results / "run-manifest.json"
    assert pinned_path.is_file()
    pinned_protocol = json.loads(pinned_path.read_text(encoding="utf-8"))
    assert pinned_protocol["execution_status"] == "not_run"
    assert set(pinned_protocol["pinning"]) == required_pins
    for name, pin in pinned_protocol["pinning"].items():
        assert pin["state"] == "pinned"
        value = pin["values"] if name == "seeds" else pin["value"]
        assert "PREREGISTRATION_PLACEHOLDER" not in str(value)
        assert pin["immutable_during_run"] is True
    assert pinned_protocol["pinning"]["seeds"]["values"] == [7]
    frozen_manifest = json.loads(frozen_manifest_path.read_text(encoding="utf-8"))
    assert frozen_manifest["execution_status"] == "frozen"
    assert frozen_manifest["evidence_classification"] == "benchmark"
    assert frozen_manifest["run_count"] == 0
    assert not {"raw_jsonl_hash", "completion_utc"} & frozen_manifest["pins"].keys()
    assert not (production_results / "raw-runs.jsonl").exists()
    missing_command = invoke(
        production_runner,
        {**production_env, "APPDATA": str(tmp_path / "missing-appdata")},
    )
    assert missing_command.returncode != 0
    assert "Copilot command is missing" in missing_command.stderr
    assert not production_log.exists()
    assert json.loads(frozen_manifest_path.read_text(encoding="utf-8")) == frozen_manifest
    refused_refreeze = invoke(
        production_runner,
        production_env,
        ("-FreezePins",),
    )
    assert refused_refreeze.returncode != 0
    assert "use -Force" in refused_refreeze.stderr
    assert not production_log.exists()
    assert json.loads(frozen_manifest_path.read_text(encoding="utf-8")) == frozen_manifest

    production = invoke(production_runner, production_env)
    assert production.returncode == 0, production.stderr + production.stdout
    assert len(production_log.read_text(encoding="utf-8").splitlines()) == 2
    assert_completed(production_harness, "benchmark", False)

    mechanics_root, mechanics_harness, mechanics_runner = make_production_fixture(
        tmp_path, "mechanics"
    )
    mechanics_output = mechanics_harness / "results"
    mechanics_log = tmp_path / "mechanics-log.jsonl"
    mechanics = invoke(
        mechanics_runner,
        {
            "EXPECTED_MANIFEST": str(mechanics_output / "run-manifest.json"),
            "EXPECTED_CLASSIFICATION": "mechanics_only",
            "EXPECTED_STATUS": "mechanics_only",
            "FAKE_COPILOT_LOG": str(mechanics_log),
        },
        (
            "-TasksDir",
            str(mechanics_root / "evals" / "swe-bench-lite" / "tasks"),
            "-OutputDir",
            str(mechanics_output),
            "-CopilotCommand",
            str(fake_dir / "copilot.cmd"),
            "-Seeds",
            "7",
        ),
    )
    assert mechanics.returncode == 0, mechanics.stderr + mechanics.stdout
    assert_completed(mechanics_harness, "mechanics_only", True)

    _, interrupted_harness, interrupted_runner = make_production_fixture(
        tmp_path, "interrupted"
    )
    interrupted_log = tmp_path / "interrupted-log.jsonl"
    interrupted_env = {
        "PHOENIX_BUILD_STAMP": "synthetic-interrupted-build",
        "EXPECTED_MANIFEST": str(
            interrupted_harness / "results" / "run-manifest.json"
        ),
        "EXPECTED_CLASSIFICATION": "benchmark",
        "EXPECTED_STATUS": "running",
        "FAKE_COPILOT_LOG": str(interrupted_log),
        "INTERRUPT_RUN": "1",
    }
    interrupted_frozen = invoke(
        interrupted_runner,
        interrupted_env,
        ("-FreezePins",),
    )
    assert interrupted_frozen.returncode == 0
    assert not interrupted_log.exists()
    interrupted = invoke(interrupted_runner, interrupted_env)
    assert interrupted.returncode != 0
    running_path = interrupted_harness / "results" / "run-manifest.json"
    running = json.loads(running_path.read_text(encoding="utf-8"))
    assert running["execution_status"] == "running"
    assert running["evidence_classification"] == "benchmark"
    assert not {"raw_jsonl_hash", "completion_utc"} <= running["pins"].keys()
    with pytest.raises(AssertionError):
        assert_completed(interrupted_harness, "benchmark", False)


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell unavailable")
def test_missing_immutable_protocol_pin_is_rejected_before_calls(tmp_path):
    copied_harness = tmp_path / "copy" / "evals" / "harness-eval"
    copied_harness.mkdir(parents=True)
    shutil.copy2(RUNNER, copied_harness / RUNNER.name)
    shutil.copy2(VERIFIERS, copied_harness / VERIFIERS.name)
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    del protocol["pinning"]["task_set_hash"]
    (copied_harness / "protocol.json").write_text(json.dumps(protocol), encoding="utf-8")
    tasks = tmp_path / "tasks"
    make_task(tasks)
    fake = make_fake_copilot(tmp_path)
    output = tmp_path / "output"
    log = tmp_path / "fake.jsonl"
    command = [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(copied_harness / RUNNER.name),
        "-TasksDir",
        str(tasks),
        "-OutputDir",
        str(output),
        "-CopilotCommand",
        str(fake),
        "-Seeds",
        "7",
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=90,
        env={**os.environ, "FAKE_COPILOT_LOG": str(log)},
    )
    assert completed.returncode != 0
    assert "protocol pins are incomplete" in completed.stderr
    assert not log.exists()
    assert not (output / "run-manifest.json").exists()


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell unavailable")
@pytest.mark.parametrize(
    ("missing", "message"),
    [("verifiers.py", "verifier is missing"), ("protocol.json", "protocol is missing")],
)
def test_missing_harness_prerequisites_are_rejected(tmp_path, missing, message):
    copied_harness = tmp_path / "copy" / "evals" / "harness-eval"
    copied_harness.mkdir(parents=True)
    shutil.copy2(RUNNER, copied_harness / RUNNER.name)
    if missing != "verifiers.py":
        shutil.copy2(VERIFIERS, copied_harness / VERIFIERS.name)
    if missing != "protocol.json":
        shutil.copy2(PROTOCOL, copied_harness / PROTOCOL.name)
    tasks = tmp_path / "tasks"
    make_task(tasks)
    fake = make_fake_copilot(tmp_path)
    output = tmp_path / "output"
    completed = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(copied_harness / RUNNER.name),
            "-TasksDir",
            str(tasks),
            "-OutputDir",
            str(output),
            "-CopilotCommand",
            str(fake),
            "-Seeds",
            "7",
        ],
        capture_output=True,
        text=True,
        timeout=90,
        env={**os.environ, "FAKE_COPILOT_LOG": str(tmp_path / "fake.jsonl")},
    )
    assert completed.returncode != 0
    assert message in completed.stderr
    assert not (output / "run-manifest.json").exists()


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell unavailable")
@pytest.mark.parametrize(
    ("mode", "message", "raw_lines"),
    [
        ("malformed", "verifier JSON is malformed", 1),
        ("extra-fields", "verifier JSON is malformed", 1),
        ("wrong-reason", "verifier JSON is malformed", 1),
        ("process-fail", "verifier process failed", 1),
        ("duplicate-raw", "incomplete or duplicate arm pairs", 3),
    ],
)
def test_invalid_or_incomplete_pairs_leave_running_manifest(
    tmp_path, mode, message, raw_lines
):
    tasks = tmp_path / "tasks"
    make_task(tasks)
    fake = make_fake_copilot(tmp_path)
    output = tmp_path / "output"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    real_python = sys.executable
    (fake_bin / "python.cmd").write_text(
        "@echo off\n"
        "echo %*|findstr /C:\"--workspace\" >nul\n"
        "if not errorlevel 1 (\n"
        "  if exist \"%VERIFY_ONCE%\" (\n"
        "    if \"%VERIFY_MODE%\"==\"malformed\" (echo malformed-json&exit /b 0)\n"
        "    if \"%VERIFY_MODE%\"==\"extra-fields\" "
        "(echo {\"level1\":{\"pass\":true,\"reason\":\"passed\",\"detail\":\"leak\"},"
        "\"level2\":{\"pass\":true,\"reason\":\"passed\"}}&exit /b 0)\n"
        "    if \"%VERIFY_MODE%\"==\"wrong-reason\" "
        "(echo {\"level1\":{\"pass\":false,\"reason\":\"assertion secret\"},"
        "\"level2\":{\"pass\":true,\"reason\":\"passed\"}}&exit /b 0)\n"
        "    if \"%VERIFY_MODE%\"==\"process-fail\" exit /b 9\n"
        "    if \"%VERIFY_MODE%\"==\"duplicate-raw\" "
        "(copy /Y \"%RAW_PATH%\" \"%DUP_PATH%\" >nul&type \"%DUP_PATH%\" >> \"%RAW_PATH%\")\n"
        "  )\n"
        "  echo x>\"%VERIFY_ONCE%\"\n"
        ")\n"
        "\"%REAL_PYTHON%\" %*\n",
        encoding="ascii",
    )
    env = {
        "FAKE_COPILOT_LOG": str(tmp_path / "fake.jsonl"),
        "REAL_PYTHON": real_python,
        "VERIFY_ONCE": str(tmp_path / "verified.flag"),
        "VERIFY_MODE": mode,
        "RAW_PATH": str(output / "raw-runs.jsonl"),
        "DUP_PATH": str(tmp_path / "duplicate.jsonl"),
        "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
    }
    completed = run_runner(tasks, output, fake, seeds=(11,), env=env)
    assert completed.returncode != 0
    assert message in completed.stderr
    manifest = json.loads((output / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["execution_status"] == "mechanics_only"
    assert manifest["evidence_classification"] == "mechanics_only"
    assert manifest["run_count"] == 0
    raw = output / "raw-runs.jsonl"
    assert raw.exists()
    assert len(raw.read_text(encoding="utf-8").splitlines()) == raw_lines


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_verifier_pass_fail_for_every_task(task_id, tmp_path):
    verifiers = load_verifiers()
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    good.mkdir()
    bad.mkdir()
    task = TASK_FIXTURES / task_id
    (good / "solution.py").write_text(CORRECT_SOLUTIONS[task_id], encoding="utf-8")
    shutil.copy2(task / "solution.py", bad / "solution.py")

    assert verifiers.level1_sealed(task_id, good) == {"pass": True, "reason": "passed"}
    assert verifiers.level2_adversarial(task_id, good) == {
        "pass": True,
        "reason": "passed",
    }
    assert verifiers.level1_sealed(task_id, bad) == {
        "pass": False,
        "reason": "objective checks failed",
    }
    assert verifiers.level2_adversarial(task_id, bad) == {
        "pass": False,
        "reason": "adversarial checks failed",
    }


def test_level1_does_not_execute_or_copy_public_tests(tmp_path):
    verifiers = load_verifiers()
    task = tmp_path / "task"
    workspace = tmp_path / "workspace"
    task.mkdir()
    workspace.mkdir()
    marker = tmp_path / "public-test-executed"
    (workspace / "solution.py").write_text(correct_lru(), encoding="utf-8")
    (task / "test_f2p.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('f2p')\n"
        "raise AssertionError('public f2p executed')\n",
        encoding="utf-8",
    )
    (task / "test_p2p.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('p2p')\n"
        "raise AssertionError('public p2p executed')\n",
        encoding="utf-8",
    )
    assert verifiers.level1_sealed("cache-lru", workspace) == {
        "pass": True,
        "reason": "passed",
    }
    assert not marker.exists()
    assert not {
        "test_f2p.py",
        "test_p2p.py",
        "verifiers.py",
    }.intersection(path.name for path in workspace.iterdir())


def test_level1_rejects_superficial_solution_that_passes_public_gate(tmp_path):
    verifiers = load_verifiers()
    task = TASK_FIXTURES / "hard-truncate"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "solution.py").write_text(
        "def truncate(s, limit):\n"
        "    if len(s) <= limit: return s\n"
        "    return s[:limit - 3] + '...'\n",
        encoding="utf-8",
    )
    shutil.copy2(task / "test_f2p.py", workspace / "test_f2p.py")
    shutil.copy2(task / "test_p2p.py", workspace / "test_p2p.py")
    public = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "test_f2p.py",
            "test_p2p.py",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    assert public.returncode == 0, public.stdout + public.stderr
    (workspace / "test_f2p.py").unlink()
    (workspace / "test_p2p.py").unlink()
    assert verifiers.level1_sealed("hard-truncate", workspace) == {
        "pass": False,
        "reason": "objective checks failed",
    }


def test_hostile_solution_base_exception_is_a_generic_failure(tmp_path):
    verifiers = load_verifiers()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "solution.py").write_text(
        "raise SystemExit('hostile evaluator escape')\n", encoding="utf-8"
    )
    assert verifiers.level1_sealed("cache-lru", workspace) == {
        "pass": False,
        "reason": "objective checks failed",
    }
    assert verifiers.level2_adversarial("cache-lru", workspace) == {
        "pass": False,
        "reason": "adversarial checks failed",
    }
    completed = subprocess.run(
        [
            sys.executable,
            str(VERIFIERS),
            "--workspace",
            str(workspace),
            "--task-id",
            "cache-lru",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(completed.stdout) == {
        "level1": {"pass": False, "reason": "objective checks failed"},
        "level2": {"pass": False, "reason": "adversarial checks failed"},
    }


def test_candidate_cannot_replace_later_evaluator_level(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "solution.py").write_text(
        "import __main__\n"
        "from collections import OrderedDict\n"
        "__main__.level2_adversarial = lambda *args: "
        "{'pass': True, 'reason': 'passed'}\n"
        f"open(__file__, 'w', encoding='utf-8').write({correct_lru()!r})\n"
        "class LRUCache:\n"
        "    def __init__(self, capacity): self.data = OrderedDict()\n"
        "    def get(self, key):\n"
        "        if key not in self.data: return None\n"
        "        self.data.move_to_end(key); return self.data[key]\n"
        "    def put(self, key, value):\n"
        "        if key in self.data: self.data.move_to_end(key)\n"
        "        self.data[key] = value\n"
        "        if len(self.data) > 2: self.data.popitem(last=False)\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(VERIFIERS),
            "--workspace",
            str(workspace),
            "--task-id",
            "cache-lru",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(completed.stdout) == {
        "level1": {"pass": True, "reason": "passed"},
        "level2": {"pass": False, "reason": "adversarial checks failed"},
    }


def test_hard_dedupe_adversarial_values_are_distinct_on_equality_edge(
    tmp_path, monkeypatch
):
    verifiers = load_verifiers()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "solution.py").write_text(
        CORRECT_SOLUTIONS["hard-dedupe"], encoding="utf-8"
    )

    class EqualityEdgeRandom:
        def __init__(self, seed):
            self.seed = seed

        def randrange(self, *args):
            return 313

        def sample(self, population, count):
            return [313, 314, 315, 316]

    monkeypatch.setattr(verifiers.random, "Random", EqualityEdgeRandom)
    assert verifiers.level2_adversarial("hard-dedupe", workspace) == {
        "pass": True,
        "reason": "passed",
    }


def test_verifier_exact_source_hashes():
    verifiers = load_verifiers()
    expected = {
        "level1_sealed": hashlib.sha256(
            inspect.getsource(verifiers.level1_sealed).encode()
        ).hexdigest(),
        "level2_adversarial": hashlib.sha256(
            inspect.getsource(verifiers.level2_adversarial).encode()
        ).hexdigest(),
    }
    assert expected["level1_sealed"] != expected["level2_adversarial"]
    cli = subprocess.run(
        [sys.executable, str(VERIFIERS), "--hash-report"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(cli.stdout) == expected
