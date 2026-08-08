//! Live check of [`HttpCloudClient`] against the real GitHub Copilot Agent Tasks API.
//!
//! Done-check: `cargo test --locked --test cloud_live -- --ignored`
//!
//! Every other cloud test drives a stub server, which proves the client is self-consistent but not
//! that the real service agrees with it: a wrong host, a rejected header set, or a response shape
//! that drifted would pass the stubs and fail in production. These tests close that gap.
//!
//! **They are `#[ignore]` by default** and additionally skip themselves when credentials are
//! absent, so neither CI nor a normal `cargo test` reaches the network.
//!
//! Scope is deliberately **read-only**. `submit` creates a real Copilot SWE job — a branch and a
//! pull request on the target repository — which is a side effect on shared infrastructure, not
//! something a test suite should produce as a matter of course. `submit` is covered against the
//! stub server in `cloud_client_http.rs`; what is verified here is that the credentials, hosts,
//! header set, URL shape, and response decoding all hold against production.
//!
//! Run with:
//!   $env:GITHUB_TOKEN = (gh auth token)          # needs the `copilot` scope
//!   $env:GITHUB_REPOSITORY = "owner/repo"
//!   cargo test --test cloud_live -- --ignored --nocapture

use phoenix::cloud_backend::{CloudClient, HttpCloudClient, TaskId, TaskState};

/// Returns the client, or `None` when credentials are absent so the test can skip rather than fail.
fn client_from_env() -> Option<HttpCloudClient> {
    if std::env::var("GITHUB_TOKEN").ok().filter(|t| !t.trim().is_empty()).is_none() {
        eprintln!("skipping: GITHUB_TOKEN not set");
        return None;
    }
    if std::env::var("GITHUB_REPOSITORY").ok().filter(|r| !r.trim().is_empty()).is_none() {
        eprintln!("skipping: GITHUB_REPOSITORY not set");
        return None;
    }
    match HttpCloudClient::from_env() {
        Ok(c) => Some(c),
        Err(e) => panic!("credentials present but client construction failed: {e}"),
    }
}

/// Ask the live API for one existing task id, using the same host the client polls.
fn any_existing_task_id() -> Option<String> {
    let repo = std::env::var("GITHUB_REPOSITORY").ok()?;
    let token = std::env::var("GITHUB_TOKEN").ok()?;
    let base =
        std::env::var("GITHUB_API_URL").unwrap_or_else(|_| "https://api.github.com".to_string());
    let (owner, name) = repo.split_once('/')?;

    let url = format!("{base}/agents/repos/{owner}/{name}/tasks");
    let body: serde_json::Value = ureq::get(&url)
        .set("Accept", "application/vnd.github+json")
        .set("X-GitHub-Api-Version", "2026-03-10")
        .set("User-Agent", "phoenix-cloud-client")
        .set("Authorization", &format!("Bearer {token}"))
        .call()
        .ok()?
        .into_json()
        .ok()?;

    body.get("tasks")?.as_array()?.iter().find_map(|t| {
        t.get("id").and_then(|i| i.as_str()).map(|s| s.to_string())
    })
}

#[test]
#[ignore = "hits the live GitHub Copilot API; run explicitly with --ignored"]
fn poll_decodes_a_real_task_from_the_live_api() {
    let Some(client) = client_from_env() else { return };
    let Some(task_id) = any_existing_task_id() else {
        eprintln!("skipping: the repository has no agent tasks to poll");
        return;
    };

    let state = client
        .poll(&TaskId::new(&task_id))
        .unwrap_or_else(|e| panic!("live poll of task {task_id} failed: {e}"));

    // Any decoded state is a pass: the point is that the real payload maps onto our model without
    // a decode error, and that a terminal task is not mistaken for a pending one.
    match &state {
        TaskState::Pending => eprintln!("task {task_id} is pending"),
        TaskState::Succeeded { branch, report } => {
            eprintln!("task {task_id} succeeded on {branch}, report={report:?}");
            assert!(!branch.trim().is_empty(), "a succeeded task must name its branch");
        }
        TaskState::Failed { reason, report } => {
            eprintln!("task {task_id} failed: {reason}, report={report:?}");
            assert!(!reason.trim().is_empty(), "a failed task must carry a reason");
        }
    }
}

#[test]
#[ignore = "hits the live GitHub Copilot API; run explicitly with --ignored"]
fn an_unknown_task_is_an_error_not_a_silent_pending() {
    // A 404 must surface as a CloudError. Mapping "we could not read it" onto Pending would make a
    // mission wait out its whole poll budget on a task that does not exist.
    let Some(client) = client_from_env() else { return };

    let missing = TaskId::new("00000000-0000-4000-8000-000000000000");
    match client.poll(&missing) {
        Err(e) => eprintln!("unknown task correctly reported as an error: {e}"),
        Ok(state) => panic!("a nonexistent task decoded as {state:?} instead of erroring"),
    }
}

#[test]
#[ignore = "hits the live GitHub Copilot API; run explicitly with --ignored"]
fn bad_credentials_are_reported_rather_than_retried_forever() {
    let Some(repo) = std::env::var("GITHUB_REPOSITORY").ok() else {
        eprintln!("skipping: GITHUB_REPOSITORY not set");
        return;
    };
    let Some((owner, name)) = repo.split_once('/') else {
        panic!("GITHUB_REPOSITORY must be owner/repo");
    };

    let client = HttpCloudClient::new("https://api.github.com", owner, name, "not-a-real-token")
        .expect("client construction only validates shape");

    match client.poll(&TaskId::new("00000000-0000-4000-8000-000000000000")) {
        Err(e) => eprintln!("bad credentials correctly reported: {e}"),
        Ok(state) => panic!("a bad token decoded as {state:?} instead of erroring"),
    }
}
