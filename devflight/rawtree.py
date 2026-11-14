"""RawTree HTTP API; durable batch identities survive ambiguous timeouts."""
import hashlib
import json
import os
import time
import datetime as dt
import urllib.parse
import urllib.request
from .core import atomic_json, file_lock, redact

class RawTree:
    def __init__(self, read_only=False):
        self.key = os.getenv("RAWTREE_READ_KEY" if read_only else "RAWTREE_API_KEY")
        if not self.key:
            raise ValueError("Configure RAWTREE_READ_KEY" if read_only else "Configure RAWTREE_API_KEY")
        self.base = os.getenv("RAWTREE_BASE_URL", "https://api.rawtree.com").rstrip("/")
        self.database = os.getenv("RAWTREE_DATABASE", "datathon_mathops")
        self.read_only = read_only

    def request(self, path, payload, params=None, headers=None):
        query = urllib.parse.urlencode({"database": self.database, **(params or {})})
        req = urllib.request.Request(self.base + path + "?" + query,
            data=json.dumps(payload, ensure_ascii=False).encode(), headers={
                "Authorization": "Bearer " + self.key, "Content-Type": "application/json",
                "x-rawtree-database": self.database, **(headers or {})})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    def insert(self, table, events, token):
        if self.read_only:
            raise PermissionError("Read-only analyst client")
        # RawTree's dynamic JSON may reformat timestamps and omit null-valued paths.
        # Keep a lossless serialization alongside SQL-queryable original fields.
        clean = [redact(e) for e in events]
        wire = [{**e, "event_json": json.dumps(e, ensure_ascii=False, allow_nan=False)} for e in clean]
        result = self.request("/v1/tables/" + table, wire,
            {"deduplicate_insert": "enable", "insert_deduplication_token": token})
        count = result.get("written_rows", result.get("inserted"))
        if count is None or int(count) != len(events):
            raise RuntimeError("Unconfirmed batch: " + str(result))

    def query(self, sql):
        if not sql.lstrip().upper().startswith("SELECT "):
            raise ValueError("Only SELECT is allowed by the analyst")
        return self.request("/v1/query", {"sql": sql})["data"]

    def evaluations(self):
        sql = "SELECT event_json AS event FROM dev_events_raw WHERE event_type = 'eval.grade' ORDER BY timestamp, event_id LIMIT 100000"
        return [json.loads(r["event"]) for r in self.query(sql)], sql

def sync(queue, client=None, attempts=3):
    if os.getenv("DEVFLIGHT_OFFLINE") == "1":
        return {**queue.status(), "offline": True}
    client = client or RawTree()
    with file_lock(queue.home / "sync.lock"):
        state = queue.state()
        rows_snapshot = queue.events()
        if "acked_sequence" not in state:
            legacy = set(state.get("acked", []))
            cursor = 0
            for event in rows_snapshot:
                if event["sequence"] != cursor + 1 or event["event_id"] not in legacy:
                    break
                cursor = event["sequence"]
            state["acked_sequence"] = cursor
            state["acked"] = list(legacy - {e["event_id"] for e in rows_snapshot if e["sequence"] <= cursor})
        manifest = queue.home / "batch.json"
        while True:
            if manifest.exists():
                batch = json.loads(manifest.read_text(encoding="utf-8"))
            else:
                acked = set(state.get("acked", []))
                pending = [e for e in rows_snapshot if e["sequence"] > state["acked_sequence"] and e["event_id"] not in acked]
                if not pending:
                    break
                artifact = pending[0]["event_type"].startswith("artifact.")
                rows = []
                for event in pending:
                    if event["event_type"].startswith("artifact.") != artifact or len(rows) == 100:
                        break
                    rows.append(event)
                table = "dev_artifacts_raw" if artifact else "dev_events_raw"
                token = hashlib.sha256((table + ":" + ":".join(e["event_id"] for e in rows)).encode()).hexdigest()
                batch = {"table": table, "events": rows, "deduplication_id": token}
                atomic_json(manifest, batch)
            for attempt in range(attempts):
                try:
                    # OTLP is already represented by native signal tables. Keep its
                    # lossless envelope in the durable local queue, not a second table.
                    ordinary = [e for e in batch["events"] if not e["event_type"].startswith("otel.")]
                    if ordinary:
                        client.insert("dev_events_raw", ordinary, batch["deduplication_id"] + "-events")
                    if batch["table"] == "dev_artifacts_raw":
                        client.insert("dev_artifacts_raw", batch["events"], batch["deduplication_id"] + "-artifacts")
                    for event in batch["events"]:
                        if event["event_type"].startswith("otel."):
                            signal = event["event_type"].split(".")[1]
                            # Retries of the same OTLP payload share a remote identity,
                            # including after a collector restart or exporter reconnect.
                            payload_token = hashlib.sha256(
                                json.dumps(event["data"], sort_keys=True, ensure_ascii=False,
                                           separators=(",", ":")).encode("utf-8")
                            ).hexdigest()
                            result = client.request("/otlp/v1/" + signal, event["data"],
                                {"deduplicate_insert": "enable", "insert_deduplication_token": payload_token},
                                {"x-rawtree-" + signal + "-table": "dev_" + signal})
                            if any(int(v) for k,v in result.get("partialSuccess", {}).items() if k.startswith("rejected")):
                                raise RuntimeError("OTLP partial rejection")
                    break
                except Exception as error:
                    state["last_error"] = redact(str(error))
                    state["retries"] = state.get("retries", 0) + 1
                    atomic_json(queue.home / "sync.json", state)
                    if attempt + 1 == attempts:
                        raise
                    time.sleep(min(2 ** attempt, 8))
            state["acked_sequence"] = max(state["acked_sequence"], max(e["sequence"] for e in batch["events"]))
            state["acked"] = [identifier for identifier in state.get("acked", [])
                              if identifier not in {e["event_id"] for e in batch["events"]}]
            state["last_error"] = None
            state["last_sync"] = dt.datetime.now(dt.timezone.utc).isoformat()
            state["batches_sent"] = state.get("batches_sent", 0) + 1
            atomic_json(queue.home / "sync.json", state)
            manifest.unlink()
    return queue.status()
