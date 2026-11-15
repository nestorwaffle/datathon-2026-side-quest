"""Explicit one-event SDK integration probe; not discovered by unittest.

No model inference. Default is local only; --remote opts into one RawTree insert
and a read-back. Probe history persists under tmp/devflight-sdk-probe.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from devflight import Queue
from devflight.collector import make_server
from devflight.rawtree import RawTree, sync


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", action="store_true")
    args = parser.parse_args()
    queue = Queue(ROOT / "tmp" / "devflight-sdk-probe")
    rows = queue.events()
    if not rows:
        server = make_server(queue, 0)
        runner = threading.Thread(target=server.serve_forever, daemon=True)
        runner.start()
        try:
            started = time.perf_counter()
            result = sum(value * value for value in range(1, 11))
            duration = time.perf_counter() - started
            body = {"event_type": "tool.result", "agent": {"id": "python-sdk-validation", "framework": "python"},
                    "session_id": "devflight-local-sdk-probe", "developer_id": "validation",
                    "data": {"name": "sum_squares", "result": result, "seconds": duration,
                             "validation": True, "model_inference": False, "workload": "actual_python_calculation"}}
            headers = {"Content-Type": "application/json"}
            if os.getenv("DEVFLIGHT_HTTP_TOKEN"):
                headers["Authorization"] = "Bearer " + os.environ["DEVFLIGHT_HTTP_TOKEN"]
            request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/events",
                                             data=json.dumps(body).encode(), headers=headers)
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status != 201:
                    raise RuntimeError("Collector did not confirm the event")
        finally:
            server.shutdown()
            server.server_close()
            runner.join(5)
        rows = queue.events()
    if len(rows) != 1 or rows[0]["data"]["result"] != 385:
        raise RuntimeError("Unexpected probe history; refusing remote upload")
    output = {"kind": "actual deterministic Python SDK task; not Codex inference",
              "local_events": len(rows), "result": rows[0]["data"]["result"], "event_id": rows[0]["event_id"]}
    if args.remote:
        sync(queue, attempts=1)
        identifier = rows[0]["event_id"]
        import uuid
        uuid.UUID(identifier)
        result = RawTree(read_only=True).query(
            f"SELECT count() AS matching_rows FROM dev_events_raw WHERE event_id = '{identifier}'")
        output["remote"] = result
        output["pending"] = queue.status()["pending"]
        if not result or int(result[0].get("matching_rows", 0)) != 1:
            raise RuntimeError("Remote read-back did not confirm exactly one row")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
