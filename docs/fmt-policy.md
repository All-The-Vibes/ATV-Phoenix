# Formatting Policy: fmt ungated (deliberate hand style)

**Decision (recorded 2026-07-05):** Leave cargo fmt ungated in CI permanently. Option (b) from issue #6.

## Investigation

cargo fmt --check exits 1 against this codebase. Investigated whether a ustfmt.toml could match
the existing hand style without reformatting ~88 source files. Finding: no single configuration achieves
this because the hand style contains intentional inconsistencies that rustfmt cannot reproduce:

- **Single-line macro calls kept long** (up to ~111 chars): e.g. ec!["cmd".into(), ...] on one line.
- **Multi-line macro calls kept split** even when short enough to fit on one line: e.g. println!(...) 
  split at ~106 chars despite fitting a 112-char width threshold.
- **Attribute strings up to 551 chars**: #[tool(description = "...")] kept on one line.

Any max_width that prevents wrapping the single-line calls also causes rustfmt to collapse the
deliberately-split multi-line calls. There is no threshold that preserves both simultaneously.
Option (a) — ustfmt.toml matching hand style — is not achievable without either:
  a. Applying cargo fmt to ~88 files (one-time reformatting accepted as scope expansion), or
  b. Adding per-block #[rustfmt::skip] annotations across many files.

Both exceed the current blast-radius budget per beat.

## Decision

Leave cargo fmt ungated. CI gates on **build** (cargo build) and **tests** (cargo test --locked),
mirroring what ust.yml has always enforced.

## If the policy changes

To adopt fmt gating later: run cargo fmt once across all files with a chosen ustfmt.toml,
accept the reformatting as a single cleanup commit, and add cargo fmt --check to ci-local.sh.
