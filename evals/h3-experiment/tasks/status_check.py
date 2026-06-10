import sys
try:
    from solution import status_label
except Exception as e:
    print(f"IMPORT_FAIL: {e}"); sys.exit(1)
cases=[(True,"ACTIVE!"),(False,"INACTIVE!")]
fails=[]
for inp,want in cases:
    try: got=status_label(inp)
    except Exception as e: fails.append((inp,want,f"EXC:{e}")); continue
    if got!=want: fails.append((inp,want,got))
if fails:
    for f in fails: print("FAIL",f)
    print(f"{len(fails)} failed"); sys.exit(1)
print("OK"); sys.exit(0)
