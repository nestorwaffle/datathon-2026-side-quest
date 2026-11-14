"""Evaluate predictions, including breakdowns by language, topic and difficulty."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from collections import defaultdict
from devflight import Trace

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True); p.add_argument("--predictions",required=True)
    p.add_argument("--recipe",default="baseline"); p.add_argument("--tokens",type=int,required=True)
    p.add_argument("--recipe-config",required=True)
    args=p.parse_args()
    problems=[json.loads(l) for l in Path(args.input).read_text(encoding="utf-8").splitlines() if l.strip()]
    with open(args.predictions,encoding="utf-8") as f: predictions={r["id"]:r for r in csv.DictReader(f)}
    groups=defaultdict(list); elapsed=0
    for problem in problems:
        prediction=predictions.get(str(problem["id"]),{})
        correct=prediction.get("status")=="ok" and prediction.get("answer")==problem["label"]
        groups["all"].append(correct); elapsed+=float(prediction.get("seconds",0))
        for field in ("language","topic","difficulty"):
            groups[field+":"+str(problem.get(field,"unknown"))].append(correct)
    report={key:{"accuracy":sum(v)/len(v),"count":len(v)} for key,v in groups.items()}
    if not problems: raise ValueError("Empty evaluation set")
    Trace(agent="evaluator",kind="m3kang_eval").emit("eval.grade",{
        "recipe":args.recipe,"recipe_config":json.loads(Path(args.recipe_config).read_text()),
        "dataset":hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),"split":"validation",
        "success":all(groups["all"]),"accuracy":report["all"]["accuracy"],"seconds":elapsed,
        "tokens":args.tokens,"breakdown":report})
    print(json.dumps(report,indent=2))

if __name__=="__main__": main()
