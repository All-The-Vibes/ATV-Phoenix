import sys
try:
    from solution import user_id
except Exception as e:
    print(f"IMPORT_FAIL: {e}"); sys.exit(1)
cases=[(42,"u-00042"),(7,"u-00007"),(12345,"u-12345"),(1,"u-00001")]
fails=[]
for inp,want in cases:
    try: got=user_id(inp)
    except Exception as e: fails.append((inp,want,f"EXC:{e}")); continue
    if got!=want: fails.append((inp,want,got))
if fails:
    for f in fails: print("FAIL",f)
    print(f"{len(fails)} failed"); sys.exit(1)
print("OK"); sys.exit(0)
