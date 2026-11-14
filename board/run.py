"""UNO Q Linux side: newline JSON from buttons/serial bridge/stdin, local replies."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from devflight import Queue, Trace
from copilot.pipeline import solve

def main():
    p=argparse.ArgumentParser(); p.add_argument("--demo",action="store_true"); p.add_argument("--policy-pack")
    args=p.parse_args()
    # Board path never imports uploader and never uses cloud credentials.
    os.environ["DEVFLIGHT_OFFLINE"]="1"
    if args.policy_pack:
        pack=json.loads(Path(args.policy_pack).read_text())
        os.environ["DEVFLIGHT_RECIPE"]=json.dumps(pack["recipe"])
    trace=Trace(Queue(os.getenv("BOARD_QUEUE",".devflight/board-private")),agent="uno-q",kind="teaching_eval")
    for line in sys.stdin:
        if not line.strip(): continue
        try:
            request=json.loads(line)
            trace.emit("board.event",request)
            result=solve(request["problem"],mode=request.get("mode","study"),step=request.get("step",""),backend="demo" if args.demo else "llama",trace=trace)
        except Exception as error: result={"status":"error","error":str(error)}
        print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=="__main__": main()
