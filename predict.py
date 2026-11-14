"""Compatible with the organizer's JSONL -> CSV evaluation interface."""
import argparse
import csv
import json
from copilot.pipeline import solve, Index
from devflight import Trace

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input", required=True); p.add_argument("--output", required=True)
    p.add_argument("--backend", choices=["llama","demo","helmcode"], default="llama")
    p.add_argument("--rag", type=int, default=0); p.add_argument("--index")
    p.add_argument("--embedding-url")
    args=p.parse_args()
    index=Index.load(args.index,args.embedding_url) if args.index else Index()
    trace=Trace(agent="predict",kind="m3kang_eval")
    trace.emit("run.started", {"backend":args.backend})
    with open(args.input,encoding="utf-8") as source, open(args.output,"w",newline="",encoding="utf-8") as output:
        writer=csv.DictWriter(output,fieldnames=["id","language","answer","seconds","status"]); writer.writeheader()
        for line in source:
            if not line.strip(): continue
            problem=json.loads(line)
            result=solve(problem,index=index,k=args.rag,backend=args.backend,trace=trace)
            writer.writerow({"id":problem["id"],"language":problem.get("language",""),**{k:result[k] for k in ("answer","seconds","status")}})
    trace.emit("run.finished")

if __name__ == "__main__": main()
