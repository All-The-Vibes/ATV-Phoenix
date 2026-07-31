use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::sync::{Arc, Mutex};
use std::thread;

use phoenix::cloud_backend::{CloudClient, HttpCloudClient, TaskState};
use phoenix::execution_backend::Job;

#[derive(Debug, Clone)]
struct CapturedRequest {
    method: String,
    path: String,
    authorization: Option<String>,
    body: String,
}

#[derive(Debug, Clone)]
struct PlannedResponse {
    status: u16,
    body: String,
}

struct StubServer {
    base_url: String,
    requests: Arc<Mutex<Vec<CapturedRequest>>>,
    join: thread::JoinHandle<()>,
}

impl StubServer {
    fn spawn(responses: Vec<PlannedResponse>) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind local stub");
        let address = listener.local_addr().expect("local address");
        let base_url = format!("http://{}", address);
        let requests = Arc::new(Mutex::new(Vec::new()));
        let requests_for_thread = Arc::clone(&requests);
        let planned = Arc::new(Mutex::new(VecDeque::from(responses)));
        let planned_for_thread = Arc::clone(&planned);

        let join = thread::spawn(move || {
            while let Some(response) = planned_for_thread.lock().expect("lock responses").pop_front() {
                let (mut stream, _) = listener.accept().expect("accept request");
                let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));

                let mut request_line = String::new();
                reader.read_line(&mut request_line).expect("read request line");
                let mut parts = request_line.split_whitespace();
                let method = parts.next().unwrap_or_default().to_string();
                let path = parts.next().unwrap_or_default().to_string();

                let mut authorization = None;
                let mut content_length = 0usize;
                loop {
                    let mut header_line = String::new();
                    reader.read_line(&mut header_line).expect("read header line");
                    if header_line == "\r\n" || header_line.is_empty() {
                        break;
                    }
                    if let Some((name, value)) = header_line.split_once(':') {
                        let trimmed = value.trim().to_string();
                        if name.eq_ignore_ascii_case("authorization") {
                            authorization = Some(trimmed);
                        } else if name.eq_ignore_ascii_case("content-length") {
                            content_length = trimmed.parse().expect("content-length must be numeric");
                        }
                    }
                }

                let mut body_bytes = vec![0u8; content_length];
                if content_length > 0 {
                    reader.read_exact(&mut body_bytes).expect("read request body");
                }
                let body = String::from_utf8(body_bytes).expect("request body utf8");
                requests_for_thread
                    .lock()
                    .expect("lock requests")
                    .push(CapturedRequest { method, path, authorization, body });

                let payload = response.body;
                let status_text = match response.status {
                    200 => "OK",
                    201 => "Created",
                    401 => "Unauthorized",
                    _ => "Error",
                };
                let wire = format!(
                    "HTTP/1.1 {} {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    response.status,
                    status_text,
                    payload.len(),
                    payload
                );
                stream.write_all(wire.as_bytes()).expect("write response");
            }
        });

        Self { base_url, requests, join }
    }

    fn base_url(&self) -> &str {
        &self.base_url
    }

    fn finish(self) -> Vec<CapturedRequest> {
        let StubServer { requests, join, .. } = self;
        join.join().expect("server thread finished");
        let captured = requests.lock().expect("lock requests").clone();
        captured
    }
}

fn client(base_url: &str) -> HttpCloudClient {
    HttpCloudClient::new(base_url, "All-The-Vibes", "ATV-Phoenix", "test-token")
        .expect("construct http cloud client")
}

#[test]
fn submit_posts_prompt_with_bearer_auth_and_returns_task_id() {
    let server = StubServer::spawn(vec![PlannedResponse {
        status: 201,
        body: r#"{"id":"task-123","state":"queued"}"#.into(),
    }]);
    let task = client(server.base_url())
        .submit(&Job::new("job-1", "fix issue 82"))
        .expect("submit succeeds");

    assert_eq!(task.as_str(), "task-123");
    let requests = server.finish();
    assert_eq!(requests.len(), 1);
    assert_eq!(requests[0].method, "POST");
    assert_eq!(
        requests[0].path,
        "/agents/repos/All-The-Vibes/ATV-Phoenix/tasks"
    );
    let authorization = requests[0].authorization.as_deref().unwrap_or_default();
    assert!(authorization.starts_with("Bearer "));
    assert!(authorization.ends_with("test-token"));
    assert!(requests[0].body.contains(r#""prompt":"fix issue 82""#));
}

#[test]
fn poll_maps_non_terminal_states_to_pending() {
    let server = StubServer::spawn(vec![PlannedResponse {
        status: 200,
        body: r#"{"id":"task-p","state":"in_progress"}"#.into(),
    }]);
    let state = client(server.base_url())
        .poll(&phoenix::cloud_backend::TaskId::new("task-p"))
        .expect("poll succeeds");

    assert!(matches!(state, TaskState::Pending));
    let requests = server.finish();
    assert_eq!(requests[0].method, "GET");
    assert_eq!(
        requests[0].path,
        "/agents/repos/All-The-Vibes/ATV-Phoenix/tasks/task-p"
    );
}

#[test]
fn poll_maps_completed_task_with_branch_and_usage_report() {
    let server = StubServer::spawn(vec![PlannedResponse {
        status: 200,
        body: r#"{
            "id":"task-ok",
            "state":"completed",
            "artifacts":[{"type":"branch","data":{"head_ref":"copilot/issue-82"}}],
            "sessions":[{"model":"gpt-5.3-codex","input_tokens":17,"output_tokens":29,"cost_micros":4100}]
        }"#
        .into(),
    }]);
    let state = client(server.base_url())
        .poll(&phoenix::cloud_backend::TaskId::new("task-ok"))
        .expect("poll succeeds");

    match state {
        TaskState::Succeeded { branch, report } => {
            assert_eq!(branch, "copilot/issue-82");
            assert_eq!(report.model.as_deref(), Some("gpt-5.3-codex"));
            assert_eq!(report.input_tokens, Some(17));
            assert_eq!(report.output_tokens, Some(29));
            assert_eq!(report.cost_micros, Some(4100));
        }
        other => panic!("expected succeeded state, got {other:?}"),
    }
    let _ = server.finish();
}

#[test]
fn poll_maps_failed_task_reason_and_burned_tokens() {
    let server = StubServer::spawn(vec![PlannedResponse {
        status: 200,
        body: r#"{
            "id":"task-fail",
            "state":"failed",
            "error":{"message":"runner out of quota"},
            "sessions":[{"input_tokens":101,"output_tokens":7}]
        }"#
        .into(),
    }]);
    let state = client(server.base_url())
        .poll(&phoenix::cloud_backend::TaskId::new("task-fail"))
        .expect("poll succeeds");

    match state {
        TaskState::Failed { reason, report } => {
            assert_eq!(reason, "runner out of quota");
            assert_eq!(report.input_tokens, Some(101));
            assert_eq!(report.output_tokens, Some(7));
        }
        other => panic!("expected failed state, got {other:?}"),
    }
    let _ = server.finish();
}

#[test]
fn poll_transport_and_http_failures_are_typed_cloud_errors() {
    let closed_listener = TcpListener::bind("127.0.0.1:0").expect("reserve local port");
    let closed_port = closed_listener.local_addr().expect("local addr");
    drop(closed_listener);
    let unreachable_base = format!("http://{}", closed_port);
    let transport_error = client(&unreachable_base)
        .poll(&phoenix::cloud_backend::TaskId::new("task-any"))
        .expect_err("poll must report transport failure");
    assert!(
        transport_error.to_string().contains("poll request failed"),
        "got {:?}",
        transport_error
    );

    let server = StubServer::spawn(vec![PlannedResponse {
        status: 401,
        body: r#"{"message":"Bad credentials"}"#.into(),
    }]);
    let token = "secret-token";
    let auth_client = HttpCloudClient::new(
        server.base_url(),
        "All-The-Vibes",
        "ATV-Phoenix",
        token,
    )
    .expect("construct auth client");
    let http_error = auth_client
        .poll(&phoenix::cloud_backend::TaskId::new("task-nope"))
        .expect_err("poll must report http failure");
    let message = http_error.to_string();
    assert!(message.contains("Bad credentials"));
    assert!(
        !message.contains(token),
        "error messages must never echo credentials"
    );
    let _ = server.finish();
}
