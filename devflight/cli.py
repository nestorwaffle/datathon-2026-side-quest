import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .core import Queue, Trace, redact, restore_artifact

EXCLUDED = {".git", ".venv", "node_modules", "__pycache__", ".devflight", "models", "tmp", "output", ".codex", ".agents", ".aws", "private"}

def snapshot(root, queue):
    result = {}
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED and not (Path(directory)/d).is_symlink() and (Path(directory)/d).resolve() != queue.home]
        for name in files:
            path = Path(directory)/name
            if path.is_symlink() or name.startswith(".env") or name.endswith((".pem", ".key", ".p12")):
                continue
            try:
                result[str(path)] = path.read_bytes()
            except OSError:
                continue
    return result

def run(args, queue):
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise ValueError("A command is required after --")
    trace = Trace(queue, args.agent, args.task, args.kind)
    if args.developer: trace.developer_id = args.developer
    if args.session: trace.session_id = args.session
    trace.agent["model"] = args.model
    trace.agent["framework"] = "cli"
    env = dict(os.environ, DEVFLIGHT_HOME=str(queue.home), DEVFLIGHT_RUN_ID=trace.run_id,
               DEVFLIGHT_TRACE_ID=trace.trace_id, DEVFLIGHT_SPAN_ID=trace.span_id,
               DEVFLIGHT_DEVELOPER_ID=trace.developer_id, DEVFLIGHT_SESSION_ID=trace.session_id)
    recipe = None
    path = queue.home / "recipes.json"
    if args.recommend and path.exists():
        recipe = json.loads(path.read_text()).get(args.kind)
        if recipe:
            env["DEVFLIGHT_RECIPE"] = json.dumps(recipe)
    before = snapshot(Path.cwd(), queue)
    trace.emit("run.started", {"command": command, "recipe": recipe})
    start = time.perf_counter()
    code = 1
    try:
        process = subprocess.run(command, env=env, capture_output=True, timeout=args.timeout)
        stdout = process.stdout.decode("utf-8", "replace")
        stderr = process.stderr.decode("utf-8", "replace")
        code = process.returncode
        trace.emit("command.finished", {"command": command, "stdout": stdout, "stderr": stderr,
                   "returncode": code, "seconds": time.perf_counter()-start}, "ok" if code == 0 else "error")
        print(redact(stdout), end="")
        print(redact(stderr), end="", file=sys.stderr)
        if args.source:
            from .adapters import import_record
            for line in stdout.splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    import_record(trace, args.source, record)
    except subprocess.TimeoutExpired as error:
        code = 124
        trace.emit("command.finished", {"command": command, "stdout": (error.stdout or b"").decode("utf-8", "replace"),
            "stderr": (error.stderr or b"").decode("utf-8", "replace"), "returncode": code}, "timeout")
    except OSError as error:
        trace.emit("error", {"message": str(error)}, "error")
    finally:
        after = snapshot(Path.cwd(), queue)
        for path, content in after.items():
            if before.get(path) != content:
                trace.artifact(path, before.get(path, b"").decode("utf-8", "replace"))
        for path in before.keys() - after.keys():
            trace.emit("artifact.deleted", {"path": path, "previous_content": before[path].decode("utf-8", "replace")})
        trace.emit("run.finished", {"returncode": code, "seconds": time.perf_counter()-start}, "ok" if code == 0 else "error")
        if not args.no_sync:
            from .rawtree import sync
            try:
                result = sync(queue)
                print(json.dumps({"telemetry": result}), file=sys.stderr)
            except Exception as error:
                print(json.dumps({"telemetry_pending": queue.status()["pending"], "sync_error": redact(str(error))}), file=sys.stderr)
    return code

def main(argv=None):
    p = argparse.ArgumentParser(prog="fme-trace")
    p.add_argument("--home", help="Local queue directory")
    sub = p.add_subparsers(dest="action", required=True)
    for name in ("init", "status", "sync"):
        sub.add_parser(name)
    r = sub.add_parser("run")
    r.add_argument("--agent", default="cli"); r.add_argument("--task", default="development")
    r.add_argument("--kind", default="bug_fix"); r.add_argument("--recommend", action="store_true")
    r.add_argument("--source", choices=["codex", "claude", "generic"])
    r.add_argument("--developer"); r.add_argument("--session"); r.add_argument("--model", default="unknown")
    r.add_argument("--no-sync", action="store_true", help="Keep telemetry local; otherwise sync at exit")
    r.add_argument("--timeout", type=float, default=3600); r.add_argument("command", nargs=argparse.REMAINDER)
    e = sub.add_parser("emit"); e.add_argument("--type", required=True); e.add_argument("--data-file", required=True)
    a = sub.add_parser("artifact"); a.add_argument("--path", required=True)
    i = sub.add_parser("import"); i.add_argument("--source", required=True, choices=["codex", "claude", "generic"]); i.add_argument("--path", required=True)
    t = sub.add_parser("trace"); t.add_argument("trace_id"); t.add_argument("--remote", action="store_true")
    a = sub.add_parser("restore"); a.add_argument("artifact_id"); a.add_argument("--output", required=True); a.add_argument("--remote", action="store_true")
    a = sub.add_parser("analyze"); a.add_argument("--kind", required=True); a.add_argument("--champion", default="baseline"); a.add_argument("--local", action="store_true"); a.add_argument("--policy", action="store_true")
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8787)
    s = sub.add_parser("collect", help="Telemetry-only receiver with background upload")
    s.add_argument("--port", type=int, default=8787); s.add_argument("--interval", type=float, default=5)
    s = sub.add_parser("doctor", help="Read-only RawTree API connectivity check")
    s.add_argument("--read", action="store_true")
    args = p.parse_args(argv)
    queue = Queue(args.home)
    try:
        if args.action == "doctor":
            from .rawtree import RawTree
            client = RawTree(read_only=args.read)
            result = {"database": client.database, "connection": client.query("SELECT 1 AS connected")}
        elif args.action == "collect":
            from .collector import serve
            serve(queue, args.port, args.interval)
            return 0
        elif args.action == "run":
            return run(args, queue)
        elif args.action in ("status", "init"):
            result = queue.status()
        elif args.action == "sync":
            from .rawtree import sync
            result = sync(queue)
        elif args.action == "emit":
            result = Trace(queue).emit(args.type, json.loads(Path(args.data_file).read_text(encoding="utf-8-sig")))
        elif args.action == "artifact":
            result = Trace(queue).artifact(args.path)
        elif args.action == "import":
            from .adapters import import_file
            result = {"imported": import_file(Trace(queue), args.source, args.path)}
        elif args.action in ("trace", "restore"):
            rows = queue.events()
            if args.remote:
                from .rawtree import RawTree
                import re
                identifier = args.trace_id if args.action == "trace" else args.artifact_id
                if not re.fullmatch("[a-fA-F0-9]+", identifier):
                    raise ValueError("Invalid hex identifier")
                where = "trace_id" if args.action == "trace" else "data.artifact_id"
                table = "dev_events_raw" if args.action == "trace" else "dev_artifacts_raw"
                sql = f"SELECT event_json AS event FROM {table} WHERE {where} = '{identifier}' ORDER BY sequence"
                rows = [json.loads(r["event"]) for r in RawTree(read_only=True).query(sql)]
            if args.action == "trace":
                result = [e for e in rows if e["trace_id"] == args.trace_id]
            else:
                with open(args.output, "xb") as f:
                    f.write(restore_artifact(rows, args.artifact_id))
                result = {"restored": args.output}
        elif args.action == "analyze":
            from .analyst import analyze
            if args.local:
                rows, sql = queue.events(), "local queue (explicit offline mode)"
            else:
                from .rawtree import RawTree
                rows, sql = RawTree(read_only=True).evaluations()
            result = analyze(queue, rows, args.kind, args.champion, sql, args.policy)
        elif args.action == "serve":
            from .server import serve
            serve(queue, args.port)
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"error": redact(str(error))}), file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
