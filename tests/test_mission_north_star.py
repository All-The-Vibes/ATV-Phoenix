import re
from pathlib import Path


MISSION = Path(__file__).parent.parent / "MISSION.md"


def active_mission() -> str:
    raw = MISSION.read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", raw, flags=re.S)


def test_dark_factory_headings_and_conjunctive_rule():
    text = active_mission()
    assert re.search(r"^## North star: the AI-native dark factory[ \t]*$", text, re.M)
    assert re.search(r"^## Mission criteria — all gates must be green[ \t]*$", text, re.M)
    assert re.search(r"^### Metric definitions[ \t]*$", text, re.M)
    assert "A failed gate cannot be averaged away." in text
    assert "steer by intent and monitor by exception" in text


def test_every_north_star_gate_has_its_full_safety_contract():
    text = active_mission()
    criteria = [
        "| **Intent steering** | Every mission becomes a runnable acceptance contract and bounded work graph before mutation; operators specify outcomes and constraints, not task-by-task instructions. |",
        "| **Autonomous initiation** | At least 90% of all items eligible during the measurement window are autonomously started within the configured start SLA; items never started count against the rate. |",
        "| **Durable fleet execution** | Isolated, idempotent jobs survive retries and restarts without duplicate shipping or workspace collisions; concurrency can scale from tens toward thousands without changing the control model. |",
        "| **Verified outcomes** | 100% of outcomes marked done or shipped have a currently-green `phoenix_accept` failure-first proof bound to the exact check and commit, plus an intact trace. |",
        "| **Bounded recovery** | At least 95% of recoverable RED states heal within the bounded retry/rollback policy; exhausted cases become explicit exceptions, never silent success. |",
        "| **Policy-gated shipping** | Eligible low-risk changes can merge automatically after objective test, review, security, cost, and blast-radius gates; risky or ambiguous changes enter a human exception lane. |",
        "| **Compounding learning** | Verified outcomes enter retrievable memory automatically; skill or policy changes adopt only on sealed, measured gains with zero right-to-wrong regression. |",
        "| **Economic control** | Every mission has model-routing and spend limits; no runaway compute; cost, latency, and tokens per verified outcome stay within budget and trend down without quality regression. |",
        "| **Exception operations** | Human intervention is required for no more than 10% of eligible outcomes, excluding changed intent or policy; routine status stays silent and alerts carry one concrete decision or recovery action. |",
    ]
    for criterion in criteria:
        assert criterion in text


def test_metrics_include_complete_populations_and_denominators():
    text = active_mission()
    required = [
        "all items that were eligible at any point during the measurement window",
        "Items never started count against the rate.",
        "proven done-or-shipped outcomes divided by all outcomes marked done or shipped",
        "At least 95% of terminal work items",
        "The denominator is every item entering a terminal state during the measurement window",
        "divided by all RED states classified as recoverable",
        "divided by all eligible outcomes reaching a terminal state",
    ]
    for clause in required:
        assert clause in text
    assert "an item without a matching acceptance proof cannot enter either state" in text


def test_trigger_plane_and_subordinate_benchmark_contract():
    text = active_mission()
    assert "Scout heartbeat and scheduled or condition-triggered automations form the trigger plane" in text
    assert "persistent job ledger, work keys, leases, and restart-safe checkpoints" in text
    assert "Code-quality benchmarks are subordinate evidence" in text
