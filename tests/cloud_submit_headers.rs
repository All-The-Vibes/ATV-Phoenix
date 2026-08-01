//! The Copilot CAPI host is not the REST API and does not accept its headers.
//!
//! Verified against the live service on 2026-08-01. With `X-GitHub-Api-Version` and
//! `Accept: application/vnd.github+json`, a correctly-addressed, correctly-shaped create request
//! still returns **HTTP 400**. Sending the header set the official client uses returns a real
//! `job_id` and starts a real cloud agent. The URL and the body were necessary but not sufficient.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::sync::{Arc, Mutex};
use std::thread;

use phoenix::cloud_backend::{CloudClient, HttpCloudClient};
use phoenix::execution_backend::Job;

fn capture(status: u16, body: &str) -> (String, Arc<Mutex<HashMap<String, String>>>, thread::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
    let base = format!("http://{}", listener.local_addr().expect("addr"));
    let headers: Arc<Mutex<HashMap<String, String>>> = Arc::new(Mutex::new(HashMap::new()));
    let seen = Arc::clone(&headers);
    let body = body.to_string();
    let join = thread::spawn(move || {
        let (mut stream, _) = listener.accept().expect("accept");
        let mut reader = BufReader::new(stream.try_clone().expect("clone"));
        let mut line = String::new();
        reader.read_line(&mut line).expect("request line");
        let mut len = 0usize;
        loop {
            let mut h = String::new();
            reader.read_line(&mut h).expect("header");
            if h == "\r\n" || h.is_empty() { break; }
            if let Some((n, v)) = h.split_once(':') {
                let name = n.trim().to_ascii_lowercase();
                let value = v.trim().to_string();
                if name == "content-length" { len = value.parse().unwrap_or(0); }
                seen.lock().expect("lock").insert(name, value);
            }
        }
        let mut buf = vec![0u8; len];
        if len > 0 { reader.read_exact(&mut buf).expect("body"); }
        let response = format!(
            "HTTP/1.1 {status} OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}",
            body.len(), body);
        stream.write_all(response.as_bytes()).expect("write");
        stream.flush().expect("flush");
    });
    (base, headers, join)
}

#[test]
fn submit_must_not_send_the_rest_api_version_header() {
    let (base, headers, join) = capture(201, r#"{"job_id":"j-1"}"#);
    let client = HttpCloudClient::new(base.clone(), "o", "r", "t")
        .expect("client")
        .with_submit_base(base);
    client.submit(&Job::new("j", "task")).expect("submit");
    join.join().expect("join");

    let h = headers.lock().expect("lock");
    assert!(
        !h.contains_key("x-github-api-version"),
        "the CAPI host returns HTTP 400 when the REST version header is present; got {:?}",
        h.keys().collect::<Vec<_>>()
    );
}

#[test]
fn submit_sends_the_preview_accept_types_the_service_requires() {
    let (base, headers, join) = capture(201, r#"{"job_id":"j-1"}"#);
    let client = HttpCloudClient::new(base.clone(), "o", "r", "t")
        .expect("client")
        .with_submit_base(base);
    client.submit(&Job::new("j", "task")).expect("submit");
    join.join().expect("join");

    let h = headers.lock().expect("lock");
    let accept = h.get("accept").cloned().unwrap_or_default();
    assert!(accept.contains("nebula-preview"), "accept was {accept}");
    assert!(accept.contains("merge-info-preview"), "accept was {accept}");
    assert_eq!(h.get("content-type").map(String::as_str), Some("application/json"));
    let auth = h.get("authorization").cloned().unwrap_or_default();
    assert!(auth.starts_with("Bearer "), "authorization must be a bearer token");
}

#[test]
fn reads_keep_the_rest_headers_because_they_go_to_the_rest_host() {
    let (base, headers, join) = capture(200, r#"{"state":"queued"}"#);
    let client = HttpCloudClient::new(base, "o", "r", "t").expect("client");
    let _ = client.poll(&phoenix::cloud_backend::TaskId::new("t-1"));
    join.join().expect("join");

    let h = headers.lock().expect("lock");
    assert!(
        h.contains_key("x-github-api-version"),
        "the REST read path still versions its requests; got {:?}",
        h.keys().collect::<Vec<_>>()
    );
}
