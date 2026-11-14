"""Explicit synthetic transport probe, not a fabricated AI session."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from devflight import Queue, Trace
from devflight.rawtree import sync, RawTree

def main():
    queue=Queue(".devflight/telemetry-probe")
    trace=Trace(queue,agent="transport-probe",task="telemetry-verification",kind="instrumentation")
    trace.developer_id="devflight-test"
    trace.emit("run.started",{"synthetic":True,"purpose":"verify API ingestion"})
    for value in (42,"text",True,[1,2],{"nested":"value"}):
        trace.emit("tool.result",{"synthetic":True,"value":value})
    trace.emit("run.finished",{"synthetic":True})
    sync(queue)
    sql=f"SELECT event_json AS event FROM dev_events_raw WHERE trace_id = '{trace.trace_id}' ORDER BY sequence"
    rows=RawTree(read_only=True).query(sql)
    actual={json.loads(r["event"])["event_id"] for r in rows}
    expected={e["event_id"] for e in queue.events() if e["trace_id"]==trace.trace_id}
    assert actual==expected,"Remote event identity mismatch"
    print(json.dumps({"verified":True,"events":len(actual),"trace_id":trace.trace_id,"sql":sql}))

if __name__=="__main__":main()
