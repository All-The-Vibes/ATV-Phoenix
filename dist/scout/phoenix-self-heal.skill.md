---
name: phoenix-self-heal
description: Self-healing verification for coding tasks. Use the Phoenix CLI to OBJECTIVELY check whether a task actually succeeded (a command's exit code, a file hash, or a regex) and to recover (rollback to a known-good snapshot, or retry) when it failed — instead of self-judging. Trigger whenever you make a code change that has a runnable test/build/lint, or whenever success must be verified rather than assumed.
---

# Phoenix self-heal (Microsoft Scout skill)

You have the ATV-Phoenix self-healing CLI available through the shell. It gives you objective
verification + bounded recovery so you never declare a task done on silently-broken work.

**Binary:** `phoenix-mcp` (set `PHOENIX_WORKSPACE` to the repo root; snapshots + trace live in `.phoenix/`).

## Commands (call via the shell tool; exit code 0 = pass, 1 = fail)
```
phoenix-mcp sense        '<check-json>'            # objective check; exit 0 if ok
phoenix-mcp snapshot     <path> '<check-json>'     # save <path> as good ONLY if the check passes
phoenix-mcp heal         rollback '<ctx-json>'     # restore a blessed snapshot, recheck externally
phoenix-mcp heal         retry    '<ctx-json>'     # re-run a command up to 3x, recheck externally
phoenix-mcp verify-trace                           # audit the tamper-evident trace
```

A `<check-json>` is: `{"kind":"command_exit","target":["pytest","-q"],"expect":0}`
(kinds: `command_exit`, `file_sha256`, `regex_in_file`).

A heal `<ctx-json>` for rollback is:
`{"path":"src/app.py","snap_id":"<from snapshot>","recheck":{"kind":"command_exit","target":["pytest","-q"],"expect":0}}`

## The loop you MUST follow for any change with a checkable outcome
1. `phoenix-mcp sense` the project's test/build command — establish a green baseline.
2. `phoenix-mcp snapshot` the file(s) you will edit (only blesses if green).
3. Make the edit.
4. `phoenix-mcp sense` again. If it exits non-zero, you broke it.
5. `phoenix-mcp heal rollback` (or fix and re-sense). Trust the external recheck, not your judgment.
6. Only report success after `phoenix-mcp sense` exits 0. Show `phoenix-mcp verify-trace` as evidence.

## Honesty
Never claim success you didn't `sense`. "I'm not sure it passed" is acceptable; a fabricated "done"
is exactly the failure mode this skill prevents.
