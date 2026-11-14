"""DevFlight low-overhead Codex setup for Windows, without external dependencies.

Run from repository root: .venv\\Scripts\\python.exe devflight_fix.py

This patches start_devflight.py only when its expected source is present, and
backs up the user's Codex TOML before changing managed telemetry settings.
It does not delete or modify RawTree data or local telemetry queues.
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
import re
import shutil
import sys
import tomllib

ROOT = Path(__file__).resolve().parent
LAUNCHER = ROOT / "start_devflight.py"
CONFIG = Path.home() / ".codex" / "config.toml"
KEYS = {
    "exporter": "exporter = { otlp-http = { endpoint = 'http://127.0.0.1:8787/v1/logs', protocol = 'json' } }",
    "trace_exporter": "trace_exporter = 'none'",
    "metrics_exporter": "metrics_exporter = 'none'",
    "log_user_prompt": "log_user_prompt = false",
    "log_agent_responses": "log_agent_responses = false",
}
HEADER = re.compile(r"^\s*\[([^\]]+)\]\s*(?:#.*)?$")
ASSIGNMENT = re.compile(r"^\s*([\w-]+)\s*=")


def backup(path: Path) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = path.with_name(path.name + ".backup-" + stamp)
    shutil.copy2(path, target)
    return target


def modify_launcher() -> None:
    original = LAUNCHER.read_text(encoding="utf-8")
    # The existing --with-codex launcher starts a separate interactive CLI. In
    # light mode it should not emit every internal span by default.
    old = 'f"otel.trace_exporter={{otlp-http={{endpoint=\'{base}/v1/traces\',protocol=\'json\'}}}}",'
    new = '"otel.trace_exporter=\'none\'",'
    if old in original:
        updated = original.replace(old, new, 1)
        compile(updated, str(LAUNCHER), "exec")
        save = backup(LAUNCHER)
        LAUNCHER.write_text(updated, encoding="utf-8")
        print("[OK] Launcher uses lightweight logs; internal traces disabled.")
        print("[BACKUP]", save)
    elif new in original:
        print("[OK] Launcher already uses lightweight telemetry.")
    else:
        print("[NOTICE] Unexpected launcher version; not modifying its code.")


def configure_codex() -> None:
    if os.environ.get("DEVFLIGHT_HTTP_TOKEN"):
        raise RuntimeError("DEVFLIGHT_HTTP_TOKEN is set. Configure exporter authorization before enabling globally.")
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    original = CONFIG.read_text(encoding="utf-8") if CONFIG.exists() else ""
    parsed = tomllib.loads(original)
    # Inline root 'otel' or other unusual layouts are not safe to rewrite.
    if "otel" in parsed and not isinstance(parsed["otel"], dict):
        raise RuntimeError("Existing inline 'otel' configuration is not supported; file unchanged.")
    sections = []
    lines = original.splitlines(keepends=True)
    for i, line in enumerate(lines):
        match = HEADER.match(line)
        if match:
            section = match.group(1).replace('"', '').replace("'", "")
            sections.append((i, section))
    if sum(section == "otel" for _, section in sections) > 1:
        raise RuntimeError("Multiple [otel] sections; no changes made.")
    # Don't risk overwriting custom existing OTLP subtable settings.
    if any(section.startswith(("otel.exporter", "otel.trace_exporter", "otel.metrics_exporter")) for _, section in sections):
        raise RuntimeError("Nested [otel.*] tables detected; merge manually, config unchanged.")
    if re.search(r"(?m)^\s*otel\s*=", original):
        raise RuntimeError("Root inline otel config detected; config unchanged.")
    existing_section = next((i for i, section in sections if section == "otel"), None)
    if existing_section is None:
        # Appending [otel] only after all existing tables avoids accidentally
        # moving root settings into a new namespace.
        updated = original.rstrip() + ("\n\n" if original.strip() else "") + "[otel]\n" + "\n".join(KEYS.values()) + "\n"
    else:
        end = next((i for i, _ in sections if i > existing_section), len(lines))
        before, region, after = lines[:existing_section+1], lines[existing_section+1:end], lines[end:]
        keep = []
        for line in region:
            match = ASSIGNMENT.match(line)
            if match and match.group(1) in KEYS:
                continue
            keep.append(line)
        updated = "".join(before + [s + "\n" for s in KEYS.values()] + keep + after)
    tomllib.loads(updated)  # validate BEFORE touching original
    if updated != original:
        if CONFIG.exists():
            print("[BACKUP]", backup(CONFIG))
        tmp = CONFIG.with_name("config.toml.devflight-tmp")
        tmp.write_text(updated, encoding="utf-8")
        os.replace(tmp, CONFIG)
    print("[OK] Global Codex telemetry configured:", CONFIG)
    print("     All NEW Codex CLI terminals use OTLP logs, no full traces.")
    print("     Restart existing Codex windows; sessions already running are unaffected.")


def main() -> int:
    if not LAUNCHER.exists():
        raise RuntimeError("Place this script in the DevFlight repository root (alongside start_devflight.py).")
    modify_launcher()
    configure_codex()
    print("[NEXT] Restart DevFlight collector using start_devflight.py stop/start.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("[ERROR]", exc, file=sys.stderr)
        sys.exit(1)
