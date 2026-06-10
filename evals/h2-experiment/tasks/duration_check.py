import sys
# Hidden acceptance checker for format_duration. Exit 0 = all pass.
try:
    from solution import format_duration
except Exception as e:
    print(f"IMPORT_FAIL: {e}"); sys.exit(1)

cases = [
    (0, "0s"),
    (5, "5s"),
    (60, "1m"),
    (61, "1m 1s"),
    (3600, "1h"),
    (3661, "1h 1m 1s"),
    (3600 + 5, "1h 5s"),       # omit zero minutes
    (7200 + 30, "2h 30s"),
    (120, "2m"),
    (3725, "1h 2m 5s"),
]
fails = []
for inp, want in cases:
    try:
        got = format_duration(inp)
    except Exception as e:
        fails.append((inp, want, f"EXC:{e}")); continue
    if got != want:
        fails.append((inp, want, got))
if fails:
    for f in fails: print("FAIL", f)
    print(f"{len(fails)}/{len(cases)} failed"); sys.exit(1)
print(f"OK {len(cases)}/{len(cases)} passed"); sys.exit(0)
