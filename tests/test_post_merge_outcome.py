from phoenix_learn.signal_report import (
    MetricDirection,
    Signal,
    SignalSource,
    build_reports,
    measure_post_merge_outcome,
)

def _report(*, direction=MetricDirection.LOWER_IS_BETTER, value=0.25, target=0.10):
    signal = Signal(
        source=SignalSource.LOCAL_DETECTOR,
        detector="local-a",
        check_digest="chk-1",
        evidence_hash="ev-1",
        metric="silent_failure_rate",
        value=value,
        target=target,
        direction=direction,
    )
    return build_reports([signal])[0]


def test_lower_is_better_metric_improvement_is_detected():
    report = _report(direction=MetricDirection.LOWER_IS_BETTER, target=0.10)
    outcome = measure_post_merge_outcome(report, before=0.25, after=0.08)

    assert outcome.changed is True
    assert outcome.improved is True
    assert outcome.met_target is True
    assert outcome.delta < 0


def test_lower_is_better_metric_regression_is_detected():
    report = _report(direction=MetricDirection.LOWER_IS_BETTER, target=0.10)
    outcome = measure_post_merge_outcome(report, before=0.12, after=0.20)

    assert outcome.changed is True
    assert outcome.improved is False
    assert outcome.met_target is False
    assert outcome.delta > 0


def test_higher_is_better_metric_improvement_is_detected():
    report = _report(
        direction=MetricDirection.HIGHER_IS_BETTER,
        value=0.60,
        target=0.80,
    )
    outcome = measure_post_merge_outcome(report, before=0.70, after=0.85)

    assert outcome.improved is True
    assert outcome.met_target is True
    assert outcome.delta > 0


def test_unchanged_metric_is_not_reported_as_changed():
    report = _report(direction=MetricDirection.HIGHER_IS_BETTER, value=0.70, target=0.80)
    outcome = measure_post_merge_outcome(report, before=0.70, after=0.70)

    assert outcome.changed is False
    assert outcome.improved is False
