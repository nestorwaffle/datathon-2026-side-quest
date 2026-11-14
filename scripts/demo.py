"""Reproducible synthetic telemetry demo; no model or cloud credential required."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from devflight import Trace,Queue
from devflight.analyst import analyze
from copilot.pipeline import solve

def main():
    p=argparse.ArgumentParser();p.add_argument("--home",default=".devflight/demo");args=p.parse_args()
    queue=Queue(args.home)
    trace=Trace(queue,agent="demo-parent",task="fraction-skill",kind="skill_authoring")
    trace.emit("run.started",{"synthetic":True})
    with trace.child("skill-worker") as child:
        child.emit("llm.request",{"prompt":"Create a minimal fraction hint. api_key=synthetic-secret"})
        with child.tool("fraction-check",{"numerators":[1,1],"denominators":[2,4]}) as result:result["sum"]=.75
        child.emit("rag.retrieved",{"hits":[{"id":"demo-fraction","text":"Find a common denominator"}]})
        child.emit("skill.invoked",{"name":"fraction-hint"})
        child.emit("llm.response",{"content":"Can you give the fractions a common denominator?"})
        child.emit("command.finished",{"stdout":"fraction test passed\n","stderr":"","returncode":0})
        path=queue.home/"fraction-skill.txt";path.write_text("Can you give the fractions a common denominator?\n",encoding="utf-8")
        artifact=child.artifact(path,"Solve the whole problem.\n")
        child.emit("eval.grade",{"success":True,"rubric":"does not reveal answer"})
    for value in [42,"text",True,[1,2],{"nested":"value"}]:trace.emit("tool.result",{"value":value})
    trace.emit("run.finished")
    # Synthetic benchmark validates mechanics, not model performance claims.
    for name in ("baseline","minimal-hint"):
        for i in range(3):
            run=Trace(queue,agent="demo-evaluator",kind="skill_authoring")
            run.emit("eval.grade",{"synthetic":True,"recipe":name,"dataset":"synthetic-fractions-v1","split":"validation",
                "recipe_config":{"agent":"skill-worker","model":"demo","prompt":"Use minimal hints","skill":"fraction-hint","tools":["fraction-check"],"budget_tokens":60},
                "success":name=="minimal-hint" or i>0,"seconds":8 if name=="minimal-hint" else 10,"tokens":50 if name=="minimal-hint" else 100})
    decision=analyze(queue,queue.events(),"skill_authoring")
    problem=json.loads(Path("data/demo.jsonl").read_text().splitlines()[0])
    study=solve(problem,mode="study",backend="demo",trace=trace)
    challenge=solve(problem,backend="demo",trace=trace)
    report={"trace_id":trace.trace_id,"artifact_id":artifact["artifacts"][0],"decision":decision,"study":study,"challenge":challenge,"queue":queue.status(),"synthetic":True}
    (queue.home/"demo-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()
