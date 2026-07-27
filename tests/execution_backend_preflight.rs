//! Execution-backend preflight tests — prove backends refuse fail-closed in preflight,
//! preserve every refusal dimension, and do not contradict that gate when executed directly.

use phoenix::execution_backend::{
    BackendOutcome, BackendStatus, EmptyRefusals, ExecutionBackend, Job, LocalBackend, PreflightDimension,
    PreflightOutcome, PreflightRefusal, Refusals, LOCAL_BACKEND_NAME,
};

fn assert_covers_substantive_dimensions_once(reasons: &[PreflightRefusal]) {
    let expected = [
        PreflightDimension::RepositoryEligibility,
        PreflightDimension::Authentication,
        PreflightDimension::RunnerCompatibility,
        PreflightDimension::TaskConstraints,
    ];

    assert_eq!(
        reasons.len(),
        expected.len(),
        "preflight must report exactly the four substantive dimensions"
    );
    for dimension in expected {
        assert_eq!(
            reasons.iter().filter(|r| r.dimension == dimension).count(),
            1,
            "dimension {:?} must appear exactly once in {:?}",
            dimension,
            reasons
        );
    }
}

#[test]
fn local_preflight_accepts_runnable_job() {
    let backend = LocalBackend;
    let out = backend.preflight(&Job::new("job-1", "sum 2 and 2"));

    assert!(
        out.is_eligible(),
        "local preflight should accept a non-empty task"
    );
    assert!(
        out.reasons().is_empty(),
        "eligible preflight must not carry refusal reasons"
    );
}

#[test]
fn local_preflight_refuses_empty_task_with_reason() {
    let backend = LocalBackend;
    let out = backend.preflight(&Job::new("job-2", "   "));

    assert!(!out.is_eligible(), "blank tasks are not runnable");
    assert_eq!(out.reasons().len(), 1);
    assert_eq!(
        out.reasons()[0].dimension,
        PreflightDimension::TaskConstraints
    );
    assert!(
        out.reasons()[0].reason.contains("empty task"),
        "refusal must state the reason, got {:?}",
        out.reasons()[0].reason
    );
}

#[test]
fn preflight_reports_all_simultaneous_failures() {
    struct AuditedBackend;

    impl ExecutionBackend for AuditedBackend {
        fn name(&self) -> &str {
            "audited"
        }

        fn preflight(&self, job: &Job) -> PreflightOutcome {
            let mut reasons = vec![
                PreflightRefusal::new(
                    PreflightDimension::RepositoryEligibility,
                    "repository is private",
                ),
                PreflightRefusal::new(PreflightDimension::Authentication, "missing token"),
                PreflightRefusal::new(
                    PreflightDimension::RunnerCompatibility,
                    "runner lacks label",
                ),
            ];

            if job.task.trim().is_empty() {
                reasons.push(PreflightRefusal::new(
                    PreflightDimension::TaskConstraints,
                    "empty task",
                ));
            }

            PreflightOutcome::try_ineligible(reasons).expect("test backend always supplies reasons")
        }

        fn execute(&self, job: &Job) -> BackendOutcome {
            BackendOutcome::failed(&job.id, self.name(), "not runnable")
        }
    }

    let out = AuditedBackend.preflight(&Job::new("job-many", "   "));

    assert!(!out.is_eligible());
    assert_covers_substantive_dimensions_once(out.reasons());
}

#[test]
fn trait_default_preflight_refuses_fail_closed() {
    struct MinimalBackend;

    impl ExecutionBackend for MinimalBackend {
        fn name(&self) -> &str {
            "minimal"
        }

        fn execute(&self, job: &Job) -> BackendOutcome {
            BackendOutcome::failed(&job.id, self.name(), "not implemented")
        }
    }

    let out = MinimalBackend.preflight(&Job::new("job-3", "work"));

    assert!(
        !out.is_eligible(),
        "default preflight must not silently allow dispatch"
    );
    assert_covers_substantive_dimensions_once(out.reasons());
    assert!(out
        .reasons()
        .iter()
        .all(|r| r.reason.contains("cannot vouch")));
}

#[test]
fn refusal_sets_cannot_be_empty() {
    assert_eq!(
        Refusals::try_new(Vec::<PreflightRefusal>::new()),
        Err(EmptyRefusals),
        "a reasonless refusal set must be rejected instead of fabricated"
    );

    let reason = PreflightRefusal::new(PreflightDimension::TaskConstraints, "empty task");
    let out = PreflightOutcome::try_ineligible(vec![reason.clone()])
        .expect("one explicit reason is a valid refusal set");

    assert!(!out.is_eligible());
    assert_eq!(out.reasons(), &[reason]);
    // `PreflightOutcome::Ineligible` takes `Refusals`, whose vector field is private; callers
    // cannot write or drain an empty ineligible state by construction.
}

#[test]
fn empty_refusals_is_human_readable_and_error_propagatable() {
    fn build_refusals() -> Result<Refusals, Box<dyn std::error::Error>> {
        Ok(Refusals::try_new(Vec::<PreflightRefusal>::new())?)
    }

    let err = build_refusals().expect_err("empty refusal sets must remain fallible");
    assert_eq!(
        EmptyRefusals.to_string(),
        "empty refusal set rejected: a refusal with no reason is a fail-open shape"
    );
    assert_eq!(err.to_string(), EmptyRefusals.to_string());
}

#[test]
fn crate_root_reexports_preflight_contract_types() {
    let _: phoenix::PreflightOutcome = phoenix::PreflightOutcome::eligible();
    let _: phoenix::PreflightDimension = phoenix::PreflightDimension::TaskConstraints;
    let _: phoenix::PreflightRefusal =
        phoenix::PreflightRefusal::new(phoenix::PreflightDimension::TaskConstraints, "reason");
    let _: Result<phoenix::Refusals, phoenix::EmptyRefusals> =
        phoenix::Refusals::try_new(Vec::<phoenix::PreflightRefusal>::new());
}

#[test]
fn local_refused_preflight_never_executes_as_completed() {
    let backend = LocalBackend;
    let job = Job::new("job-4", "");

    assert!(!backend.preflight(&job).is_eligible());
    let out = backend.execute(&job);
    assert_ne!(
        out.status,
        BackendStatus::Completed,
        "execute must not complete a job preflight refused"
    );
}

#[test]
fn preflight_is_usable_behind_trait_object() {
    let backend: &dyn ExecutionBackend = &LocalBackend;
    let out = backend.preflight(&Job::new("job-5", "via trait object"));

    assert_eq!(backend.name(), LOCAL_BACKEND_NAME);
    assert!(out.is_eligible(), "preflight must preserve object safety");
}
