//! Regression test for issue #141: the mission binary must give each goal its own task.
//!
//! Before the fix, `phoenix_mission` wrapped the inner backend in a `FixedTaskBackend` that
//! rewrote every job to one constant `MISSION_TASK`, so all four goals of the diamond DAG ran the
//! identical command. Under `--backend cloud` that same string becomes the problem statement handed
//! to a Copilot coding agent, so a cloud run would start four agents all asked to do the same thing.
//! These tests pin the fix from three angles: the fixed backend is gone (structural), `GOALS`
//! declares four distinct non-empty tasks (structural), and a real run records four different
//! execution details on disk (behavioural).
//!
//! The behavioural check reads each goal's own trace chain
//! (`<workspace>/.phoenix/goal-<id>-trace.jsonl`). `run_mission` appends the backend outcome detail
//! as the `evidence` field of that chain's `execute` row (see `src/mission.rs`), and `LocalBackend`
//! puts the captured `exit=..; stdout=..; stderr=..` of the spawned process into that detail. The
//! run ledger is not usable here: for a successful run it stores no per-goal detail (only a failed
//! run carries `error`), so the goal trace chain is the artifact that actually distinguishes one
//! task from another. Limit: this proves the four recorded outputs differ, not that any specific
//! task string ran; the second test pins the specific task strings in the source.

use std::collections::HashSet;
use std::fs;
use std::process::Command;

use phoenix::trace_chains::MissionChains;

const MISSION_SOURCE: &str = "src/bin/phoenix_mission.rs";
const DIAMOND_GOALS: [&str; 4] = ["a", "b", "c", "d"];

#[test]
fn mission_binary_does_not_reintroduce_a_fixed_task_backend() {
    let source = fs::read_to_string(MISSION_SOURCE).expect("read mission cli source");
    assert!(
        !source.contains("FixedTaskBackend"),
        "issue #141: the binary must not reintroduce FixedTaskBackend. A single fixed-task backend \
         makes every goal run the same task and produces no observable difference under \
         --backend local, which is exactly the defect."
    );
}

#[test]
fn mission_goals_declare_four_distinct_nonempty_tasks() {
    let source = fs::read_to_string(MISSION_SOURCE).expect("read mission cli source");
    let tuples = goals_tuples(&source);
    assert_eq!(tuples.len(), 4, "GOALS must have exactly 4 entries, got {}: {tuples:?}", tuples.len());

    let mut tasks: Vec<String> = Vec::new();
    for tuple in &tuples {
        let fields = split_top_level_commas(strip_outer_parens(tuple));
        let last = fields.last().expect("a GOALS tuple has at least one field");
        assert!(
            unquote(last).is_some(),
            "each GOALS entry must end with a string task literal; entry {tuple:?} ends with \
             {last:?}, so GOALS carries no per-goal task (issue #141)"
        );
        let task = unquote(last).unwrap();
        assert!(!task.trim().is_empty(), "GOALS entry {tuple:?} has an empty task");
        tasks.push(task);
    }

    let distinct: HashSet<&str> = tasks.iter().map(String::as_str).collect();
    assert_eq!(
        distinct.len(),
        4,
        "the four goal tasks must be distinct, not one constant applied to all four; got {tasks:?}"
    );
}

#[test]
fn mission_run_records_four_different_execution_details() {
    let workspace = tempfile::tempdir().expect("tempdir");
    let bin = env!("CARGO_BIN_EXE_phoenix_mission");

    let output = Command::new(bin)
        .arg("--workspace")
        .arg(workspace.path())
        .output()
        .expect("run phoenix_mission");

    assert!(
        output.status.success(),
        "mission cli failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    let chains = MissionChains::in_workspace(workspace.path());
    let mut details: Vec<(String, String)> = Vec::new();
    for goal in DIAMOND_GOALS {
        let events = chains.goal(goal).read_all();
        let exec = events
            .iter()
            .find(|e| e.tool == "execute")
            .unwrap_or_else(|| panic!("goal {goal} chain must record an execute row"));
        details.push((goal.to_string(), exec.evidence.clone()));
    }

    let distinct: HashSet<&str> = details.iter().map(|(_, d)| d.as_str()).collect();
    assert!(
        distinct.len() > 1,
        "issue #141: all four goals recorded identical execution detail, so one task ran four \
         times. details: {details:#?}"
    );
    assert_eq!(
        distinct.len(),
        4,
        "each goal should execute its own distinct task; got {} distinct details across 4 goals: {:#?}",
        distinct.len(),
        details
    );
}

// ── source parsing helpers ──────────────────────────────────────────────────────────────────────

/// Return each top-level `(...)` tuple string inside the `const GOALS = [ ... ];` array value.
fn goals_tuples(source: &str) -> Vec<String> {
    let body = goals_array_body(source);
    split_top_level_commas(&body)
        .into_iter()
        .filter(|f| f.trim_start().starts_with('('))
        .collect()
}

/// The text between the outer `[` and `]` of the GOALS array value (not its type annotation).
fn goals_array_body(source: &str) -> String {
    let decl = source.find("const GOALS").expect("GOALS declaration is present");
    let after_decl = &source[decl..];
    let eq = after_decl.find('=').expect("GOALS has an assignment");
    let value = &after_decl[eq + 1..];
    let open = value.find('[').expect("GOALS value is an array literal");
    let chars: Vec<char> = value[open..].chars().collect();

    let mut depth = 0i32;
    let mut in_str = false;
    let mut escaped = false;
    for (i, &ch) in chars.iter().enumerate() {
        if in_str {
            if escaped {
                escaped = false;
            } else if ch == '\\' {
                escaped = true;
            } else if ch == '"' {
                in_str = false;
            }
            continue;
        }
        match ch {
            '"' => in_str = true,
            '[' => depth += 1,
            ']' => {
                depth -= 1;
                if depth == 0 {
                    return chars[1..i].iter().collect();
                }
            }
            _ => {}
        }
    }
    panic!("GOALS array literal is not closed");
}

/// Split on commas that sit at bracket/paren depth 0 and outside string literals.
fn split_top_level_commas(s: &str) -> Vec<String> {
    let mut fields = Vec::new();
    let mut cur = String::new();
    let mut depth = 0i32;
    let mut in_str = false;
    let mut escaped = false;
    for ch in s.chars() {
        if in_str {
            cur.push(ch);
            if escaped {
                escaped = false;
            } else if ch == '\\' {
                escaped = true;
            } else if ch == '"' {
                in_str = false;
            }
            continue;
        }
        match ch {
            '"' => {
                in_str = true;
                cur.push(ch);
            }
            '(' | '[' => {
                depth += 1;
                cur.push(ch);
            }
            ')' | ']' => {
                depth -= 1;
                cur.push(ch);
            }
            ',' if depth == 0 => {
                let trimmed = cur.trim().to_string();
                if !trimmed.is_empty() {
                    fields.push(trimmed);
                }
                cur.clear();
            }
            _ => cur.push(ch),
        }
    }
    let trimmed = cur.trim().to_string();
    if !trimmed.is_empty() {
        fields.push(trimmed);
    }
    fields
}

/// Strip one balanced pair of outer parentheses from a tuple string.
fn strip_outer_parens(tuple: &str) -> &str {
    let t = tuple.trim();
    t.strip_prefix('(')
        .and_then(|inner| inner.strip_suffix(')'))
        .map(str::trim)
        .unwrap_or(t)
}

/// If `field` is a `"..."` string literal, return its inner text; otherwise `None`.
fn unquote(field: &str) -> Option<String> {
    let f = field.trim();
    let inner = f.strip_prefix('"')?.strip_suffix('"')?;
    Some(inner.to_string())
}
