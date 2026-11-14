"""Durable local-first telemetry. No network operations in the SDK."""
import base64
import contextlib
import datetime as dt
import difflib
import gzip
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import time
import uuid

MASK = "[REDACTED_SECRET]"

def load_dotenv(dotenv_path=None):
    """Load variables from .env if present into os.environ without overwriting existing vars."""
    if dotenv_path is None:
        dotenv_path = Path.cwd() / ".env"
        if not dotenv_path.exists():
            dotenv_path = Path(__file__).resolve().parents[1] / ".env"
    path = Path(dotenv_path)
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            if key and key not in os.environ:
                os.environ[key] = val

load_dotenv()
SECRET_KEY = re.compile(r"(?i)(password|passwd|secret|api[_-]?key|authorization|cookie|access[_-]?token|refresh[_-]?token|^token$)")
PATTERNS = [
    re.compile(r"\b(?:sk-|rt_|ghp_|github_pat_|AKIA)[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    re.compile(r"(?i)\bBearer\s+[^\s\"']+"),
    re.compile(r'''(?ix)(?:password|passwd|api[_-]?key|secret|access[_-]?token|refresh[_-]?token|cookie)\s*[=:]\s*["']?[^\s,"';}]+'''),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]

def redact(value):
    if isinstance(value, dict):
        # OpenTelemetry attributes use {key, value} rather than key:value.
        if isinstance(value.get("key"), str) and SECRET_KEY.search(value["key"]):
            return {**value, "value": {"stringValue": MASK}}
        return {k: MASK if SECRET_KEY.search(k) else redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for k, v in os.environ.items():
            if SECRET_KEY.search(k) and len(v) >= 6:
                value = value.replace(v, MASK)
        for pattern in PATTERNS:
            value = pattern.sub(MASK, value)
    return value

def uuid7():
    n = (int(time.time() * 1000) << 80) | (7 << 76) | (secrets.randbits(12) << 64)
    return str(uuid.UUID(int=n | (2 << 62) | secrets.randbits(62)))

def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(redact(value), f, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

@contextlib.contextmanager
def file_lock(path):
    with open(path, "a+b") as f:
        if os.name == "nt":
            import msvcrt
            if f.tell() == 0:
                f.write(b"0"); f.flush()
            while True:
                try:
                    f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(.02)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)

class Queue:
    def __init__(self, home=None, rotate_bytes=1024 * 1024):
        self.home = Path(home or os.getenv("DEVFLIGHT_HOME", ".devflight")).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.rotate_bytes = rotate_bytes
        self.active = self.home / "active.jsonl"

    def _read(self):
        events = {}
        for path in sorted(self.home.glob("segment-*.jsonl.gz")) + [self.active]:
            if not path.exists():
                continue
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", encoding="utf-8") as f:
                for line in f:
                    event = json.loads(line)
                    events[event["event_id"]] = event
        return sorted(events.values(), key=lambda e: e["sequence"])

    def _recover(self):
        if not self.active.exists():
            return
        raw = self.active.read_bytes()
        if raw and not raw.endswith(b"\n"):
            end = raw.rfind(b"\n") + 1
            # Keep a damaged tail for diagnosis, never silently discard it.
            (self.home / ("damaged-" + uuid7() + ".bin")).write_bytes(raw[end:])
            with self.active.open("r+b") as f:
                f.truncate(end); f.flush(); os.fsync(f.fileno())

    def events(self):
        with file_lock(self.home / "queue.lock"):
            self._recover()
            return self._read()

    def append(self, event):
        with file_lock(self.home / "queue.lock"):
            self._recover()
            rows = self._read()
            event = redact(event)
            event["sequence"] = max((e["sequence"] for e in rows), default=0) + 1
            raw = (json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n").encode()
            with self.active.open("ab") as f:
                f.write(raw); f.flush(); os.fsync(f.fileno())
            if self.active.stat().st_size >= self.rotate_bytes:
                path = self.home / ("segment-" + uuid7() + ".jsonl.gz")
                tmp = path.with_suffix(".tmp")
                with tmp.open("wb") as f:
                    f.write(gzip.compress(self.active.read_bytes(), mtime=0))
                    f.flush(); os.fsync(f.fileno())
                os.replace(tmp, path)
                self.active.unlink()
            return event

    def state(self):
        path = self.home / "sync.json"
        return json.loads(path.read_text()) if path.exists() else {"acked": [], "last_error": None}

    def status(self):
        rows, state = self.events(), self.state()
        acked = set(state["acked"])
        pending = [e for e in rows if e["event_id"] not in acked]
        oldest = pending[0]["timestamp"] if pending else None
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(oldest)).total_seconds() if oldest else 0
        return {"total": len(rows), "pending": len(pending), "oldest": oldest,
                "age_seconds": age, "last_error": state.get("last_error"), "home": str(self.home)}

class Trace:
    def __init__(self, queue=None, agent="python", task="development", kind="bug_fix", model="unknown", parent=None):
        self.queue = queue or Queue()
        self.run_id = parent.run_id if parent else os.getenv("DEVFLIGHT_RUN_ID", uuid7())
        self.trace_id = parent.trace_id if parent else os.getenv("DEVFLIGHT_TRACE_ID", secrets.token_hex(16))
        self.parent_span_id = parent.span_id if parent else os.getenv("DEVFLIGHT_SPAN_ID")
        self.span_id = secrets.token_hex(8)
        self.agent = {"id": agent, "framework": "python", "model": model}
        self.task = {"id": task, "kind": kind}
        self.developer_id = parent.developer_id if parent else (os.getenv("DEVFLIGHT_DEVELOPER_ID") or "unassigned")
        self.session_id = parent.session_id if parent else (os.getenv("DEVFLIGHT_SESSION_ID") or self.run_id)

    def emit(self, event_type, data=None, status="ok", artifacts=None):
        if not isinstance(event_type, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,100}", event_type):
            raise ValueError("Invalid event_type")
        return self.queue.append({"schema_version": 1, "event_id": uuid7(),
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(), "project_id": "datathon-mathops",
            "run_id": self.run_id, "trace_id": self.trace_id, "span_id": self.span_id,
            "parent_span_id": self.parent_span_id, "agent": self.agent, "task": self.task,
            "event_type": event_type, "status": status, "data": {} if data is None else data,
            "artifacts": artifacts or [], "developer_id": self.developer_id,
            "session_id": self.session_id, "agent_id": self.agent["id"], "model": self.agent["model"]})

    @contextlib.contextmanager
    def child(self, agent, kind=None):
        child = Trace(self.queue, agent, self.task["id"], kind or self.task["kind"], parent=self)
        child.emit("agent.spawned", {"parent_agent": self.agent["id"]})
        try:
            yield child
        except BaseException as error:
            child.emit("error", {"message": str(error)}, "error")
            child.emit("agent.finished", {}, "error")
            raise
        else:
            child.emit("agent.finished")

    @contextlib.contextmanager
    def tool(self, name, arguments):
        started = time.perf_counter()
        self.emit("tool.started", {"name": name, "arguments": arguments})
        result = {}
        try:
            yield result
        except BaseException as error:
            self.emit("tool.result", {"name": name, "error": str(error), "seconds": time.perf_counter()-started}, "error")
            raise
        else:
            self.emit("tool.result", {"name": name, "result": result, "seconds": time.perf_counter()-started})

    def artifact(self, path, before=None):
        path = Path(path)
        content = path.read_bytes()
        try:
            text = content.decode("utf-8")
            content = redact(text).encode("utf-8")
        except UnicodeDecodeError:
            # Binary blobs require explicit handling: redact known embedded secrets too.
            for key, value in os.environ.items():
                if SECRET_KEY.search(key) and len(value) >= 6:
                    content = content.replace(value.encode(), MASK.encode())
            for pattern in PATTERNS:
                content = re.compile(pattern.pattern.encode(), pattern.flags & ~re.UNICODE).sub(MASK.encode(), content)
        digest = hashlib.sha256(content).hexdigest()
        with file_lock(self.queue.home / "artifacts.lock"):
            known = any(e["event_type"] == "artifact.created" and digest in e["artifacts"] for e in self.queue.events())
            if not known:
                blob = gzip.compress(content, mtime=0)
                chunks = [blob[i:i+32768] for i in range(0, len(blob), 32768)]
                for i, chunk in enumerate(chunks):
                    self.emit("artifact.chunk", {"artifact_id": digest, "index": i, "count": len(chunks),
                        "encoding": "gzip+base64", "content": base64.b64encode(chunk).decode()}, artifacts=[digest])
            diff = None
            if before is not None:
                diff = "".join(difflib.unified_diff(redact(before).splitlines(True), content.decode("utf-8", "replace").splitlines(True), fromfile=str(path), tofile=str(path)))
            return self.emit("artifact.created", {"artifact_id": digest, "path": str(path),
                "sha256": digest, "size": len(content), "mime": mimetypes.guess_type(path)[0],
                "diff": diff, "deduplicated": known}, artifacts=[digest])

def restore_artifact(events, artifact_id):
    chunks = {e["data"]["index"]: e["data"] for e in events
              if e["event_type"] == "artifact.chunk" and e["data"]["artifact_id"] == artifact_id}
    if not chunks or set(chunks) != set(range(next(iter(chunks.values()))["count"])):
        raise ValueError("Incomplete artifact")
    content = gzip.decompress(b"".join(base64.b64decode(chunks[i]["content"]) for i in sorted(chunks)))
    if hashlib.sha256(content).hexdigest() != artifact_id:
        raise ValueError("Artifact checksum mismatch")
    return content
