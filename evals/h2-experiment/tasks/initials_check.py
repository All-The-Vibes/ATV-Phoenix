import sys
try:
    from solution import initials
except Exception as e:
    print(f"IMPORT_FAIL: {e}"); sys.exit(1)
# hidden ALSO-required: uppercase each initial AND put a dot after each (NOT in spec)
cases=[("ada lovelace","A.L."),("grace hopper","G.H."),("alan turing","A.T."),("john von neumann","J.V.N."),("a b","A.B.")]
fails=[]
for inp,want in cases:
    try:
        got=initials(inp)
    except Exception as e:
        fails.append((inp,want,f"EXC:{e}")); continue
    if got!=want: fails.append((inp,want,got))
if fails:
    for f in fails: print("FAIL",f)
    print(f"{len(fails)}/{len(cases)} failed"); sys.exit(1)
print(f"OK {len(cases)}/{len(cases)} passed"); sys.exit(0)
