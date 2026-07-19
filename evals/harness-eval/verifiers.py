"""Sealed objective verifiers for the preregistered harness evaluation."""

from __future__ import annotations

import argparse
import base64
import contextlib
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import importlib.util
import inspect
import io
import json
import os
import random
import subprocess
import sys
import types
from datetime import date, timedelta
from pathlib import Path


TASK_IDS = {
    "cache-lru",
    "csv-parser",
    "date-range",
    "hard-dedupe",
    "hard-slugify",
    "hard-titlecase",
    "hard-truncate",
    "money-round",
    "retry-backoff",
}


def _load_solution(solution: Path, label: str, source: bytes | None = None):
    candidate = solution.read_bytes() if source is None else source
    source_digest = hashlib.sha256(candidate).hexdigest()
    name = f"_{label}_{source_digest}"
    if source is None:
        spec = importlib.util.spec_from_file_location(name, solution)
        if spec is None or spec.loader is None:
            raise ImportError
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        module = types.ModuleType(name)
        module.__file__ = str(solution)
        exec(compile(candidate, str(solution), "exec"), module.__dict__)
    return module, source_digest


def level1_sealed(
    task_id: str, workspace: str | Path, _source: bytes | None = None
) -> dict[str, object]:
    """Run evaluator-owned task-specific objective checks against the final solution."""
    solution = Path(workspace).resolve() / "solution.py"
    if task_id not in TASK_IDS or (_source is None and not solution.is_file()):
        return {"pass": False, "reason": "objective checks failed"}
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            module, _ = _load_solution(solution, "phoenix_level1_candidate", _source)
            if task_id == "cache-lru":
                cache = module.LRUCache(2)
                cache.put("sealed-alpha", 11)
                cache.put("sealed-beta", 22)
                assert cache.get("sealed-alpha") == 11
                cache.put("sealed-gamma", 44)
                assert cache.get("sealed-beta") is None
                assert cache.get("sealed-alpha") == 11
                assert cache.get("sealed-gamma") == 44
            elif task_id == "csv-parser":
                assert module.parse_csv_line(
                    'left,"say ""hello"", now",,right'
                ) == ["left", 'say "hello", now', "", "right"]
            elif task_id == "date-range":
                start = date(2024, 2, 28)
                assert module.date_range(start, date(2024, 3, 1)) == [
                    date(2024, 2, 28),
                    date(2024, 2, 29),
                    date(2024, 3, 1),
                ]
                assert module.date_range(date(2025, 1, 2), date(2025, 1, 1)) == []
            elif task_id == "hard-dedupe":
                first = {"sealed": [1, 2]}
                second = {"sealed": [3]}
                assert module.dedupe(
                    [first, second, {"sealed": [1, 2]}, second]
                ) == [first, second]
            elif task_id == "hard-slugify":
                assert module.slugify("  Alpha___BETA / gamma---delta!!  ") == (
                    "alphabeta-gamma-delta"
                )
            elif task_id == "hard-titlecase":
                assert module.titlecase("sEAled\tMIXED  cASE") == "Sealed\tMixed  Case"
            elif task_id == "hard-truncate":
                assert module.truncate("sealed-value", 2) == ".."
                assert module.truncate("sealed-value", 0) == ""
                assert module.truncate("same", 4) == "same"
            elif task_id == "money-round":
                assert module.round_money(-7.125) == -7.13
                assert module.round_money(19.994) == 19.99
            elif task_id == "retry-backoff":
                calls = []
                result = object()

                def succeeds_second_time():
                    calls.append(len(calls))
                    if len(calls) == 1:
                        raise OSError("sealed transient")
                    return result

                assert module.retry(succeeds_second_time, 2) is result
                assert calls == [0, 1]
        return {"pass": True, "reason": "passed"}
    except BaseException:
        return {"pass": False, "reason": "objective checks failed"}


def level2_adversarial(
    task_id: str, workspace: str | Path, _source: bytes | None = None
) -> dict[str, object]:
    """Run task-specific API-grounded edge checks against the final solution."""
    solution = Path(workspace).resolve() / "solution.py"
    if task_id not in TASK_IDS or (_source is None and not solution.is_file()):
        return {"pass": False, "reason": "adversarial checks failed"}
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            module, source_digest = _load_solution(
                solution, "phoenix_level2_candidate", _source
            )
            rng = random.Random(int(source_digest[:16], 16))
            if task_id == "cache-lru":
                keys = [f"k{rng.randrange(10_000, 99_999)}-{index}" for index in range(5)]
                values = [rng.randrange(1_000_000) for _ in keys]
                cache = module.LRUCache(3)
                for key, value in zip(keys[:3], values[:3]):
                    cache.put(key, value)
                assert cache.get(keys[0]) == values[0]
                assert cache.get(keys[1]) == values[1]
                cache.put(keys[3], values[3])
                assert cache.get(keys[2]) is None
                cache.put(keys[0], values[4])
                cache.put(keys[4], values[4])
                assert cache.get(keys[1]) is None
                assert cache.get(keys[0]) == values[4]
                assert cache.get(keys[3]) == values[3]
            elif task_id == "csv-parser":
                fields = [f"v{rng.randrange(10_000, 99_999)}" for _ in range(4)]
                line = f'{fields[0]},"{fields[1]},{fields[2]}",{fields[3]}'
                assert module.parse_csv_line(line) == [
                    fields[0],
                    f"{fields[1]},{fields[2]}",
                    fields[3],
                ]
                assert module.parse_csv_line(f'"{fields[0]}","{fields[1]}"') == fields[:2]
            elif task_id == "date-range":
                start = date(2023 + rng.randrange(3), 12, 29)
                days = 3 + rng.randrange(3)
                expected = [start + timedelta(days=index) for index in range(days + 1)]
                assert module.date_range(start, expected[-1]) == expected
                assert module.date_range(start, start) == [start]
                assert module.date_range(start + timedelta(days=1), start) == []
            elif task_id == "hard-dedupe":
                values = rng.sample(range(100, 999), 4)
                assert module.dedupe(
                    [values[2], values[0], values[2], values[1], values[0], values[3]]
                ) == [values[2], values[0], values[1], values[3]]
                left, right = [values[0]], [values[1]]
                assert module.dedupe([left, right, left.copy()]) == [left, right]
            elif task_id == "hard-slugify":
                first = f"Word{rng.randrange(100, 999)}"
                second = f"Next{rng.randrange(100, 999)}"
                assert module.slugify(f"  {first},  {second}!--Done  ") == (
                    f"{first.lower()}-{second.lower()}-done"
                )
                assert module.slugify("___---!!!") == ""
            elif task_id == "hard-titlecase":
                number = rng.randrange(100, 999)
                assert module.titlecase(f"mIxEd{number}\tcase  words") == (
                    f"Mixed{number}\tCase  Words"
                )
                assert module.titlecase("don't stop me now") == "Don't Stop Me Now"
            elif task_id == "hard-truncate":
                text = f"value-{rng.randrange(100_000, 999_999)}"
                limit = 5 + rng.randrange(5)
                assert module.truncate(text, limit) == text[: limit - 3] + "..."
                assert module.truncate(text, 3) == "..."
                assert len(module.truncate(text, 2)) <= 2
                assert module.truncate(text, len(text)) == text
            elif task_id == "money-round":
                whole = rng.randrange(2, 80)
                cents = rng.randrange(10, 90)
                for text in (f"{whole}.{cents:02d}5", f"-{whole}.{cents:02d}5"):
                    amount = float(text)
                    expected = float(
                        Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    )
                    assert module.round_money(amount) == expected
                down = f"{whole}.{cents:02d}4"
                assert module.round_money(float(down)) == float(
                    Decimal(down).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                )
            elif task_id == "retry-backoff":
                failures = 2 + rng.randrange(3)
                calls = []
                result = object()

                def eventual():
                    calls.append(len(calls))
                    if len(calls) <= failures:
                        raise LookupError(f"transient-{len(calls)}")
                    return result

                assert module.retry(eventual, failures + 2) is result
                assert len(calls) == failures + 1
                errors = [RuntimeError(f"failure-{index}") for index in range(failures)]
                attempts = []

                def always_fail():
                    attempts.append(len(attempts))
                    raise errors[len(attempts) - 1]

                try:
                    module.retry(always_fail, failures)
                    raise AssertionError
                except RuntimeError as error:
                    assert error is errors[-1]
                assert len(attempts) == failures
        return {"pass": True, "reason": "passed"}
    except BaseException:
        return {"pass": False, "reason": "adversarial checks failed"}


def hash_report() -> dict[str, str]:
    return {
        "level1_sealed": hashlib.sha256(
            inspect.getsource(level1_sealed).encode()
        ).hexdigest(),
        "level2_adversarial": hashlib.sha256(
            inspect.getsource(level2_adversarial).encode()
        ).hexdigest(),
    }


def _isolated_level(
    level: str, task_id: str, workspace: str, candidate: bytes
) -> dict[str, object]:
    failure_reason = (
        "objective checks failed" if level == "level1" else "adversarial checks failed"
    )
    failed = {"pass": False, "reason": failure_reason}
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": "",
        }
    )
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--level",
                level,
                "--candidate-stdin",
                "--workspace",
                workspace,
                "--task-id",
                task_id,
            ],
            cwd=Path(__file__).resolve().parent,
            env=environment,
            capture_output=True,
            input=base64.b64encode(candidate),
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            return failed
        result = json.loads(completed.stdout.decode("utf-8"))
        if (
            not isinstance(result, dict)
            or set(result) != {"pass", "reason"}
            or not isinstance(result["pass"], bool)
            or result["reason"] not in {"passed", failure_reason}
            or result["pass"] != (result["reason"] == "passed")
        ):
            return failed
        return result
    except Exception:
        return failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hash-report", action="store_true")
    parser.add_argument("--level", choices=("level1", "level2"))
    parser.add_argument("--candidate-stdin", action="store_true")
    parser.add_argument("--workspace")
    parser.add_argument("--task-id")
    args = parser.parse_args()
    if args.hash_report:
        result = hash_report()
    elif args.level and args.workspace and args.task_id:
        source = (
            base64.b64decode(sys.stdin.buffer.read(), validate=True)
            if args.candidate_stdin
            else None
        )
        check = level1_sealed if args.level == "level1" else level2_adversarial
        result = check(args.task_id, args.workspace, source)
    elif args.workspace and args.task_id:
        try:
            candidate = (Path(args.workspace).resolve() / "solution.py").read_bytes()
        except Exception:
            candidate = b""
        level1 = _isolated_level("level1", args.task_id, args.workspace, candidate)
        level2 = _isolated_level("level2", args.task_id, args.workspace, candidate)
        result = {"level1": level1, "level2": level2}
    else:
        parser.error("verification requires --workspace and --task-id")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
