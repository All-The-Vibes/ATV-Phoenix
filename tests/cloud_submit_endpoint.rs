//! The submit and poll halves of the Copilot agent API are served by DIFFERENT hosts with
//! DIFFERENT path shapes. Verified against the live service on 2026-07-31:
//!
//!   create : POST https://api.githubcopilot.com/agents/swe/v1/jobs/{owner}/{repo}
//!   read   : GET  https://api.github.com/agents/repos/{owner}/{repo}/tasks/{id}
//!
//! The original client used the read host and the read path shape for BOTH, and its hermetic
//! stub tests asserted that wrong path — so the suite was green while every real submit
//! returned 403. A stub answers whatever it is asked; it cannot know the URL is wrong.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::sync::{Arc, Mutex};
use std::thread;

use phoenix::cloud_backend::{CloudClient, HttpCloudClient};
use phoenix::execution_backend::Job;

struct Stub {
    base_url: String,
    path: Arc<Mutex<String>>,
    body: Arc<Mutex<String>>,
    join: thread::JoinHandle<()>,
}

impl Stub {
    fn spawn(status: u16, body: &str) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let base_url = format!("http://{}", listener.local_addr().expect("addr"));
        let path = Arc::new(Mutex::new(String::new()));
        let seen = Arc::clone(&path);
        let body_seen: Arc<Mutex<String>> = Arc::new(Mutex::new(String::new()));
        let body_for_thread = Arc::clone(&body_seen);
        let body = body.to_string();
        let join = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let mut reader = BufReader::new(stream.try_clone().expect("clone"));
            let mut line = String::new();
            reader.read_line(&mut line).expect("request line");
            let mut parts = line.split_whitespace();
            let _method = parts.next().unwrap_or_default();
            *seen.lock().expect("lock") = parts.next().unwrap_or_default().to_string();

            let mut len = 0usize;
            loop {
                let mut h = String::new();
                reader.read_line(&mut h).expect("header");
                if h == "\r\n" || h.is_empty() { break; }
                if let Some((n, v)) = h.split_once(':') {
                    if n.eq_ignore_ascii_case("content-length") {
                        len = v.trim().parse().expect("len");
                    }
                }
            }
            let mut buf = vec![0u8; len];
            if len > 0 { reader.read_exact(&mut buf).expect("body"); }
            *body_for_thread.lock().expect("lock body") = String::from_utf8_lossy(&buf).to_string();
            let response = format!(
                "HTTP/1.1 {status} OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}",
                body.len(), body
            );
            stream.write_all(response.as_bytes()).expect("write");
            stream.flush().expect("flush");
        });
        Self { base_url, path, body: body_seen, join }
    }

    fn finish(self) -> (String, String) {
        self.join.join().expect("join");
        let p = self.path.lock().expect("lock").clone();
        let b = self.body.lock().expect("lock body").clone();
        (p, b)
    }
}

#[test]
fn submit_targets_the_copilot_jobs_path_not_the_rest_tasks_path() {
    let stub = Stub::spawn(201, r#"{"job_id":"task-abc","status":"queued"}"#);
    let client = HttpCloudClient::new(stub.base_url.clone(), "All-The-Vibes", "ATV-Phoenix", "t")
        .expect("client")
        .with_submit_base(stub.base_url.clone());

    let id = client.submit(&Job::new("j1", "do the thing")).expect("submit");
    assert_eq!(id.as_str(), "task-abc");

    let (path, body) = stub.finish();
    assert!(
        body.contains(r#""problem_statement":"do the thing""#),
        "the create payload field is problem_statement, not prompt; got {body}"
    );
    assert!(!body.contains(r#""prompt""#), "sending prompt to the right URL still returns HTTP 400; got {body}");
    assert!(body.contains(r#""event_type""#), "event_type is part of the create payload; got {body}");
    assert_eq!(
        path, "/agents/swe/v1/jobs/All-The-Vibes/ATV-Phoenix",
        "submit must use the Copilot jobs path; the REST tasks path returns 403 in production"
    );
    assert!(
        !path.contains("/agents/repos/"),
        "the REST read path shape must never be used to create a job"
    );
}

/// Both env assertions live in ONE test on purpose. Environment variables are process-global, so
/// two tests mutating them run in parallel threads and race — the first version of this file had
/// exactly that bug and `phoenix-mcp accept` caught it as an intermittent RED after a green sense.
/// Serialising by merging is honest; a `--test-threads=1` flag would only hide the sharp edge.
#[test]
fn from_env_splits_the_write_host_from_the_read_host_and_honours_an_override() {
    std::env::set_var("GITHUB_TOKEN", "t");
    std::env::set_var("GITHUB_REPOSITORY", "All-The-Vibes/ATV-Phoenix");
    std::env::remove_var("GITHUB_API_URL");
    std::env::remove_var("COPILOT_API_URL");

    let shown = format!("{:?}", HttpCloudClient::from_env().expect("from_env"));
    assert!(
        shown.contains("api_base: \"https://api.github.com\""),
        "reads stay on the REST host, got {shown}"
    );
    assert!(
        shown.contains("submit_base: \"https://api.githubcopilot.com\""),
        "writes must go to the Copilot host, got {shown}"
    );
    assert!(shown.contains("<redacted>"), "the token must never be printed");

    std::env::set_var("COPILOT_API_URL", "https://copilot.internal.example/");
    let overridden = format!("{:?}", HttpCloudClient::from_env().expect("from_env override"));
    assert!(
        overridden.contains("submit_base: \"https://copilot.internal.example\""),
        "override must apply and trailing slashes must be trimmed, got {overridden}"
    );
    std::env::remove_var("COPILOT_API_URL");
}
