import sys
# Hidden acceptance checker for roman numerals. Exit 0 = all pass.
try:
    from solution import to_roman
except Exception as e:
    print(f"IMPORT_FAIL: {e}"); sys.exit(1)

cases = [
    (1, "I"), (4, "IV"), (9, "IX"), (14, "XIV"), (40, "XL"),
    (90, "XC"), (400, "CD"), (900, "CM"), (444, "CDXLIV"),
    (1994, "MCMXCIV"), (2023, "MMXXIII"), (3888, "MMMDCCCLXXXVIII"),
    (49, "XLIX"), (3999, "MMMCMXCIX"),
]
fails = []
for inp, want in cases:
    try:
        got = to_roman(inp)
    except Exception as e:
        fails.append((inp, want, f"EXC:{e}")); continue
    if got != want:
        fails.append((inp, want, got))
if fails:
    for f in fails: print("FAIL", f)
    print(f"{len(fails)}/{len(cases)} failed"); sys.exit(1)
print(f"OK {len(cases)}/{len(cases)} passed"); sys.exit(0)
