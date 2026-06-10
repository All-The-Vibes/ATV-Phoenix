import re, sys
# Hidden acceptance checker for slugify. Exit 0 = all pass, 1 = any fail.
try:
    from solution import slugify
except Exception as e:
    print(f"IMPORT_FAIL: {e}"); sys.exit(1)

cases = [
    ("Hello World", "hello-world"),
    ("  Leading and trailing  ", "leading-and-trailing"),
    ("Multiple   spaces", "multiple-spaces"),
    ("Special!@#Chars$%^", "specialchars"),
    ("already-slug", "already-slug"),
    ("Mix OF -- Hyphens", "mix-of-hyphens"),
    ("UPPER CASE", "upper-case"),
    ("a---b", "a-b"),
    ("--edge--", "edge"),
    ("CafÃ© 123", "caf-123"),
]
fails = []
for inp, want in cases:
    try:
        got = slugify(inp)
    except Exception as e:
        fails.append((inp, want, f"EXC:{e}")); continue
    if got != want:
        fails.append((inp, want, got))
if fails:
    for f in fails: print("FAIL", f)
    print(f"{len(fails)}/{len(cases)} failed"); sys.exit(1)
print(f"OK {len(cases)}/{len(cases)} passed"); sys.exit(0)
