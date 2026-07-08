import json, sys
from datasets import load_dataset
n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
out = [{"instance_id":r["instance_id"],"repo":r["repo"],"base_commit":r["base_commit"],"problem_statement":r["problem_statement"]} for r in ds.select(range(n))]
json.dump(out, sys.stdout)
print("", file=sys.stderr, flush=True)