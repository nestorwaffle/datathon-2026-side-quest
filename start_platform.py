"""Single local entry point for the existing collector and enterprise application."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

import start_devflight as collector

ROOT = Path(__file__).resolve().parent
HOME = ROOT / ".devflight" / "platform"

def health():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8788/api/health", timeout=2) as response:
            data = json.load(response)
            if data.get("service") != "devflight-platform":
                raise RuntimeError("Port 8788 belongs to another application")
            return data
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None

def main():
    global HOME
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", choices=("start", "restart", "status", "stop", "doctor", "integrations"), default="start")
    args,extra = parser.parse_known_args()
    if args.action in ("doctor","integrations"):
        return subprocess.call([sys.executable,str(ROOT/"start_devflight.py"),args.action,*extra],cwd=ROOT)
    if extra: parser.error("Unexpected arguments")
    collector.load_environment()
    configured=Path(os.getenv("DEVFLIGHT_PLATFORM_HOME",str(HOME)))
    HOME=(configured if configured.is_absolute() else ROOT/configured).resolve()
    os.environ["DEVFLIGHT_PLATFORM_HOME"] = str(HOME)
    os.environ["DEVFLIGHT_ENTERPRISE"] = "1"
    from devflight.core import file_lock
    HOME.mkdir(parents=True, exist_ok=True)
    with file_lock(HOME / "launcher.lock"):
        current = health()
        if args.action == "status":
            from devflight.identity import Store
            local=Store(HOME).status() if (HOME/"platform.sqlite3").exists() else None
            print(json.dumps({"platform": current,"enterprise_outbox_local":local,
                              "collector": collector.get_health(8787)}, ensure_ascii=False))
            return 0
        if args.action in ("stop","restart"):
            if current:
                key = (HOME / "control.key").read_text().strip()
                request = urllib.request.Request("http://127.0.0.1:8788/api/control/stop", data=b"{}",
                    headers={"Content-Type": "application/json", "X-DevFlight-Control": key})
                with urllib.request.urlopen(request, timeout=3): pass
                for _ in range(20):
                    if health() is None: break
                    time.sleep(.1)
                else: raise RuntimeError("Platform did not stop")
            if args.action=="stop":
                old=collector.get_health(8787)
                if old and not old.get("control_required"):
                    print("[WARNING] Platform stopped. Legacy collector has no authenticated stop API; retained without terminating an unverified process.")
                    return 1
                return subprocess.call([sys.executable, str(ROOT / "start_devflight.py"), "stop"], cwd=ROOT)
            current=None
        from devflight.identity import Store
        Store(HOME).bootstrap()
        existing=collector.get_health(8787)
        if existing and not existing.get("enterprise"):
            print("[Collector] Existing legacy collector retained; org ingestion uses /api/events until authenticated collector restart.")
        collector.ensure_collector(8787)
        if not current:
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            with (HOME / "platform.log").open("ab") as logfile:
                child = subprocess.Popen([sys.executable, "-m", "devflight.platform", "--home", str(HOME)],
                    cwd=ROOT, env=os.environ.copy(), stdin=subprocess.DEVNULL,
                    stdout=logfile, stderr=subprocess.STDOUT, creationflags=flags,
                    start_new_session=os.name != "nt")
            for _ in range(40):
                if child.poll() is not None: raise RuntimeError("Platform stopped; inspect .devflight/platform/platform.log")
                if health(): break
                time.sleep(.25)
            else: raise RuntimeError("Platform did not become ready")
        print("DevFlight: http://127.0.0.1:8788")
        print(f"Private sign-in token file: {HOME / 'admin.token'}")
        return 0

if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as error:
        print("[ERROR] " + str(error), file=sys.stderr)
        raise SystemExit(1)
