import gzip
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch
from devflight import Queue, Trace
from devflight.adapters import import_record
from devflight.collector import make_server

class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.queue=Queue(self.tmp.name)

    def test_context_inheritance(self):
        with patch.dict(os.environ,{"DEVFLIGHT_DEVELOPER_ID":"etna","DEVFLIGHT_SESSION_ID":"session-test"}):
            parent=Trace(self.queue)
        with parent.child("worker") as child: event=child.emit("tool.result",{"value":3})
        self.assertEqual(event["developer_id"],"etna")
        self.assertEqual(event["session_id"],"session-test")
        self.assertEqual(event["parent_span_id"],parent.span_id)

    def test_provider_usage_and_source_session(self):
        trace=Trace(self.queue)
        import_record(trace,"codex",{"type":"thread.started","thread_id":"real-provider-id"})
        event=import_record(trace,"codex",{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20,"cached_input_tokens":40}})
        self.assertEqual(event["session_id"],"real-provider-id")
        self.assertEqual(event["data"]["usage"]["cached_input_tokens"],40)
        self.assertIsNone(event["data"]["usage"]["cost_usd"])
        record={"type":"assistant","session_id":"claude-session","message":{"model":"provider-model","content":[],"usage":{"input_tokens":5}}}
        self.assertEqual(import_record(trace,"claude",record)["model"],"provider-model")
        event=import_record(trace,"claude",{"type":"result","session_id":"claude-session","usage":{"input_tokens":10},"total_cost_usd":.1})
        self.assertEqual(event["data"]["usage"]["scope"],"session")
        self.assertEqual(sum(e["event_type"]=="llm.usage" for e in self.queue.events()),2)

    def test_collector_preserves_otlp_and_identity(self):
        server=make_server(self.queue,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        def post(path,payload,compressed=False):
            raw=json.dumps(payload).encode();headers={"Content-Type":"application/json"}
            if compressed:raw=gzip.compress(raw);headers["Content-Encoding"]="gzip"
            req=urllib.request.Request(f"http://127.0.0.1:{server.server_port}"+path,data=raw,headers=headers)
            with urllib.request.urlopen(req) as response:return json.load(response)
        post("/events",{"event_type":"tool.result","developer_id":"guillem","session_id":"s1","agent":{"id":"codex","model":"model-x"},"data":{"value":[1,2]}})
        data={"resourceSpans":[{"resource":{"attributes":[{"key":"developer_id","value":{"stringValue":"etna"}}]},"scopeSpans":[]}]}
        post("/v1/traces",data,True)
        rows=self.queue.events()
        self.assertEqual(rows[0]["developer_id"],"guillem")
        self.assertEqual(rows[0]["model"],"model-x")
        self.assertEqual(rows[1]["data"],data)

if __name__=="__main__":unittest.main()
