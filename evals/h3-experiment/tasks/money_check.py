import sys
try:
    from solution import format_money
except Exception as e:
    print(f"IMPORT_FAIL: {e}"); sys.exit(1)
cases=[(123450,"USD 1,234.50"),(500,"USD 5.00"),(99,"USD 0.99"),(1000000,"USD 10,000.00")]
fails=[]
for inp,want in cases:
    try: got=format_money(inp)
    except Exception as e: fails.append((inp,want,f"EXC:{e}")); continue
    if got!=want: fails.append((inp,want,got))
if fails:
    for f in fails: print("FAIL",f)
    print(f"{len(fails)} failed"); sys.exit(1)
print("OK"); sys.exit(0)
