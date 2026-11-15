import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import threading
import urllib.request
import urllib.error
from unittest.mock import patch

from devflight import Queue, Trace
from devflight.collector import make_server, otlp_identity
from devflight.core import atomic_json
from devflight.integrations import configure, report
from devflight.rawtree import sync
from start_devflight import codex_overrides
from start_devflight import remote_status


class ReliabilityTests(unittest.TestCase):
    @unittest.skipUnless(os.name=="nt","Windows transient file sharing")
    def test_atomic_replace_retries_transient_windows_permission_error(self):
        with tempfile.TemporaryDirectory() as home:
            path=Path(home)/'state.json'
            replace=os.replace
            calls=[]
            def transient(source,destination):
                calls.append(1)
                if len(calls)==1: raise PermissionError('temporarily held by scanner')
                return replace(source,destination)
            with patch('devflight.core.os.replace',side_effect=transient): atomic_json(path,{'confirmed':True})
            self.assertEqual(json.loads(path.read_text()),{'confirmed':True})
            self.assertEqual(len(calls),2)
    def test_malformed_otlp_and_gzip_are_rejected_without_persistence(self):
        with tempfile.TemporaryDirectory() as home:
            queue = Queue(home)
            server = make_server(queue, 0)
            runner = threading.Thread(target=server.serve_forever, daemon=True)
            runner.start()
            try:
                cases = [(b"not gzip", {"Content-Encoding": "gzip"}),
                         (b'{"resourceLogs":[7]}', {}),
                         (b'{"resourceLogs":[{"scopeLogs":[{"logRecords":[null]}]}]}', {}),
                         (b'{"resourceLogs":' + b'[' * 1500 + b']' * 1500 + b'}', {})]
                for raw, extra in cases:
                    request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/v1/logs", data=raw,
                        headers={"Content-Type": "application/json", **extra})
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(request, timeout=5)
                    self.assertEqual(error.exception.code, 400)
                self.assertEqual(queue.events(), [])
            finally:
                server.shutdown()
                server.server_close()
                runner.join(5)

    def test_enterprise_sink_authenticates_before_accepting_otlp(self):
        class Store:
            def __init__(self): self.accepted = []
            def authenticate(self, token, purpose):
                if token != "trusted-ingest-key" or purpose != "ingest": raise PermissionError()
                return {"org_id": "trusted-org", "user_id": "trusted-user"}
            def ingest_otlp(self, identity, signal, body):
                self.accepted.append((identity, signal, body))
        with tempfile.TemporaryDirectory() as home:
            queue = Queue(home)
            store = Store()
            server = make_server(queue, 0, enterprise_store=store)
            runner = threading.Thread(target=server.serve_forever, daemon=True)
            runner.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/v1/logs"
                body = b'{"org_id":"attacker-org","resourceLogs":[]}'
                for token in (None, "wrong"):
                    headers = {"Content-Type": "application/json"}
                    if token: headers["Authorization"] = "Bearer " + token
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=5)
                    self.assertEqual(error.exception.code, 401)
                request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer trusted-ingest-key"})
                with urllib.request.urlopen(request, timeout=5) as response: self.assertEqual(response.status, 200)
                self.assertEqual(len(store.accepted), 1)
                self.assertEqual(store.accepted[0][0]["org_id"], "trusted-org")
                self.assertEqual(queue.events(), [])
            finally:
                server.shutdown()
                server.server_close()
                runner.join(5)

    def test_otlp_record_identities_and_resource_conflicts(self):
        def attrs(**pairs):
            return {"attributes": [{"key": key, "value": {"stringValue": value}} for key, value in pairs.items()]}
        body = {"resourceLogs": [{
            "resource": attrs(**{"session.id": "resource-session", "service.name": "agent-service"}),
            "scopeLogs": [{"logRecords": [attrs(**{
                "conversation.id": "record-session", "gen_ai.provider.name": "provider-emitted",
                "model": "actual-model", "developer_id": "developer-emitted"})]}],
        }]}
        identity = otlp_identity(body, "resourceLogs")
        self.assertNotIn("session.id", identity)
        self.assertEqual(identity["gen_ai.system"], "provider-emitted")
        self.assertEqual(identity["gen_ai.request.model"], "actual-model")
        self.assertEqual(identity["developer.id"], "developer-emitted")

    def test_otlp_span_and_metric_identities_ignore_unrelated_payloads(self):
        attribute = {"key": "session.id", "value": {"stringValue": "explicit-session"}}
        span = {"attributes": [attribute]}
        self.assertEqual(otlp_identity({"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}, "resourceSpans")["session.id"], "explicit-session")
        metric = {"sum": {"dataPoints": [{"attributes": [attribute]}]},
                  "unrelated": {"attributes": [{"key": "session.id", "value": {"stringValue": "not-an-identity"}}]}}
        identity = otlp_identity({"resourceMetrics": [{"scopeMetrics": [{"metrics": [metric]}]}]}, "resourceMetrics")
        self.assertEqual(identity["session.id"], "explicit-session")
        nested = {"key": "model", "value": {"kvlistValue": {"values": [attribute]}}}
        self.assertEqual(otlp_identity({"resourceLogs": [{"scopeLogs": [{"logRecords": [{"attributes": [nested]}]}]}]}, "resourceLogs"), {})

    def test_legacy_noncontiguous_manifest_does_not_skip_events(self):
        class Remote:
            def __init__(self): self.ids = set()
            def insert(self, table, rows, token):
                if table == "dev_events_raw": self.ids.update(e["event_id"] for e in rows)
        with tempfile.TemporaryDirectory() as home:
            queue = Queue(home)
            trace = Trace(queue)
            rows = [trace.emit("artifact.created"), trace.emit("error"), trace.emit("artifact.created")]
            atomic_json(queue.home / "batch.json", {"table": "dev_artifacts_raw", "events": [rows[0], rows[2]], "deduplication_id": "old-token"})
            remote = Remote()
            sync(queue, remote, attempts=1)
            self.assertEqual(remote.ids, {e["event_id"] for e in rows})
            self.assertEqual(queue.state()["acked_sequence"], 3)
            self.assertEqual(queue.status()["pending"], 0)

    def test_partial_otlp_failure_keeps_manifest_and_unacked_event(self):
        class Remote:
            def request(self, *args): return {"partialSuccess": {"rejectedSpans": "1"}}
        with tempfile.TemporaryDirectory() as home:
            queue = Queue(home)
            Trace(queue).emit("otel.traces", {"resourceSpans": []})
            with self.assertRaises(RuntimeError): sync(queue, Remote(), attempts=1)
            self.assertTrue((queue.home / "batch.json").exists())
            self.assertEqual(queue.status()["pending"], 1)

    def test_empty_control_key_cannot_disable_authentication(self):
        with tempfile.TemporaryDirectory() as home:
            queue = Queue(home)
            (queue.home / "control.key").write_text("")
            with self.assertRaises(ValueError): make_server(queue, 0)

    def test_essential_explicitly_disables_inherited_traces(self):
        with patch.dict(os.environ, {"DEVFLIGHT_CAPTURE_PROFILE": "essential"}):
            self.assertIn("otel.trace_exporter='none'", codex_overrides(8787))
        with patch.dict(os.environ, {"DEVFLIGHT_CAPTURE_PROFILE": "detailed"}):
            self.assertTrue(any("trace_exporter={" in value for value in codex_overrides(8787)))

    def test_configuration_preview_never_prints_existing_secrets(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / ".gemini" / "settings.json"
            path.parent.mkdir()
            original = '{"privateCredential":"do-not-display"}'
            path.write_text(original)
            output = io.StringIO()
            with patch("devflight.integrations.Path.home", return_value=Path(home)), patch("builtins.input", return_value="NO"), contextlib.redirect_stdout(output):
                self.assertFalse(configure("gemini_cli")["changed"])
            self.assertNotIn("do-not-display", output.getvalue())
            self.assertEqual(path.read_text(), original)

    def test_integration_endpoint_requires_exact_loopback_host(self):
        with tempfile.TemporaryDirectory() as home:
            with patch("devflight.integrations.Path.home", return_value=Path(home)), patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:8787.attacker.example"}):
                self.assertFalse(report()["claude_code"]["configured"])

    def test_cached_writer_recovers_checkpoint_after_another_writer_crash(self):
        with tempfile.TemporaryDirectory() as home:
            queue = Queue(home)
            first = Trace(queue).emit("tool.result")
            second = Trace(Queue(home)).emit("tool.result")
            atomic_json(queue.home / "sequence.json", {"sequence": first["sequence"]})
            third = Trace(queue).emit("tool.result")
            self.assertEqual((first["sequence"], second["sequence"], third["sequence"]), (1, 2, 3))

    def test_opt_in_storage_cap_preserves_confirmed_events(self):
        with tempfile.TemporaryDirectory() as home:
            queue = Queue(home)
            event = Trace(queue).emit("tool.result")
            with patch.dict(os.environ, {"DEVFLIGHT_MAX_QUEUE_BYTES": str(queue.disk_bytes())}):
                with self.assertRaises(OSError): Trace(queue).emit("error")
            self.assertEqual(queue.events(), [event])

    def test_real_collector_shutdown_restart_preserves_queue(self):
        from devflight import collector
        with tempfile.TemporaryDirectory() as home:
            for cycle in range(2):
                ready = threading.Event()
                holder = {}
                def factory(queue, port):
                    holder["server"] = make_server(queue, 0)
                    ready.set()
                    return holder["server"]
                with patch.object(collector, "make_server", side_effect=factory), patch.dict(os.environ, {"DEVFLIGHT_OFFLINE": "1"}):
                    runner = threading.Thread(target=collector.serve, args=(Queue(home), 0, .05), daemon=True)
                    runner.start()
                    self.assertTrue(ready.wait(5))
                    base = f"http://127.0.0.1:{holder['server'].server_port}"
                    try:
                        if cycle == 0:
                            request = urllib.request.Request(base + "/events", data=b'{"event_type":"tool.result"}', headers={"Content-Type": "application/json"})
                            with urllib.request.urlopen(request, timeout=5) as response: self.assertEqual(response.status, 201)
                        with urllib.request.urlopen(base + "/health", timeout=5) as response:
                            self.assertEqual(json.load(response)["total"], 1)
                        key = (Path(home) / "control.key").read_text()
                        request = urllib.request.Request(base + "/shutdown", data=b"", headers={"X-DevFlight-Control": key})
                        with urllib.request.urlopen(request, timeout=5) as response: self.assertEqual(response.status, 200)
                        runner.join(5)
                        self.assertFalse(runner.is_alive())
                    finally:
                        if runner.is_alive(): holder["server"].shutdown()
                        runner.join(5)
            self.assertEqual(Queue(home).status()["pending"], 1)

    def test_native_remote_activity_uses_signal_timestamps(self):
        class Remote:
            def __init__(self): self.queries = []
            def query(self, sql):
                self.queries.append(sql)
                if "dev_metrics" in sql and "recent_rows" in sql: raise ValueError("Unknown identifier timeUnixNano")
                return [{"total_rows": 9}] if "total_rows" in sql else [{"recent_rows": 0}]
        remote = Remote()
        output = io.StringIO()
        with patch("devflight.rawtree.RawTree", return_value=remote), patch.dict(os.environ, {"RAWTREE_READ_KEY": "unit-test-only"}), contextlib.redirect_stdout(output):
            remote_status()
        self.assertIn("startTimeUnixNano", next(q for q in remote.queries if "dev_traces" in q))
        self.assertIn("timeUnixNano", next(q for q in remote.queries if "dev_logs" in q))
        self.assertIn("9 total rows; recent activity unavailable", output.getvalue())


if __name__ == "__main__": unittest.main()
