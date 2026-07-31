use phoenix::execution_backend::{BackendStatus, ExecutionBackend, Job, LocalBackend, PreflightDimension};

#[test]
fn local_backend_executes_a_real_process_and_captures_output() {
    let backend = LocalBackend;
    let out = backend.execute(&Job::new("job-ok", "rustc --version"));

    assert_eq!(out.status, BackendStatus::Completed);
    assert!(out.is_completed());
    assert_eq!(out.job_id, "job-ok");
    assert_eq!(out.backend, "local");
    assert!(
        out.detail.contains("exit=0"),
        "completed run must capture exit status, got {:?}",
        out.detail
    );
    assert!(
        out.detail.contains("stdout=") && out.detail.contains("rustc"),
        "completed run must capture stdout, got {:?}",
        out.detail
    );
}

#[test]
fn local_backend_maps_non_zero_exit_to_failed_without_dropping_output() {
    let backend = LocalBackend;
    let out = backend.execute(&Job::new("job-fail", "rustc --definitely-not-a-real-flag"));

    assert_eq!(out.status, BackendStatus::Failed);
    assert!(!out.is_completed());
    assert!(
        out.detail.contains("exit="),
        "failed run must include exit status, got {:?}",
        out.detail
    );
    assert!(
        out.detail.contains("stderr=") && out.detail.contains("definitely-not-a-real-flag"),
        "failed run must keep captured process output, got {:?}",
        out.detail
    );
}

#[test]
fn local_backend_keeps_empty_task_refusal_before_spawning() {
    let backend = LocalBackend;
    let job = Job::new("job-empty", "   ");

    let preflight = backend.preflight(&job);
    assert!(!preflight.is_eligible());
    assert_eq!(preflight.reasons().len(), 1);
    assert_eq!(preflight.reasons()[0].dimension, PreflightDimension::TaskConstraints);
    assert!(preflight.reasons()[0].reason.contains("empty task"));

    let out = backend.execute(&job);
    assert_eq!(out.status, BackendStatus::Failed);
    assert!(out.detail.contains("empty task"));
}
