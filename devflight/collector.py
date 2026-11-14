"""Telemetry-only receiver. No model, UI, evaluation or analyst dependencies."""
import gzip
import hmac
import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .core import Trace, redact, atomic_json
from .rawtree import sync

LIMIT = 4 * 1024 * 1024

def make_server(queue, port=8787):
    slots = threading.BoundedSemaphore(32)
    control_path = queue.home / "control.key"
    if control_path.exists():
        control_key = control_path.read_text(encoding="ascii").strip()
    else:
        control_key = secrets.token_hex(32)
        try:
            with control_path.open("x", encoding="ascii") as stream:
                stream.write(control_key)
        except FileExistsError:
            control_key = control_path.read_text(encoding="ascii").strip()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def reply(self, status, body):
            raw = json.dumps(redact(body), ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers(); self.wfile.write(raw)

        def authorized(self):
            host = self.headers.get("Host", "")
            if host not in (f"localhost:{self.server.server_port}", f"127.0.0.1:{self.server.server_port}"):
                return False
            if self.headers.get("Origin", "http://" + host) != "http://" + host: return False
            token = os.getenv("DEVFLIGHT_HTTP_TOKEN")
            return not token or hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self):
            if not self.authorized(): return self.reply(403, {"error": "Forbidden"})
            if self.path in ("/", "/health", "/status"):
                return self.reply(200, {"service": "devflight-collector", **queue.status()})
            self.reply(404, {"error": "Not found"})

        def do_POST(self):
            if not self.authorized(): return self.reply(403, {"error": "Forbidden"})
            if self.path == "/shutdown":
                if not hmac.compare_digest(self.headers.get("X-DevFlight-Control", ""), control_key):
                    return self.reply(403, {"error": "Forbidden"})
                self.reply(200, {"stopping": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if not slots.acquire(blocking=False):
                self.send_response(503)
                self.send_header("Retry-After", "1")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                self.connection.settimeout(15)
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self.reply(415, {"error": "Use OTLP HTTP JSON, not protobuf/gRPC"})
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= LIMIT: return self.reply(413, {"error": "Body exceeds 4 MiB"})
                raw = self.rfile.read(length)
                if len(raw) != length: raise ValueError("Incomplete body")
                encoding = self.headers.get("Content-Encoding", "identity")
                if encoding == "gzip":
                    import io
                    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f: raw = f.read(LIMIT + 1)
                elif encoding != "identity": return self.reply(415, {"error": "Unsupported content encoding"})
                if len(raw) > LIMIT: return self.reply(413, {"error": "Decompressed body exceeds 4 MiB"})
                body = json.loads(raw)
                if not isinstance(body, dict): raise ValueError("Expected an object")
                trace = Trace(queue, agent="otlp" if self.path.startswith("/v1/") else "http")
                if self.path == "/events":
                    context = body.get("context", {})
                    for name, size in (("trace_id", 32), ("span_id", 16), ("parent_span_id", 16)):
                        if name in context:
                            if not isinstance(context[name], str) or not re.fullmatch("[a-fA-F0-9]{"+str(size)+"}", context[name]):
                                raise ValueError("Invalid " + name)
                            setattr(trace, name, context[name])
                    for name in ("developer_id", "session_id"):
                        value = body.get(name)
                        if value is not None:
                            if not isinstance(value,str) or not 0 < len(value) <= 256: raise ValueError("Invalid " + name)
                            setattr(trace,name,value)
                    agent = body.get("agent", "http")
                    if isinstance(agent,str): trace.agent["id"] = agent
                    elif isinstance(agent,dict):
                        for key in ("id","model","framework"):
                            if isinstance(agent.get(key),str): trace.agent[key]=agent[key]
                    event = trace.emit(body["event_type"], body.get("data",{}))
                    return self.reply(201, {"event_id":event["event_id"]})
                signal = self.path.rsplit("/",1)[-1]
                field = {"traces":"resourceSpans", "logs":"resourceLogs", "metrics":"resourceMetrics"}.get(signal)
                if self.path != "/v1/" + signal or field is None: return self.reply(404,{"error":"Not found"})
                if not isinstance(body.get(field),list): raise ValueError("Missing " + field)
                # Preserve original resource attributes: a batch may contain multiple developers/sessions.
                trace.agent["framework"] = "opentelemetry"
                trace.emit("otel."+signal,body)
                self.reply(200,{})
            except (ValueError, TypeError, KeyError, OSError) as error:
                self.reply(400,{"error":str(error)})
            finally:
                slots.release()
    return ThreadingHTTPServer(("127.0.0.1",port),Handler)

def serve(queue, port=8787, interval=5):
    if interval <= 0: raise ValueError("interval must be positive")
    stopped = threading.Event()
    def upload():
        while not stopped.is_set():
            try:
                if queue.has_pending(): sync(queue)
            except Exception as error:
                # The queue remains intact; a separate status file avoids racing sync state.
                atomic_json(queue.home / "collector-status.json", {"error": str(error)})
            stopped.wait(interval)
    server = make_server(queue,port)
    worker = threading.Thread(target=upload,daemon=True); worker.start()
    print(f"DevFlight collector http://127.0.0.1:{server.server_port}; sync every {interval}s",flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        stopped.set(); server.server_close(); worker.join(timeout=2)
