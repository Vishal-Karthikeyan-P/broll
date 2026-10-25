"""Build HARD_CASES.md from a batch_runner results folder. Run: python scripts/hard_cases_report.py results"""
import json
import os
import sys

root = sys.argv[1] if len(sys.argv) > 1 else "results"
rows = json.load(open(os.path.join(root, "summary.json")))
out = ["# Hard-case results (generated from the batch runner)\n",
       "Footage here is the built-in mock provider, so these results show the *engine's decisions* (queries, flags, "
       "failures), not the quality of real stock footage. Relevance scores with the mock provider are inflated by "
       "construction and must not be quoted as measured relevance.\n",
       "| Input | Result | What the engine did |", "|---|---|---|"]
for r in rows:
    d = os.path.join(root, r["input"].replace(".", "_"))
    note = ""
    if r["status"] == "succeeded":
        tl = json.load(open(os.path.join(d, "timeline.json")))
        mf = json.load(open(os.path.join(d, "manifest.json")))
        bits = []
        for s in tl["scenes"]:
            bits.append(f"“{(s['query_used'] or 'title card')}”" + (f" [{', '.join(s['flags'])}]" if s["flags"] else ""))
        note = "queries: " + "; ".join(bits)
        extra = sorted({w["code"] for w in mf["warnings"]} - {"AVOID_PEOPLE_BEST_EFFORT"})
        if extra:
            note += " · warnings: " + ", ".join(extra)
        res = f"succeeded, QA {'passed' if r['qa_passed'] else 'FAILED'}"
    elif r["status"].startswith("rejected"):
        res, note = f"rejected ({r['status'].split('_')[-1]}) `{r['error_code']}`", "refused up front with a JSON error"
    else:
        res, note = f"failed `{r['error_code']}`", "job failed with a clear, non-retryable error instead of a bad video"
    out.append(f"| {r['input']} | {res} | {note} |")
open("HARD_CASES.md", "w").write("\n".join(out) + "\n")
print("wrote HARD_CASES.md")
