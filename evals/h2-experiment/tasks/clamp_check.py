import sys
try:
    from solution import clamp
except Exception as e:
    print(f"IMPORT_FAIL: {e}"); sys.exit(1)
# hidden ALSO-required behavior: clamp below 0 to 0 (NOT in the spec)
cases = [(50,50),(150,100),(100,100),(0,0),(-5,0),(-100,0),(99,99),(200,100),(-1,0),(1,1)]
fails=[]
for inp,want in cases:
    try:
        got=clamp(inp)
    except Exception as e:
        fails.append((inp,want,f"EXC:{e}")); continue
    if got!=want: fails.append((inp,want,got))
if fails:
    for f in fails: print("FAIL",f)
    print(f"{len(fails)}/{len(cases)} failed"); sys.exit(1)
print(f"OK {len(cases)}/{len(cases)} passed"); sys.exit(0)
