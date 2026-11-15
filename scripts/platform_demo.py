"""End-to-end demo for the user to run against their configured services.

--live starts one real, bounded Helmcode investigation and polls its durable job.
The default replays verified audit history without a new inference. Optionally
--followup-view saves the proposed monitoring view and verifies its current query.
No fixture or synthetic provider activity is generated.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from devflight.development import Development
from devflight.rawtree import RawTree
from devflight.analytics import literal

ACTIVE = {"queued", "running", "cancelling"}


def wait_for_job(client, job_id, timeout):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        response = client.get("/api/investigations/"+job_id,
                              timeout=max(.1, min(10, deadline-time.monotonic())))
        response.raise_for_status()
        record = response.json()
        if record.get("status") not in ACTIVE:
            return record
        time.sleep(min(.5, max(0, deadline-time.monotonic())))
    # Do not repeat the POST or leave a newly queued inference unacknowledged.
    try:
        client.post("/api/investigations/"+job_id+"/cancel", json={}, timeout=5).raise_for_status()
    except Exception as error:
        print("Cancellation could not be confirmed: "+type(error).__name__, file=sys.stderr)
    raise TimeoutError("Investigation polling expired. Inspect job "+job_id+" in the dashboard; no inference was retried.")


def wait_for_remote_row(sql, timeout=45):
    """A successful local insert is not proof of remote visibility."""
    deadline = time.monotonic()+timeout
    remote = RawTree(read_only=True)
    last_error = None
    while time.monotonic() < deadline:
        try:
            # The platform's independent uploader drains the durable outbox.
            # Poll reads only, so an upload lock cannot overrun this deadline.
            rows = remote.query(sql, deadline=deadline)
            count = int(rows[0]["rows"]) if rows else 0
            if count > 1:
                raise AssertionError("The exact event ID appears more than once in RawTree")
            if count == 1:
                return count
        except AssertionError:
            raise
        except Exception as error:
            # Error bodies may contain credentials or payloads; show only types.
            last_error = type(error).__name__
        time.sleep(min(.5, max(0, deadline-time.monotonic())))
    raise TimeoutError("Remote ID visibility was not confirmed"+(" ("+last_error+")" if last_error else ""))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Run one new Helmcode investigation")
    parser.add_argument("--scope", choices=("workspace", "organization"), default="workspace",
                        help="Explicit analytical scope; workspace includes all emitters in the configured source")
    parser.add_argument("--hours", type=int, default=24, help="Time window; 0 means all available history")
    parser.add_argument("--timeout", type=float, default=180, help="Maximum job polling time, 10..600 seconds")
    parser.add_argument("--request-id", help="Reuse only to retrieve the same already-submitted investigation")
    parser.add_argument("--followup-view", action="store_true", help="Save and verify a follow-up monitoring view")
    args = parser.parse_args()
    if not 0 <= args.hours <= 87600:
        parser.error("--hours must be 0..87600")
    if not 10 <= args.timeout <= 600:
        parser.error("--timeout must be 10..600")
    subprocess.run([sys.executable, str(ROOT/"start_platform.py"), "start"], cwd=ROOT, check=True, timeout=40)
    import httpx
    development = Development()
    started = time.perf_counter()
    task = subprocess.run([sys.executable, "-m", "compileall", "-q", "devflight"], cwd=ROOT, timeout=60)
    event = development.record("demo-real-source-compilation", (time.perf_counter()-started)*1000,
        "ok" if task.returncode == 0 else "error", "CompilationFailure" if task.returncode else None)
    scope = {"source_scope": args.scope, "hours": args.hours}
    with httpx.Client(base_url="http://127.0.0.1:8788", timeout=15, trust_env=False) as client:
        token = (development.store.home/"admin.token").read_text().strip()
        response = client.post("/api/login", json={"token": token})
        response.raise_for_status()
        actor = response.json()
        source = client.get("/api/source")
        source.raise_for_status()
        if args.scope == "workspace" and not source.json().get("can_read_global"):
            raise PermissionError("The signed-in user has no shared-source grant; select an authorized scope explicitly")
        sql = "SELECT count() AS rows FROM dev_platform_events WHERE org_id="+literal(actor["org_id"])+" AND event_id="+literal(event["event_id"])
        count = wait_for_remote_row(sql)
        response = client.get("/api/sessions/"+development.run["run_id"], params={
            "source_scope": args.scope, "hours": 0, "event_id": event["event_id"]})
        response.raise_for_status()
        if not any(row.get("event_id") == event["event_id"] for row in response.json()["items"]):
            raise AssertionError("Dashboard API did not expose the exact persisted event")
        if args.live:
            question = (
                "Investiga la actividad del alcance seleccionado, incluyendo todos sus usuarios y agentes. "
                "Consulta errores y sesiones, indica qué datos faltan y propone una verificación concreta. "
                "La ejecución de desarrollo "+development.run["run_id"]+
                " acaba de compilar el código; úsala como referencia, sin restringir todo el análisis a ella. Máximo dos consultas.")
            request_id = args.request_id or str(uuid.uuid4())
            response = client.post("/api/investigations", json={
                "question": question, "scope": scope, "request_id": request_id})
            response.raise_for_status()
            if response.status_code != 202:
                raise RuntimeError("Expected the asynchronous investigation API (HTTP 202)")
            accepted = response.json()
            investigation = wait_for_job(client, accepted["id"], args.timeout)
            if investigation.get("status") != "completed":
                raise RuntimeError("Investigation "+investigation["id"]+" ended as "+str(investigation.get("status"))+"; partial evidence remains in the dashboard")
            if investigation.get("mode") != "live":
                raise AssertionError("This demonstration requires actual configured provider inference")
            if not any(evidence.get("status") == "ok" for evidence in investigation.get("evidence", [])):
                raise AssertionError("No successful analytical tool evidence was retained")
        else:
            response = client.get("/api/investigations")
            response.raise_for_status()
            candidates = [row for row in response.json()["items"]
                if row.get("status") == "completed" and row.get("query_count", 0) > 0
                and row.get("mode") in (None, "live")]
            if not candidates:
                raise RuntimeError("No verified investigation exists; use --live to run Helmcode")
            investigation = candidates[0]
        audit_sql = "SELECT count() AS rows FROM dev_investigations WHERE org_id="+literal(actor["org_id"])+" AND event_id="+literal(investigation["id"])
        wait_for_remote_row(audit_sql)
        action = None
        if args.followup_view:
            if investigation.get("read_only"):
                raise ValueError("Historical investigation is read-only; use --live --followup-view for a new verified action")
            response = client.post("/api/investigations/"+investigation["id"]+"/followup-view", json={}, timeout=45)
            response.raise_for_status()
            action = response.json()
            if action.get("status") != "verified":
                raise RuntimeError("The follow-up view was not verified; inspect its recorded action")
        print(json.dumps({"verified": True, "development_run": development.run["run_id"],
            "event_id": event["event_id"], "remote_rows": count, "dashboard_contains_exact_event": True,
            "investigation_id": investigation["id"], "conversation_id": investigation.get("conversation_id"),
            "scope": investigation.get("scope"), "requested_demo_scope": scope,
            "mode": "new-live-helmcode-investigation" if args.live else "verified-history-replay-no-new-inference",
            "tool_queries": investigation["query_count"], "reported_usage": investigation.get("usage"),
            "followup_action": action, "dashboard": "http://127.0.0.1:8788"}, ensure_ascii=False))
    return task.returncode


if __name__ == "__main__":
    raise SystemExit(main())
