"""Live acceptance probe. Requires write and separate read-only environment keys."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from devflight import Queue,Trace
from devflight.core import restore_artifact
from devflight.rawtree import RawTree,sync

def main():
    p=argparse.ArgumentParser();p.add_argument("--home",default=".devflight/live-probe");args=p.parse_args()
    queue=Queue(args.home);trace=Trace(queue,agent="live-probe")
    for value in (42,"text",True,[1,2],{"nested":"value"}): trace.emit("tool.result",{"value":value})
    trace.emit("llm.request",{"prompt":"synthetic probe","api_key":"test-secret-must-disappear"})
    path=queue.home/"probe.txt";path.write_text("Recover this complete artifact.\n",encoding="utf-8")
    artifact=trace.artifact(path)["artifacts"][0]
    expected=[e for e in queue.events() if e["trace_id"]==trace.trace_id]
    sync(queue)
    client=RawTree(read_only=True)
    sql=f"SELECT event_json AS event FROM dev_events_raw WHERE trace_id = '{trace.trace_id}' ORDER BY sequence"
    actual=[json.loads(r["event"]) for r in client.query(sql)]
    unique={e["event_id"]:e for e in actual}
    assert {e["event_id"]:e for e in expected}==unique,"RawTree round-trip mismatch"
    artifact_sql=f"SELECT event_json AS event FROM dev_artifacts_raw WHERE data.artifact_id = '{artifact}' AND event_json IS NOT NULL ORDER BY sequence"
    artifact_rows=[json.loads(r["event"]) for r in client.query(artifact_sql)]
    assert restore_artifact(artifact_rows,artifact)==path.read_bytes()
    assert "test-secret-must-disappear" not in json.dumps(actual)
    print(json.dumps({"verified":True,"events":len(unique),"trace_id":trace.trace_id,"sql":sql}))

if __name__=="__main__":main()
