"""Import visible structured output only. Unknown records are retained verbatim."""
import json

def import_record(trace, source, record):
    kind = record.get("type", "unknown")
    if source == "codex" and kind == "thread.started" and record.get("thread_id"):
        trace.session_id = record["thread_id"]
    elif source == "claude" and record.get("session_id"):
        trace.session_id = record["session_id"]
    model = record.get("model") or record.get("message", {}).get("model")
    if isinstance(model, str): trace.agent["model"] = model
    trace.agent["framework"] = source
    event_type = "provider.event"
    if source == "codex":
        item = record.get("item", {})
        item_type = item.get("type")
        if item_type == "agent_message":
            event_type = "llm.response"
        elif item_type in ("command_execution", "mcp_tool_call", "web_search"):
            event_type = "tool.started" if kind == "item.started" else "tool.result"
        elif item_type == "file_change":
            event_type = "artifact.observed"
        elif kind in ("error", "turn.failed"):
            event_type = "error"
        elif kind == "turn.completed":
            event_type = "llm.usage"
    elif source == "claude":
        event_type = {"assistant": "llm.response", "user": "llm.request", "result": "provider.result"}.get(kind, event_type)
        for block in record.get("message", {}).get("content", []) if isinstance(record.get("message", {}).get("content"), list) else []:
            if block.get("type") in ("tool_use", "tool_result"):
                trace.emit("tool.started" if block["type"] == "tool_use" else "tool.result", block)
    elif source == "generic":
        event_type = record.get("event_type", "provider.event")
    status = "error" if event_type == "error" or record.get("is_error") or record.get("item", {}).get("status") == "failed" else "ok"
    data = {"source": source, "record": record}
    # Canonical usage is emitted once per Codex turn or Claude session result.
    # Assistant-message usage remains raw to avoid counting it twice downstream.
    if (source == "codex" and kind == "turn.completed") or (source == "claude" and kind == "result"):
        usage = record.get("usage") or {}
        data["usage"] = {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
            "cached_input_tokens": usage.get("cached_input_tokens", usage.get("cache_read_input_tokens")),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "cost_usd": record.get("total_cost_usd"), "scope": "turn" if source == "codex" else "session"}
        event_type = "llm.usage"
    return trace.emit(event_type, data, status)

def import_file(trace, source, path):
    count = 0
    with open(path, encoding="utf-8-sig") as f:
        for line_number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("Expected object")
                import_record(trace, source, record)
            except (ValueError, TypeError) as error:
                trace.emit("error", {"source": source, "line": line_number, "raw": line, "error": str(error)}, "error")
            count += 1
    return count
