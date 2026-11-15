"""Small end-to-end demonstration. --live spends a bounded Helmcode investigation.

Default replays verified audit evidence and explicitly does not claim new inference.
No fixture or synthetic agent activity is generated.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from devflight.development import Development
from devflight.rawtree import RawTree
from devflight.platform import literal

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--live",action="store_true")
    args=parser.parse_args()
    subprocess.run([sys.executable,str(ROOT/"start_platform.py"),"start"],cwd=ROOT,check=True)
    import httpx
    development=Development()
    started=time.perf_counter()
    # Actually validate the local Python source; record metadata only.
    task=subprocess.run([sys.executable,"-m","compileall","-q","devflight"],cwd=ROOT)
    event=development.record("demo-real-source-compilation",(time.perf_counter()-started)*1000,
                             "ok" if task.returncode==0 else "error","CompilationFailure" if task.returncode else None)
    development.store.sync_once()
    with httpx.Client(base_url="http://127.0.0.1:8788",timeout=100,trust_env=False) as client:
        token=(development.store.home/"admin.token").read_text().strip()
        response=client.post("/api/login",json={"token":token});response.raise_for_status()
        actor=response.json()
        sql="SELECT count() AS rows FROM dev_platform_events WHERE org_id="+literal(actor["org_id"])+" AND event_id="+literal(event["event_id"])
        count=int(RawTree(read_only=True).query(sql)[0]["rows"])
        assert count==1,"Expected one remotely persisted development event"
        response=client.get("/api/sessions/"+development.run["run_id"]);response.raise_for_status()
        assert any(r.get("event_id")==event["event_id"] for r in response.json()["items"]),"Dashboard API did not expose the exact event"
        if args.live:
            question="Investiga la sesión de desarrollo "+development.run["run_id"]+". Consulta sus errores y sesiones, informa incertidumbre y propone una verificación concreta. Máximo dos consultas."
            response=client.post("/api/investigations",json={"question":question});response.raise_for_status()
            investigation=response.json()
            if investigation.get("status")!="completed":raise RuntimeError("Helmcode investigation incomplete: "+investigation.get("status","unknown"))
            assert investigation["query_count"]>0,"No real tools executed"
            development.store.sync_once()
        else:
            response=client.get("/api/investigations");response.raise_for_status()
            candidates=[r for r in response.json()["items"] if r.get("status")=="completed" and r.get("query_count",0)>0]
            if not candidates:raise RuntimeError("No verified investigation exists; use --live to run Helmcode")
            investigation=candidates[0]
        audit_sql="SELECT count() AS rows FROM dev_investigations WHERE org_id="+literal(actor["org_id"])+" AND event_id="+literal(investigation["id"])
        assert int(RawTree(read_only=True).query(audit_sql)[0]["rows"])==1,"Remote investigation audit missing or duplicated"
        print(json.dumps({"verified":True,"development_run":development.run["run_id"],"event_id":event["event_id"],
            "remote_rows":count,"dashboard_contains_exact_event":True,"investigation_id":investigation["id"],
            "mode":"new-live-helmcode-investigation" if args.live else "verified-history-replay-no-new-inference",
            "tool_queries":investigation["query_count"],"reported_usage":investigation.get("usage"),
            "dashboard":"http://127.0.0.1:8788"},ensure_ascii=False))
    return task.returncode

if __name__=="__main__":raise SystemExit(main())
