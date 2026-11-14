#!/usr/bin/env python3
r"""Start the DevFlight collector in the background and launch an OTLP-enabled Codex CLI.

Place this file at the root of the DevFlight repository on Windows.
Usage:
    .venv\Scripts\python.exe start_devflight.py
    .venv\Scripts\python.exe start_devflight.py --status
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / ".devflight" / "telemetry"
STATE_PATH = QUEUE / "launcher_state.json"
LOG_PATH = QUEUE / "collector.log"


def load_environment():
    # DevFlight already has a safe .env loader that does not override real env vars.
    from devflight.core import load_dotenv
    load_dotenv(ROOT / ".env")


def get_health(port):
    headers = {}
    token = os.environ.get("DEVFLIGHT_HTTP_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(f"http://127.0.0.1:{port}/health", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=1.5) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Collector returned HTTP {exc.code} (check DEVFLIGHT_HTTP_TOKEN).") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None
    if value.get("service") != "devflight-collector":
        raise RuntimeError(f"Port {port} belongs to a different service, not DevFlight.")
    if value.get("home") and Path(value["home"]).resolve() != QUEUE.resolve():
        raise RuntimeError(f"DevFlight on port {port} uses a different queue: {value['home']}")
    return value


def ensure_collector(port):
    QUEUE.mkdir(parents=True, exist_ok=True)
    status = get_health(port)
    if status is not None:
        print(f"[OK] Collector already running on http://127.0.0.1:{port}")
        return status

    args = [sys.executable, "-m", "devflight", "--home", str(QUEUE),
            "collect", "--port", str(port), "--interval", "5"]
    # CREATE_NO_WINDOW prevents an extra console; this Python process may exit.
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    with LOG_PATH.open("ab") as logfile:
        proc = subprocess.Popen(
            args, cwd=str(ROOT), env=os.environ.copy(), stdin=subprocess.DEVNULL,
            stdout=logfile, stderr=subprocess.STDOUT, creationflags=flags,
        )
    for _ in range(40):
        if proc.poll() is not None:
            raise RuntimeError(f"Collector stopped during startup (code {proc.returncode}). Check {LOG_PATH}")
        status = get_health(port)
        if status is not None:
            print(f"[OK] Collector started (PID {proc.pid}) on port {port}")
            print(f"     Collector log: {LOG_PATH}")
            return status
        time.sleep(0.25)
    raise RuntimeError(f"Collector did not answer /health after startup. Check {LOG_PATH}")


def check_rawtree_read():
    if not os.environ.get("RAWTREE_API_KEY"):
        print("[WARNING] RAWTREE_API_KEY is missing. Events will be queued locally, not uploaded.")
        return
    if not os.environ.get("RAWTREE_READ_KEY"):
        print("[WARNING] RAWTREE_READ_KEY missing; cannot confirm remote access.")
        return
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "devflight", "doctor", "--read"],
            cwd=str(ROOT), env=os.environ.copy(), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=15,
        )
        if proc.returncode == 0 and '"connected": 1' in proc.stdout:
            print("[OK] RawTree read connection verified (SELECT 1).")
        else:
            print("[WARNING] RawTree read check failed. Collector will retain pending events.")
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"[WARNING] RawTree read check unavailable: {type(exc).__name__}")


def codex_overrides(port):
    # Single-quoted TOML strings avoid nested Windows cmd.exe quoting problems.
    base = f"http://127.0.0.1:{port}"
    return [
        f"otel.exporter={{otlp-http={{endpoint='{base}/v1/logs',protocol='json'}}}}",
        f"otel.trace_exporter={{otlp-http={{endpoint='{base}/v1/traces',protocol='json'}}}}",
        "otel.log_user_prompt=false",
    ]


def create_codex_launcher(port):
    codex_path = shutil.which("codex.cmd") or shutil.which("codex.exe") or shutil.which("codex")
    if not codex_path:
        raise RuntimeError("Codex CLI not found in PATH. Check 'where codex' in CMD.")
    if os.environ.get("DEVFLIGHT_HTTP_TOKEN"):
        raise RuntimeError(
            "DEVFLIGHT_HTTP_TOKEN is configured. This launcher deliberately does not "
            "write tokens into a .cmd file. Configure Codex OTLP Authorization headers first."
        )
    launcher = QUEUE.parent / "codex_with_devflight.cmd"
    flags = " ".join('-c "' + item + '"' for item in codex_overrides(port))
    content = (
        "@echo off\r\n"
        "title Codex - DevFlight OTLP to RawTree\r\n"
        f'cd /d "{ROOT}"\r\n'
        "echo Codex telemetry is enabled for this window.\r\n"
        f'call "{codex_path}" {flags}\r\n'
        "echo.\r\n"
        "echo Codex finished. The DevFlight collector remains active.\r\n"
        "pause\r\n"
    )
    launcher.write_bytes(content.encode("utf-8"))
    return launcher


def remote_status():
    if not os.environ.get("RAWTREE_READ_KEY"):
        print("[INFO] No RAWTREE_READ_KEY, cannot inspect remote events.")
        return
    from devflight.rawtree import RawTree
    try:
        rows = RawTree(read_only=True).query(
            "SELECT timestamp, event_type, event_id FROM dev_events_raw "
            "WHERE event_type = 'otel.logs' ORDER BY timestamp DESC LIMIT 3"
        )
        print("[RawTree] Latest OTLP log batches:")
        if not rows:
            print("  None found yet. Open the launched Codex window and do a task.")
        for row in rows:
            print("  " + json.dumps(row, ensure_ascii=False))
    except Exception as exc:
        print(f"[WARNING] RawTree query failed ({type(exc).__name__}).")


def show_status(port):
    from devflight import Queue
    queue_status = Queue(QUEUE).status()
    health = get_health(port)
    print("[Collector] " + ("running" if health else "not running"))
    print("[Queue] " + json.dumps({
        "total": queue_status.get("total"),
        "pending": queue_status.get("pending"),
        "last_error": queue_status.get("last_error"),
    }, ensure_ascii=False))
    if STATE_PATH.exists():
        try:
            baseline = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            delta = queue_status.get("total", 0) - baseline.get("total_at_launch", 0)
            print(f"[Since last launch] {delta} new local events (all sources)")
        except (ValueError, OSError, TypeError):
            pass
    remote_status()


def main():
    parser = argparse.ArgumentParser(description="DevFlight background telemetry service")
    parser.add_argument("action", nargs="?", choices=("start", "stop", "status", "doctor"), default="start")
    parser.add_argument("--status", action="store_true", help="Show queue and RawTree status without launching")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--only-collector", action="store_true", help="Do not open a Codex window")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This launcher is intended for Windows CMD/PowerShell")
    if not (ROOT / "pyproject.toml").exists():
        parser.error("Save this file in the root of your DevFlight repository")
    try:
        load_environment()
        if args.status or args.action == "status":
            show_status(args.port)
            return 0
        if args.action == "stop":
            if get_health(args.port) is None:
                print("[Collector] not running")
                return 0
            headers = {}
            if os.environ.get("DEVFLIGHT_HTTP_TOKEN"):
                headers["Authorization"] = "Bearer " + os.environ["DEVFLIGHT_HTTP_TOKEN"]
            req = urllib.request.Request(f"http://127.0.0.1:{args.port}/shutdown", data=b"", headers=headers)
            with urllib.request.urlopen(req, timeout=3): pass
            print("[Collector] stopping")
            return 0
        if args.action == "doctor":
            show_status(args.port)
            check_rawtree_read()
            print("[Integrations] Codex: configure OTLP in user config; Claude Code: configure OTEL environment for new sessions.")
            return 0

        # Validate the CLI before starting the collector, so errors are explicit.
        if not args.only_collector and args.action != "start":
            launcher = create_codex_launcher(args.port)
        status = ensure_collector(args.port)
        STATE_PATH.write_text(json.dumps({
            "total_at_launch": status.get("total", 0),
            "started_at_epoch": time.time(),
            "port": args.port,
        }, indent=2), encoding="utf-8")
        if args.only_collector or args.action == "start":
            print("[OK] Collector active.")
            return 0

        # Opening the .cmd through ShellExecute starts a separate console window.
        os.startfile(str(launcher))
        print("[OK] Codex opened in a NEW terminal with OTLP/JSON enabled.")
        print("     Work in that new Codex window (not in an unrelated Codex session).")
        print("     After a task, run: .venv\\Scripts\\python.exe start_devflight.py --status")
        return 0
    except Exception as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
