from phoenix_learn.signal_report import (
    MetricDirection,
    Signal,
    SignalSource,
    adoption_allowed,
    build_reports,
    propose_issue_from_report,
)


def _signal(
    *,
    source=SignalSource.LOCAL_DETECTOR,
    detector="local-a",
    check_digest="chk-1",
    evidence_hash="ev-1",
    metric="silent_failure_rate",
    value=0.22,
    target=0.10,
    direction=MetricDirection.LOWER_IS_BETTER,
):
    return Signal(
        source=source,
        detector=detector,
        check_digest=check_digest,
        evidence_hash=evidence_hash,
        metric=metric,
        value=value,
        target=target,
        direction=direction,
    )


def test_signal_round_trips_through_json():
    original = _signal(source=SignalSource.POSTHOG_SCOUT, detector="posthog", value=0.31)
    assert Signal.from_json(original.to_json()) == original


def test_repeated_signals_deduplicate_into_one_report_by_check_and_evidence():
    signals = [
        _signal(source=SignalSource.LOCAL_DETECTOR, detector="local-a", value=0.30),
        _signal(source=SignalSource.POSTHOG_SCOUT, detector="scout-1", value=0.28),
        _signal(check_digest="chk-2", evidence_hash="ev-2", value=0.07),
    ]

    reports = build_reports(signals)
    assert len(reports) == 2

    deduped = reports[0]
    assert deduped.check_digest == "chk-1"
    assert deduped.evidence_hash == "ev-1"
    assert deduped.signal_count == 2
    assert deduped.detectors == ("local-a", "scout-1")
    assert deduped.actionable is True


def test_actionable_report_can_become_a_bounded_proposed_issue():
    report = build_reports([_signal(value=0.50)])[0]
    proposal = propose_issue_from_report(report)

    assert proposal is not None
    assert proposal.state == "proposed"
    assert proposal.blast_radius_max_files == 3
    assert "learning" in proposal.title


def test_non_actionable_report_does_not_create_a_proposed_issue():
    report = build_reports([_signal(value=0.05)])[0]
    assert report.actionable is False
    assert propose_issue_from_report(report) is None


def test_skill_model_and_routing_changes_require_adopt_eligible_gate():
    for change_type in ("skill", "model", "routing"):
        assert not adoption_allowed(change_type, "REJECT")
        assert adoption_allowed(change_type, "ADOPT_ELIGIBLE")
    assert adoption_allowed("docs", "REJECT")
