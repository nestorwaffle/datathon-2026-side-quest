"""Telemetry-only receiver. No model, UI, evaluation or analyst dependencies."""
import gzip
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .core import Trace, redact, atomic_json
from .rawtree import sync

LIMIT = 4 * 1024 * 1024

def validate_otlp(body, field):
    """Validate protocol containers before accepting a durable payload."""
    def objects(value, label):
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ValueError("Invalid OTLP " + label)
        return value

    scope_keys, record_key = {
        "resourceLogs": (("scopeLogs", "instrumentationLibraryLogs"), "logRecords"),
        "resourceSpans": (("scopeSpans", "instrumentationLibrarySpans"), "spans"),
        "resourceMetrics": (("scopeMetrics", "instrumentationLibraryMetrics"), "metrics"),
    }[field]
    for resource in objects(body.get(field), field):
        if "resource" in resource and not isinstance(resource["resource"], dict):
            raise ValueError("Invalid OTLP resource")
        for scope_key in scope_keys:
            for scope in objects(resource.get(scope_key, []), scope_key):
                if "scope" in scope and not isinstance(scope["scope"], dict):
                    raise ValueError("Invalid OTLP scope")
                for record in objects(scope.get(record_key, []), record_key):
                    if "attributes" in record:
                        objects(record["attributes"], "attributes")
                    if field == "resourceMetrics":
                        for kind in ("gauge", "sum", "histogram", "exponentialHistogram", "summary"):
                            if kind in record:
                                if not isinstance(record[kind], dict):
                                    raise ValueError("Invalid OTLP metric")
                                objects(record[kind].get("dataPoints", []), "dataPoints")

def otlp_identity(body, field):
    """Promote only explicit, unambiguous identities from known OTLP locations."""
    aliases = {
        "service.name": "service.name",
        "gen_ai.provider.name": "gen_ai.system", "gen_ai.system": "gen_ai.system",
        "gen_ai.request.model": "gen_ai.request.model", "model": "gen_ai.request.model",
        "session.id": "session.id", "conversation.id": "session.id",
        "developer.id": "developer.id", "developer_id": "developer.id",
    }
    values = {}
    def collect(node):
        if not isinstance(node, dict):
            return
        attrs = node.get("attributes", [])
        if not isinstance(attrs, list):
            return
        for attribute in attrs:
            if not isinstance(attribute, dict):
                continue
            key = attribute.get("key")
            if not isinstance(key, str) or key not in aliases:
                continue
            value = attribute.get("value")
            # Never stringify nested JSON/AnyValues into a fabricated identity.
            text = value.get("stringValue") if isinstance(value, dict) else None
            if isinstance(text, str) and text:
                values.setdefault(aliases[key], set()).add(text)

    scopes, records = {
        "resourceLogs": (("scopeLogs", "instrumentationLibraryLogs"), "logRecords"),
        "resourceSpans": (("scopeSpans", "instrumentationLibrarySpans"), "spans"),
        "resourceMetrics": (("scopeMetrics", "instrumentationLibraryMetrics"), "metrics"),
    }.get(field, ((), ""))
    resources = body.get(field, [])
    for item in resources if isinstance(resources, list) else []:
        if not isinstance(item, dict):
            continue
        collect(item.get("resource"))
        for scope_key in scopes:
            scope_list = item.get(scope_key, [])
            for scope in scope_list if isinstance(scope_list, list) else []:
                if not isinstance(scope, dict):
                    continue
                collect(scope.get("scope"))
                record_list = scope.get(records, [])
                for record in record_list if isinstance(record_list, list) else []:
                    if not isinstance(record, dict):
                        continue
                    if field != "resourceMetrics":
                        collect(record)
                    else:
                        for kind in ("gauge", "sum", "histogram", "exponentialHistogram", "summary"):
                            metric = record.get(kind, {})
                            points = metric.get("dataPoints", []) if isinstance(metric, dict) else []
                            for point in points if isinstance(points, list) else []:
                                collect(point)
    return {k: next(iter(v)) for k, v in values.items() if len(v) == 1}

def make_server(queue, port=8787, enterprise_store=None):
    queue.reconcile()
    if enterprise_store is None and os.getenv("DEVFLIGHT_ENTERPRISE") == "1":
        from .identity import Store
        enterprise_store = Store(os.getenv("DEVFLIGHT_PLATFORM_HOME", ".devflight/platform"))
    slots = threading.BoundedSemaphore(32)
    control_path = queue.home / "control.key"
    if control_path.exists():
        control_key = control_path.read_text(encoding="ascii").strip()
    else:
        control_key = secrets.token_hex(32)
        try:
            with control_path.open("x", encoding="ascii") as stream:
                stream.write(control_key)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            control_key = control_path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[a-f0-9]{64}", control_key):
        raise ValueError("Invalid control.key; refusing unauthenticated shutdown. Preserve the file and restore a valid control key.")
    if os.name != "nt":
        control_path.chmod(0o600)
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

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
            if enterprise_store is not None and self.command == "POST" and (self.path == "/events" or self.path in ("/v1/logs", "/v1/traces", "/v1/metrics")):
                # Per-user ingestion credentials are checked before reading the body.
                return True
            token = os.getenv("DEVFLIGHT_HTTP_TOKEN")
            return not token or hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self):
            if not self.authorized(): return self.reply(403, {"error": "Forbidden"})
            if self.path in ("/", "/health", "/status"):
                from .resources import snapshot
                return self.reply(200, {"service": "devflight-collector", "control_required": True,
                                        "enterprise":enterprise_store is not None,"process":snapshot(), **queue.status()})
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
                identity = None
                if enterprise_store is not None:
                    authorization = self.headers.get("Authorization", "")
                    if not authorization.startswith("Bearer "):
                        return self.reply(401, {"error": "Ingestion credential required"})
                    try:
                        identity = enterprise_store.authenticate(authorization[7:], purpose="ingest")
                    except PermissionError:
                        return self.reply(401, {"error": "Invalid ingestion credential"})
                    if not identity:
                        return self.reply(401, {"error": "Invalid ingestion credential"})
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
                    try:
                        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f: raw = f.read(LIMIT + 1)
                    except (OSError, EOFError) as error:
                        raise ValueError("Invalid gzip body") from error
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
                    if enterprise_store is not None:
                        event = enterprise_store.ingest(identity, body)
                    else:
                        event = trace.emit(body["event_type"], body.get("data",{}))
                    return self.reply(201, {"event_id":event["event_id"]})
                signal = self.path.rsplit("/",1)[-1]
                field = {"traces":"resourceSpans", "logs":"resourceLogs", "metrics":"resourceMetrics"}.get(signal)
                if self.path != "/v1/" + signal or field is None: return self.reply(404,{"error":"Not found"})
                validate_otlp(body, field)
                if enterprise_store is not None:
                    enterprise_store.ingest_otlp(identity, signal, body)
                    return self.reply(200, {})
                # Preserve original resource attributes: a batch may contain multiple developers/sessions.
                trace.agent["framework"] = "opentelemetry"
                identity = otlp_identity(body, field)
                provider = identity.get("gen_ai.system") or identity.get("service.name")
                trace.agent["id"] = provider
                trace.agent["model"] = identity.get("gen_ai.request.model")
                trace.session_id = identity.get("session.id")
                trace.developer_id = identity.get("developer.id")
                trace.emit("otel."+signal,body)
                self.reply(200,{})
            except (OSError, sqlite3.Error):
                self.send_response(503)
                self.send_header("Retry-After", "5")
                self.send_header("Content-Length", "0")
                self.end_headers()
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                self.reply(400,{"error":str(error)})
            finally:
                slots.release()
    server = ThreadingHTTPServer(("127.0.0.1",port),Handler)
    server.enterprise_store = enterprise_store
    return server

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
