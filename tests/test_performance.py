import concurrent.futures
import json
import tempfile
import threading
import unittest
import urllib.request

from devflight import Queue
from devflight.collector import make_server
from devflight.rawtree import sync


class PerformanceRegressionTests(unittest.TestCase):
    def test_five_concurrent_agents_durable(self):
        with tempfile.TemporaryDirectory() as home:
            queue = Queue(home)
            server = make_server(queue, 0)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                def send(agent):
                    for number in range(20):
                        body = json.dumps({"event_type": "tool.result", "agent": agent,
                                           "session_id": agent, "data": {"number": number}}).encode()
                        request = urllib.request.Request(
                            f"http://127.0.0.1:{server.server_port}/events",
                            data=body, headers={"Content-Type": "application/json"})
                        with urllib.request.urlopen(request, timeout=10) as response:
                            self.assertEqual(response.status, 201)
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                    list(pool.map(send, (f"agent-{i}" for i in range(5))))
                rows = queue.events()
                self.assertEqual(len(rows), 100)
                self.assertEqual(len({r["sequence"] for r in rows}), 100)
                self.assertEqual(len({r["session_id"] for r in rows}), 5)
            finally:
                server.shutdown()
                server.server_close()

    def test_otlp_only_native_remote(self):
        class Remote:
            def __init__(self): self.tables = []; self.signals = []
            def insert(self, table, rows, token): self.tables.append((table, len(rows)))
            def request(self, path, payload, params, headers):
                self.signals.append(path)
                return {}
        with tempfile.TemporaryDirectory() as home:
            from devflight import Trace
            queue = Queue(home)
            Trace(queue).emit("otel.traces", {"resourceSpans": []})
            remote = Remote()
            sync(queue, remote, attempts=1)
            self.assertEqual(remote.tables, [])
            self.assertEqual(remote.signals, ["/otlp/v1/traces"])
            self.assertEqual(queue.status()["pending"], 0)


if __name__ == "__main__":
    unittest.main()
