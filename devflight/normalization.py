"""Provider-aware telemetry normalization shared by ingestion and historical readers.

This module describes the *reported origin* of an event. Authentication is added by
Store afterwards and never comes from a producer's payload. Content (prompts,
commands, tool output) is deliberately not copied into analytics dimensions.
"""
import datetime as dt
import hashlib
import json
import math
import re
from decimal import Decimal, InvalidOperation

from .core import redact


NUMBER_FIELDS = {
    "input_tokens": ("input_tokens", "input_token_count", "prompt_tokens", "gen_ai.usage.input_tokens"),
    "output_tokens": ("output_tokens", "output_token_count", "completion_tokens", "gen_ai.usage.output_tokens"),
    "cached_tokens": ("cached_tokens", "cached_input_tokens", "cached_token_count", "cache_read_input_tokens", "cache_read_tokens", "gen_ai.usage.cache_read.input_tokens"),
    "cache_creation_tokens": ("cache_creation_tokens", "cache_creation_input_tokens", "cache_write_token_count", "gen_ai.usage.cache_creation.input_tokens"),
    "reasoning_tokens": ("reasoning_tokens", "reasoning_token_count", "reasoning_output_tokens"),
    "duration_ms": ("duration_ms", "duration.ms"),
    "observed_cost_usd": ("observed_cost_usd", "cost_usd", "total_cost_usd"),
}
ORIGIN_IDS = ("origin_user_id", "developer_id", "developer.id", "user.id", "enduser.id", "user.account_id")
ORIGIN_NAMES = ("origin_user_name", "developer_name", "developer.name", "user.name", "enduser.name")
SAFE_ATTRIBUTES = frozenset({
    *ORIGIN_IDS, *ORIGIN_NAMES, "service.name", "service.version", "service.instance.id",
    "agent.name", "agent.id", "gen_ai.agent.name", "gen_ai.agent.id", "gen_ai.system",
    "gen_ai.provider.name", "provider_name", "gen_ai.request.model", "gen_ai.response.model",
    "model", "session.id", "session_id", "conversation.id", "thread.id", "event.name",
    "event.kind", "event.id", "event_id", "event.sequence", "request_id", "request.id",
    "gen_ai.response.id", "client_request_id", "turn.id", "call_id", "tool_use_id",
    "gen_ai.tool.name", "tool.name", "tool_name", "success", "status", "status_code",
    "http.response.status_code", "error.type", "error_type", "project.id", "team.id",
    "activity_kind", "synthetic", "usage.scope", "scope", "cost_usd_micros",
    "cache_creation_5m_tokens", "cache_creation_1h_tokens", "type", "unit",
    "aggregationTemporality", "isMonotonic", "speed", "effort",
    *(name for aliases in NUMBER_FIELDS.values() for name in aliases),
})


def text(value, limit=256):
    return redact(value[:limit]) if isinstance(value, str) and value else None


def number(value, field, *, integer=False, nonnegative=True):
    """Parse OTLP numeric strings without accepting booleans, NaN or infinity."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Invalid numeric field: " + field)
    if isinstance(value, str) and (len(value) > 128 or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value.strip())):
        raise ValueError("Invalid numeric field: " + field)
    try:
        parsed = Decimal(str(value).strip())
    except InvalidOperation as error:
        raise ValueError("Invalid numeric field: " + field) from error
    if not parsed.is_finite() or (nonnegative and parsed < 0):
        raise ValueError("Invalid numeric field: " + field)
    if integer:
        if parsed != parsed.to_integral_value() or abs(parsed) > 2**64 - 1:
            raise ValueError("Invalid integer field: " + field)
        return int(parsed)
    result = float(parsed)
    if not math.isfinite(result):
        raise ValueError("Invalid numeric field: " + field)
    return result


def attributes(items):
    if items is None:
        return {}
    if not isinstance(items, list):
        raise ValueError("OTLP attributes must be an array")
    result = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not isinstance(item.get("value"), dict):
            raise ValueError("Invalid OTLP attribute")
        value = item["value"]
        if "stringValue" in value:
            result[item["key"]] = value["stringValue"]
        elif "intValue" in value:
            result[item["key"]] = number(value["intValue"], item["key"], integer=True, nonnegative=False)
        elif "doubleValue" in value:
            result[item["key"]] = number(value["doubleValue"], item["key"], nonnegative=False)
        elif "boolValue" in value:
            if not isinstance(value["boolValue"], bool):
                raise ValueError("Invalid OTLP boolean attribute")
            result[item["key"]] = value["boolValue"]
        # Nested AnyValues are content rather than identity/consumption dimensions.
    return result


def safe_attributes(values):
    result = {}
    for key, value in values.items():
        if key not in SAFE_ATTRIBUTES or value is None:
            continue
        if isinstance(value, str):
            result[key] = text(value, 1024)
        elif isinstance(value, (bool, int, float)):
            if not isinstance(value, float) or math.isfinite(value):
                result[key] = value
    return redact(result)


def _pick(containers, keys):
    for prefix, values in containers:
        for key in keys:
            if values.get(key) is not None and values[key] != "":
                return values[key], prefix + key
    return None, None


def _provider(service):
    if not isinstance(service, str):
        return None
    normalized = service.lower().replace("-", "_")
    for key, provider in (("codex", "openai"), ("claude", "anthropic"), ("gemini", "google"), ("qwen", "qwen")):
        if key in normalized:
            return provider
    return service


def _boolean(value):
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    return None


def _time_from_nano(value):
    nano = number(value, "timeUnixNano", integer=True)
    seconds, remainder = divmod(nano, 1_000_000_000)
    try:
        instant = dt.datetime.fromtimestamp(seconds, dt.timezone.utc) + dt.timedelta(microseconds=remainder // 1000)
    except (ValueError, OverflowError, OSError) as error:
        raise ValueError("Invalid OTLP timestamp") from error
    return instant.isoformat(), str(nano)


def normalize_event(body):
    """Return safe flat dimensions for either the public SDK envelope or flat API."""
    if not isinstance(body, dict):
        raise ValueError("Expected an event object")
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    agent = body.get("agent") if isinstance(body.get("agent"), dict) else {}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    if isinstance(body.get("usage"), dict):
        usage = {**usage, **body["usage"]}
    attrs = body.get("safe_attributes") if isinstance(body.get("safe_attributes"), dict) else {}
    containers = [("", body), ("data.", data), ("usage.", usage), ("attributes.", attrs)]
    provenance = {}
    def select(field, keys=None, sources=None):
        value, source = _pick(sources or containers, keys or (field,))
        if source:
            provenance[field] = source
        return value
    row = {"normalization_version": 2}
    for field in ("provider", "model", "session_id", "run_id", "activity_kind", "provenance", "file_path", "file_sha256", "project_id"):
        row[field] = text(select(field))
    row["origin_project_id"] = text(select("origin_project_id", ("origin_project_id", "project.id")))
    if body.get("schema_version") == 1 and isinstance(body.get("agent"), dict) and "data" in body:
        # The legacy Trace SDK's project_id describes its external repository,
        # not an authenticated local projects-table primary key.
        row["origin_project_id"] = row["origin_project_id"] or row["project_id"]
        row["project_id"] = text(body.get("platform_project_id"))
    row["agent"] = text(body.get("agent") if isinstance(body.get("agent"), str) else agent.get("id") or agent.get("name") or body.get("agent_id"))
    row["agent_id"] = text(body.get("agent_id") or agent.get("id") or attrs.get("agent.id") or attrs.get("gen_ai.agent.id"))
    if row["agent"]:
        provenance["agent"] = "agent" if isinstance(body.get("agent"), str) else "agent.id"
    if not row["model"]:
        row["model"] = text(agent.get("model"))
        if row["model"]:
            provenance["model"] = "agent.model"
    if not row["provider"]:
        known = {"codex", "claude", "claude_code", "gemini_cli", "qwen_code", "openai", "anthropic"}
        source = data.get("source")
        framework = agent.get("framework")
        hint = source if isinstance(source,str) and source in known else framework if isinstance(framework,str) and framework in known else row["agent"]
        row["provider"] = text(agent.get("provider")) or _provider(hint)
        if row["provider"]:
            provenance["provider"] = "agent.provider" if agent.get("provider") else "source/framework/service.name fallback"
    for field in ("trace_id", "span_id", "parent_span_id"):
        row[field] = text(select(field, sources=[("", body), ("context.", context)]))
    row["event_type"] = text(select("event_type", ("event_type", "event.name", "eventName"))) or "event"
    row["event_kind"] = text(select("event_kind", ("event_kind", "event.kind")))
    row["tool"] = text(select("tool", ("tool", "gen_ai.tool.name", "tool.name", "tool_name")))
    if not row["tool"] and row["event_type"].startswith("tool."):
        row["tool"] = text(data.get("name"))
        if row["tool"]:
            provenance["tool"] = "data.name"
    row["error_type"] = text(select("error_type", ("error_type", "error.type")))
    source_status = select("status")
    success = _boolean(select("success"))
    error_hint = select("error", ("error.message", "error"))
    if source_status in ("error", "failed", "failure", "timeout") or success is False or row["error_type"] or error_hint:
        row["status"] = "error"
        row["error_type"] = row["error_type"] or ("Timeout" if source_status == "timeout" else "ProviderError")
    elif source_status in ("ok", "success", "succeeded") or success is True:
        row["status"] = "ok"
    else:
        row["status"] = text(source_status)
    for field, aliases in NUMBER_FIELDS.items():
        row[field] = number(select(field, aliases), field, integer=field.endswith("tokens"))
    if row["duration_ms"] is None and data.get("seconds") is not None:
        row["duration_ms"] = number(data["seconds"], "seconds") * 1000
        provenance["duration_ms"] = "data.seconds * 1000"
    if row["observed_cost_usd"] is None:
        micros = select("cost_usd_micros")
        if micros is not None:
            row["observed_cost_usd"] = number(micros, "cost_usd_micros", integer=True) / 1_000_000
            provenance["observed_cost_usd"] = "cost_usd_micros / 1000000"
    origin_id = select("origin_user_id", ORIGIN_IDS)
    row["origin_user_id"] = str(origin_id) if isinstance(origin_id,int) and not isinstance(origin_id,bool) else text(origin_id)
    row["origin_user_name"] = text(select("origin_user_name", ORIGIN_NAMES))
    row["origin_id_source"] = text(body.get("origin_id_source")) or provenance.get("origin_user_id") or provenance.get("origin_user_name")
    row["origin_identity_verified"] = False
    row["source_event_id"] = text(select("source_event_id", ("source_event_id", "event_id", "event.id")), 512)
    supplied_id, _ = _pick(containers, ("source_event_id", "event_id", "event.id"))
    if isinstance(supplied_id, str) and len(supplied_id) > 512:
        raise ValueError("Event identity exceeds 512 characters")
    row["event_id"] = row["source_event_id"]
    row["request_id"] = text(select("request_id", ("request_id", "request.id", "gen_ai.response.id", "client_request_id")))
    row["canonical_id"] = text(body.get("canonical_id"), 512) or row["source_event_id"]
    scope = text(select("usage_kind", ("usage_kind", "scope", "usage.scope")))
    row["usage_kind"] = {"turn": "request", "session": "session_total"}.get(scope, scope)
    if not row["usage_kind"] and any(row[field] is not None for field in ("input_tokens", "output_tokens", "observed_cost_usd")):
        row["usage_kind"] = "event"
    if row["usage_kind"] in ("span", "metric_sample", "log"):
        for field in NUMBER_FIELDS:
            if field != "duration_ms":
                row[field] = None
    row["synthetic"] = body.get("synthetic") is True or data.get("synthetic") is True
    row["safe_attributes"] = safe_attributes(attrs)
    for field in ("timestamp", "occurred_at_unix_nano"):
        if body.get(field) is not None:
            row[field] = body[field]
            provenance[field] = field
    for field in ("metric_name", "metric_type", "metric_unit", "metric_temporality", "metric_start_unix_nano", "metric_time_unix_nano"):
        row[field] = text(body.get(field))
    for field in ("metric_value", "metric_sum", "metric_min", "metric_max", "metric_count"):
        row[field] = number(body.get(field), field, integer=field == "metric_count", nonnegative=field == "metric_count")
    metric_data = body.get("metric_data")
    row["metric_data"] = _safe_metric_data(metric_data) if metric_data is not None else None
    row["evaluation"] = _evaluation(body.get("evaluation") or (data if row["event_type"] == "eval.grade" else None))
    inherited = body.get("field_provenance")
    if isinstance(inherited, dict):
        provenance.update({key: text(value) for key, value in inherited.items() if key in row and isinstance(value, str)})
    row["field_provenance"] = provenance
    return redact(row)


def _evaluation(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("evaluation must be an object")
    result = {}
    for key in ("recipe", "variant", "dataset", "split", "suite_version", "hardware", "task_kind", "model"):
        if value.get(key) is not None:
            result[key] = text(value[key], 256)
    for key in ("accuracy", "seconds", "tokens", "count", "sample_size", "successes", "failures", "cost_usd"):
        if value.get(key) is not None:
            result[key] = number(value[key], "evaluation." + key, integer=key in ("tokens", "count", "sample_size", "successes", "failures"))
    for key in ("success", "no_reveal"):
        if key in value:
            if not isinstance(value[key], bool):
                raise ValueError("Invalid evaluation boolean: " + key)
            result[key] = value[key]
    config = value.get("recipe_config")
    if isinstance(config, dict):
        allowed = ("name", "model", "backend", "prompt_id", "prompt_version", "rag_k", "temperature", "max_tokens")
        result["recipe_config"] = {key: redact(config[key]) for key in allowed if key in config and isinstance(config[key], (str, int, float, bool))}
        # Comparability remains testable without retaining a private prompt.
        result["recipe_config_hash"] = value.get("recipe_config_hash") or hashlib.sha256(json.dumps(config, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()
    elif isinstance(value.get("recipe_config_hash"), str):
        result["recipe_config_hash"] = text(value["recipe_config_hash"])
    breakdown = value.get("breakdown")
    if isinstance(breakdown, dict):
        result["breakdown"] = {}
        for label, item in list(breakdown.items())[:100]:
            if isinstance(label, str) and isinstance(item, dict):
                numeric = {key: number(item[key], "breakdown."+key, integer=key in ("count", "sample_size", "successes", "failures", "tokens"))
                           for key in ("accuracy", "count", "sample_size", "successes", "failures", "seconds", "tokens") if item.get(key) is not None}
                if numeric:
                    result["breakdown"][text(label, 80)] = numeric
    return redact(result)


def _safe_metric_data(data):
    """Retain typed metric values and distributions, never arbitrary content."""
    if not isinstance(data, dict):
        raise ValueError("metric_data must be an object")
    result = {}
    signed = {"value", "sum", "min", "max", "asDouble"}
    integers = {"count", "zeroCount", "flags", "scale", "asInt"}
    for key in signed | integers | {"zeroThreshold"}:
        if data.get(key) is not None:
            result[key] = number(data[key], "metric." + key, integer=key in integers,
                                 nonnegative=key not in signed | {"scale", "asInt"})
    for key in ("timeUnixNano", "startTimeUnixNano"):
        if data.get(key) is not None:
            result[key] = str(number(data[key], key, integer=True))
    for key in ("explicitBounds", "bucketCounts"):
        if key in data:
            if not isinstance(data[key], list):
                raise ValueError("Invalid metric " + key)
            result[key] = [number(v, key, integer=key == "bucketCounts", nonnegative=key == "bucketCounts") for v in data[key]]
    if "explicitBounds" in result and "bucketCounts" in result and len(result["bucketCounts"]) != len(result["explicitBounds"]) + 1:
        raise ValueError("Histogram bucket count does not match explicit bounds")
    for key in ("positive", "negative"):
        if key in data:
            buckets = data[key]
            if not isinstance(buckets, dict) or not isinstance(buckets.get("bucketCounts", []), list):
                raise ValueError("Invalid exponential histogram buckets")
            result[key] = {"offset": number(buckets.get("offset", 0), "offset", integer=True, nonnegative=False),
                           "bucketCounts": [number(v, "bucketCounts", integer=True) for v in buckets.get("bucketCounts", [])]}
    if "quantileValues" in data:
        if not isinstance(data["quantileValues"], list):
            raise ValueError("Invalid summary quantiles")
        result["quantileValues"] = []
        for item in data["quantileValues"]:
            if not isinstance(item, dict):
                raise ValueError("Invalid summary quantile")
            q = number(item.get("quantile"), "quantile")
            value = number(item.get("value"), "quantile.value", nonnegative=False)
            if q is None or q > 1 or value is None:
                raise ValueError("Invalid summary quantile")
            result["quantileValues"].append({"quantile": q, "value": value})
    if "aggregationTemporality" in data:
        result["aggregationTemporality"] = _temporality(data["aggregationTemporality"])
    if "isMonotonic" in data:
        if not isinstance(data["isMonotonic"], bool):
            raise ValueError("Invalid metric isMonotonic")
        result["isMonotonic"] = data["isMonotonic"]
    if "exemplars" in data:
        if not isinstance(data["exemplars"], list):
            raise ValueError("Invalid metric exemplars")
        result["exemplars"] = []
        for exemplar in data["exemplars"]:
            if not isinstance(exemplar, dict):
                raise ValueError("Invalid metric exemplar")
            result["exemplars"].append({
                **_safe_metric_data({k: exemplar[k] for k in ("asInt", "asDouble", "timeUnixNano") if k in exemplar}),
                "traceId": text(exemplar.get("traceId")), "spanId": text(exemplar.get("spanId")),
                "attributes": safe_attributes(exemplar["attributes"] if isinstance(exemplar.get("attributes"),dict) else attributes(exemplar.get("filteredAttributes", []))),
            })
    return result


def _temporality(value):
    names = {0: "unspecified", 1: "delta", 2: "cumulative", "0": "unspecified", "1": "delta", "2": "cumulative",
             "AGGREGATION_TEMPORALITY_UNSPECIFIED": "unspecified", "AGGREGATION_TEMPORALITY_DELTA": "delta",
             "AGGREGATION_TEMPORALITY_CUMULATIVE": "cumulative", "unspecified": "unspecified", "delta": "delta", "cumulative": "cumulative"}
    if not isinstance(value, (str, int)) or isinstance(value, bool) or value not in names:
        raise ValueError("Invalid aggregation temporality")
    return names[value]


def normalize_otlp(signal, body):
    """Return one safe event per log/span/datapoint, rejecting unsupported records."""
    field, scope_names, record_name = {
        "logs": ("resourceLogs", ("scopeLogs", "instrumentationLibraryLogs"), "logRecords"),
        "traces": ("resourceSpans", ("scopeSpans", "instrumentationLibrarySpans"), "spans"),
        "metrics": ("resourceMetrics", ("scopeMetrics", "instrumentationLibraryMetrics"), "metrics"),
    }.get(signal, (None, (), None))
    if not field or not isinstance(body, dict) or not isinstance(body.get(field), list):
        raise ValueError("Invalid OTLP envelope")
    def objects(items, label):
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("Invalid OTLP " + label)
        return items
    rows = []
    for resource in objects(body[field], field):
        resource_info = resource.get("resource", {})
        if not isinstance(resource_info, dict):
            raise ValueError("Invalid OTLP resource")
        base = attributes(resource_info.get("attributes", []))
        for scope_name in scope_names:
            for scope in objects(resource.get(scope_name, []), scope_name):
                scope_info = scope.get("scope", scope.get("instrumentationLibrary", {}))
                if not isinstance(scope_info, dict):
                    raise ValueError("Invalid OTLP scope")
                scoped = {**base, **attributes(scope_info.get("attributes", []))}
                for record in objects(scope.get(record_name, []), record_name):
                    record_attrs = {**scoped, **attributes(record.get("attributes", []))}
                    points = [(None, {}, record)]
                    if signal == "metrics":
                        kinds = [kind for kind in ("sum", "gauge", "histogram", "exponentialHistogram", "summary") if kind in record]
                        if len(kinds) != 1 or not isinstance(record[kinds[0]], dict):
                            raise ValueError("Unsupported or ambiguous OTLP metric type")
                        kind = kinds[0]
                        metric = record[kind]
                        points = [(kind, metric, point) for point in objects(metric.get("dataPoints", []), "dataPoints")]
                    for kind, metric, point in points:
                        a = {**record_attrs, **attributes(point.get("attributes", []))}
                        event_type = record.get("eventName") or a.get("event.name") or record.get("name") or "otel." + signal
                        event_kind = a.get("event.kind")
                        event = {"event_type": event_type, "event_kind": event_kind,
                                 "agent": a.get("agent.name") or a.get("gen_ai.agent.name") or a.get("service.name"),
                                 "agent_id": a.get("agent.id") or a.get("gen_ai.agent.id"),
                                 "provider": a.get("gen_ai.provider.name") or a.get("gen_ai.system") or a.get("provider_name") or _provider(a.get("service.name")),
                                 "model": a.get("gen_ai.response.model") or a.get("gen_ai.request.model") or a.get("model"),
                                 "session_id": a.get("session.id") or a.get("session_id") or a.get("conversation.id") or a.get("thread.id"),
                                 "trace_id": record.get("traceId"), "span_id": record.get("spanId"), "parent_span_id": record.get("parentSpanId"),
                                 "safe_attributes": safe_attributes(a), "activity_kind": "agent", "provenance": "official-otlp-" + signal,
                                 "tool": a.get("gen_ai.tool.name") or a.get("tool.name") or a.get("tool_name"),
                                 "error_type": a.get("error.type") or a.get("error_type"), "success": a.get("success"),
                                 "request_id": a.get("request_id") or a.get("request.id") or a.get("gen_ai.response.id") or a.get("client_request_id"),
                                 "synthetic": _boolean(a.get("synthetic")) is True,
                                 "field_provenance": {"provider": "OTLP attribute or service.name fallback", "agent": "OTLP resource/record attribute"}}
                        # Error text is inspected for classification but never persisted.
                        status = record.get("status", {})
                        if not isinstance(status, dict):
                            raise ValueError("Invalid OTLP status")
                        severity = number(record.get("severityNumber", 0), "severityNumber", integer=True) or 0
                        http_status = a.get("http.response.status_code", a.get("status_code"))
                        if status.get("code") in (2, "STATUS_CODE_ERROR") or severity >= 17 or (http_status is not None and number(http_status, "status_code", integer=True) >= 400) or a.get("error.message") or a.get("error") or str(event_type).endswith((".api_error", ".error")):
                            event["status"] = "error"
                        elif status.get("code") in (1, "STATUS_CODE_OK"):
                            event["status"] = "ok"
                        nano = point.get("timeUnixNano") or record.get("startTimeUnixNano") or point.get("observedTimeUnixNano")
                        if nano is not None:
                            event["timestamp"], event["occurred_at_unix_nano"] = _time_from_nano(nano)
                        origin, origin_source = _pick([("attributes.", a)], ORIGIN_IDS)
                        origin_name, name_source = _pick([("attributes.", a)], ORIGIN_NAMES)
                        event.update(origin_user_id=origin, origin_user_name=origin_name, origin_id_source=origin_source or name_source)
                        name = str(event_type).lower()
                        usage_log = signal == "logs" and (
                            name in ("usage", "llm.usage", "turn.completed") or
                            name.endswith((".api_request", ".api_response", ".usage", ".turn.completed")) or
                            name == "codex.sse_event" and event_kind == "response.completed")
                        if usage_log:
                            for field_name, aliases in NUMBER_FIELDS.items():
                                value, source = _pick([("attributes.", a)], aliases)
                                if value is not None:
                                    event[field_name] = number(value, field_name, integer=field_name.endswith("tokens"))
                                    event["field_provenance"][field_name] = source
                            if event.get("observed_cost_usd") is None and a.get("cost_usd_micros") is not None:
                                event["observed_cost_usd"] = number(a["cost_usd_micros"], "cost_usd_micros", integer=True) / 1_000_000
                                event["field_provenance"]["observed_cost_usd"] = "attributes.cost_usd_micros / 1000000"
                            event["usage_kind"] = "request"
                        else:
                            event["usage_kind"] = "metric_sample" if signal == "metrics" else "span" if signal == "traces" else "log"
                        if a.get("duration_ms") is not None:
                            event["duration_ms"] = number(a["duration_ms"], "duration_ms")
                        if record.get("endTimeUnixNano") is not None and record.get("startTimeUnixNano") is not None:
                            event["duration_ms"] = (number(record["endTimeUnixNano"], "endTimeUnixNano", integer=True) - number(record["startTimeUnixNano"], "startTimeUnixNano", integer=True)) / 1e6
                            if event["duration_ms"] < 0:
                                raise ValueError("Span ends before it starts")
                        if kind:
                            dimensions = _safe_metric_data({**point, **{k: metric[k] for k in ("aggregationTemporality", "isMonotonic") if k in metric}})
                            value = dimensions.get("asInt", dimensions.get("asDouble"))
                            if kind in ("sum", "gauge") and value is None and not dimensions.get("flags", 0) & 1:
                                raise ValueError("OTLP " + kind + " datapoint has no numeric value")
                            event.update(metric_name=text(record.get("name")), metric_type=kind, metric_unit=text(record.get("unit")),
                                         metric_value=value, metric_count=dimensions.get("count"), metric_sum=dimensions.get("sum"),
                                         metric_min=dimensions.get("min"), metric_max=dimensions.get("max"),
                                         metric_temporality=dimensions.get("aggregationTemporality"),
                                         metric_start_unix_nano=dimensions.get("startTimeUnixNano"),
                                         metric_time_unix_nano=dimensions.get("timeUnixNano"), metric_data=dimensions)
                        stable_record = {k: v for k, v in record.items() if k != "observedTimeUnixNano" or not record.get("timeUnixNano")}
                        if kind:
                            # A datapoint keeps its ID when an exporter batches it
                            # with different neighbours on a later retry.
                            stable_record = {key:value for key,value in record.items() if key != kind}
                            stable_record[kind] = {key:value for key,value in metric.items() if key != "dataPoints"}
                        stable_point = {k: v for k, v in point.items() if k != "observedTimeUnixNano" or not point.get("timeUnixNano")}
                        source_id = a.get("event.id") or a.get("event_id")
                        if not isinstance(source_id, str) or not source_id:
                            source_id = "otlp:" + hashlib.sha256(json.dumps({"signal": signal, "resource": base, "scope": scope_info, "record": stable_record, "point": stable_point}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                        event.update(event_id=source_id, source_event_id=source_id, canonical_id=source_id)
                        normalized = normalize_event(event)
                        # safe_attributes contain raw numeric values too; they must
                        # not re-promote noncanonical spans/metric samples as usage.
                        if not usage_log:
                            for field_name in NUMBER_FIELDS:
                                if field_name != "duration_ms":
                                    normalized[field_name] = None
                        rows.append(normalized)
    return rows
