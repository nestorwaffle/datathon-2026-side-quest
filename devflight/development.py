"""Opt-in SDK recording of observable development operations, never command content."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import hashlib
import secrets

from .core import Trace, atomic_json
from .identity import Store


class Development:
    def __init__(self):
        self.store = Store()
        self.store.bootstrap()
        self.home = self.store.home.parent / "development"
        self.home.mkdir(parents=True, exist_ok=True)
        session = self.home / "session.json"
        if not session.exists():
            atomic_json(session, {"run_id": str(uuid.uuid4()), "started": time.time(),
                                  "coverage": "Explicit SDK operations only; no private reasoning, no automatic capture of previous work"})
        self.run = json.loads(session.read_text(encoding="utf-8"))
        if "trace_id" not in self.run:
            self.run.update(trace_id=secrets.token_hex(16),root_span_id=secrets.token_hex(8))
            atomic_json(session,self.run)
        credential = self.home / "ingest.key"
        if not credential.exists():
            owner = self.store.authenticate((self.store.home / "admin.token").read_text().strip(), "login")
            key = self.store.issue(owner, "ingest")
            with credential.open("x", encoding="ascii") as stream:
                stream.write(key); stream.flush(); os.fsync(stream.fileno())
            if os.name != "nt": credential.chmod(0o600)
        self.identity = self.store.authenticate(credential.read_text().strip(), "ingest")
        self.trace = Trace(queue=self, agent="development-sdk", task="devflight-implementation", model=None)
        self.trace.run_id = self.run["run_id"]
        self.trace.session_id = self.run["run_id"]
        self.trace.trace_id=self.run["trace_id"]
        self.trace.span_id=self.run["root_span_id"]

    def append(self, event):
        data = event.get("data", {})
        normalized = {"event_id": event["event_id"], "timestamp": event["timestamp"],
            "agent": "development-sdk", "session_id": self.run["run_id"],
            "trace_id": event["trace_id"], "span_id": event["span_id"],
            "parent_span_id": event.get("parent_span_id"), "event_type": event["event_type"],
            "tool": data.get("name"), "status": event["status"],
            "duration_ms": data.get("duration_ms"), "error_type": data.get("error_type"),
            "run_id": self.run["run_id"], "activity_kind": "development",
            "provenance": "explicit-sdk-observation", "synthetic": False,
            "file_path":data.get("file_path"),"file_sha256":data.get("file_sha256")}
        return self.store.ingest(self.identity, normalized)

    def record(self, name, duration_ms=None, status="ok", error_type=None):
        child=Trace(queue=self,parent=self.trace,agent="development-sdk",model=None)
        return child.emit("development.operation", {"name": name, "duration_ms": duration_ms,
                              "error_type": error_type}, status=status)

    def observe_files(self, paths):
        root=Path(__file__).resolve().parents[1]
        events=[]
        for name in paths:
            path=(root/name).resolve()
            if root not in path.parents or not path.is_file() or path.suffix not in (".py",".tsx",".ts",".css"):
                raise ValueError("Only explicitly selected repository source files may be observed")
            relative=path.relative_to(root).as_posix()
            sha=hashlib.sha256(path.read_bytes()).hexdigest()
            event=self.trace.emit("development.file_observed",{"name":"source-metadata-observation",
                                   "file_path":relative,"file_sha256":sha})
            events.append(event["event_id"])
        return events


def main():
    parser = argparse.ArgumentParser(description="Record an actual development command without arguments or output")
    parser.add_argument("--name", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command: parser.error("A development command is required")
    capture = Development()
    started = time.perf_counter()
    try:
        result = subprocess.run(command)
        event = capture.record(args.name, (time.perf_counter()-started)*1000,
                               "ok" if result.returncode == 0 else "error",
                               "CommandExit" if result.returncode else None)
        print(json.dumps({"development_run": capture.run["run_id"], "event_id": event["event_id"],
                          "coverage": "SDK command metadata; no prompts/output/code", "pending_sync": True}))
        return result.returncode
    except OSError as error:
        capture.record(args.name, (time.perf_counter()-started)*1000, "error", type(error).__name__)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
