"""Supported, documented exporter routes. No process inspection or config mutation."""
import json
import os
from pathlib import Path
import tomllib
import shutil
import time
import secrets
from urllib.parse import urlsplit

REGISTRY = {
    "codex": {"transport": "OTLP/HTTP JSON", "config": "~/.codex/config.toml", "default_signals": "logs"},
    "claude_code": {"transport": "OTLP/HTTP JSON", "config": "user environment", "default_signals": "logs,metrics"},
    "gemini_cli": {"transport": "OTLP/HTTP JSON", "config": "~/.gemini/settings.json", "default_signals": "logs,metrics"},
    "qwen_code": {"transport": "OTLP/HTTP JSON", "config": "~/.qwen/settings.json", "default_signals": "logs,metrics"},
}

def _json_settings(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

def report(queue=None, port=8787):
    home = Path.home()
    try:
        codex = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        codex = {}
    gemini = _json_settings(home / ".gemini" / "settings.json").get("telemetry", {})
    qwen = _json_settings(home / ".qwen" / "settings.json").get("telemetry", {})
    codex_exporter = codex.get("otel", {}).get("exporter", {})
    codex_http = codex_exporter.get("otlp-http", {}) if isinstance(codex_exporter, dict) else {}
    codex_endpoint = str(codex_http.get("endpoint", ""))
    def local(endpoint):
        try:
            parsed = urlsplit(str(endpoint))
            accepted_ports={8787,8788} if port in (8787,8788) else {port}
            return parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost") and parsed.port in accepted_ports
        except ValueError:
            return False
    configured = {
        "codex": local(codex_endpoint),
        "claude_code": (os.getenv("CLAUDE_CODE_ENABLE_TELEMETRY", "").lower() in ("1", "true")
                        and any("otlp" in os.getenv(name, "").split(",") for name in ("OTEL_LOGS_EXPORTER", "OTEL_METRICS_EXPORTER", "OTEL_TRACES_EXPORTER"))
                        and local(os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")))),
        "gemini_cli": bool(os.getenv("GEMINI_TELEMETRY_ENABLED", str(gemini.get("enabled", ""))).lower() in ("true", "1")
                           and local(os.getenv("GEMINI_TELEMETRY_OTLP_ENDPOINT", gemini.get("otlpEndpoint", "")))),
        "qwen_code": bool(os.getenv("QWEN_TELEMETRY_ENABLED", str(qwen.get("enabled", ""))).lower() in ("true", "1")
                          and local(os.getenv("QWEN_TELEMETRY_OTLP_ENDPOINT", qwen.get("otlpEndpoint", "")))),
    }
    # A configured exporter may target another collector. Report no false readiness.
    def bearer_header(value):
        if isinstance(value,dict):
            return any(str(key).lower()=="authorization" and isinstance(val,str) and val.startswith("Bearer ") for key,val in value.items())
        return isinstance(value,str) and any(part.strip().lower().startswith("authorization=bearer ") for part in value.split(","))
    common_headers=os.getenv("OTEL_EXPORTER_OTLP_LOGS_HEADERS",os.getenv("OTEL_EXPORTER_OTLP_HEADERS",""))
    auth_headers={"codex":bearer_header(codex_http.get("headers",{})),
                  "claude_code":bearer_header(common_headers),
                  "gemini_cli":bearer_header(common_headers),"qwen_code":bearer_header(common_headers)}
    result = {name: {**details, "configured": configured[name],
                     "requires_intervention": not configured[name],
                     "auth_header_configured":auth_headers[name],"authenticated":None,"uploaded":None,
                     "verification":"Configuration only; authentication and remote delivery require a received event ID",
                     "emitting": None} for name, details in REGISTRY.items()}
    if queue is not None:
        for event in queue.events():
            provider = event.get("agent", {}).get("id")
            if provider in result:
                result[provider]["emitting"] = True
                result[provider]["last_received"]=event.get("timestamp")
        for details in result.values():
            if details["emitting"] is None:
                details["emitting"] = False
    return result

def configure(provider, port=8787):
    """Interactive, backed-up setup for official user settings only."""
    if provider not in ("codex", "gemini_cli", "qwen_code"):
        raise ValueError("This provider requires manual environment or SDK setup")
    home = Path.home()
    path = home / {"codex": ".codex/config.toml", "gemini_cli": ".gemini/settings.json",
                   "qwen_code": ".qwen/settings.json"}[provider]
    if provider == "codex":
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if tomllib.loads(current).get("otel"):
            raise ValueError("Existing Codex OTEL settings require manual merge; no file changed")
        proposed = current.rstrip() + ("\n\n" if current.strip() else "") + (
            "[otel]\nlog_user_prompt = false\ntrace_exporter = 'none'\n"
            f"exporter = {{ otlp-http = {{ endpoint = 'http://127.0.0.1:{port}/v1/logs', protocol = 'json' }} }}\n")
    else:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(existing, dict):
            raise ValueError("Settings are not a JSON object")
        telemetry = existing.get("telemetry", {})
        if telemetry:
            raise ValueError("Existing telemetry settings require manual merge; no file changed")
        settings = {"enabled": True, "otlpEndpoint": f"http://127.0.0.1:{port}",
                    "otlpProtocol": "http", "logPrompts": False}
        if provider == "gemini_cli":
            settings["traces"] = False
        existing["telemetry"] = settings
        proposed = json.dumps(existing, ensure_ascii=False, indent=2) + "\n"
    # Never print the whole existing configuration: it may contain credentials.
    print(f"Proposed {provider} telemetry configuration: {path}; local HTTP/JSON port {port}; prompt capture disabled")
    if input("Apply with backup? Type YES: ").strip() != "YES":
        return {"changed": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        backup = path.with_name(path.name + f".devflight-{time.time_ns()}-{secrets.token_hex(4)}.bak")
        shutil.copy2(path, backup)
    temp = path.with_name(path.name + ".devflight-" + secrets.token_hex(8) + ".tmp")
    with temp.open("x", encoding="utf-8") as stream:
        stream.write(proposed)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    return {"changed": True, "backup": str(backup) if backup else None,
            "delivery_verified":False,
            "next_step":"Configure the per-user ingestion Bearer header in the provider's supported settings, then verify one exact event ID. Endpoint configuration alone does not verify delivery."}
