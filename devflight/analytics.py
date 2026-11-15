"""Schema-aware SQL analytics across an explicitly authorized RawTree source.

Native tables are projected at query time; historical payloads are not copied to
the local identity database. Unknown measurements stay NULL. Deduplication only
uses explicit producer IDs, never an assumed equivalence between logs and spans.
"""
import datetime as dt
import hashlib
import inspect
import json
import math
import threading
import time
import urllib.error

from .rawtree import RawTree
from .shared import ALL_TABLES, EVENT_TABLES, SharedSource


def literal(value):
    if not isinstance(value, str) or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid query filter")
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def quote(name):
    return chr(96) + name.replace(chr(96), chr(96) * 2) + chr(96)


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: finite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [finite(item) for item in value]
    return value


def invoke(method, *args, deadline=None):
    """Pass deadlines to real clients, preserving explicit small test clients."""
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("Analytics deadline exhausted")
    parameters = inspect.signature(method).parameters
    if deadline is not None and (
        "deadline" in parameters
        or any(p.kind == p.VAR_KEYWORD for p in parameters.values())
    ):
        return method(*args, deadline=deadline)
    return method(*args)


FILTERS = (
    "session_id", "provider", "project_id", "model", "user_id", "team_id",
    "run_id", "activity_kind", "origin_user_id", "agent", "agent_id", "event_id",
    "source_event_id", "canonical_id", "request_id", "origin_project_id", "usage_kind",
)
DIMENSIONS = (
    "event_id", "source_event_id", "canonical_id", "timestamp", "org_id", "user_id", "team_id",
    "origin_user_id", "origin_user_name", "origin_id_source", "ingest_user_id", "ingest_org_id",
    "session_id", "trace_id", "span_id", "parent_span_id", "provider", "agent",
    "model", "project_id", "origin_project_id", "agent_id", "run_id", "event_type", "event_kind", "tool", "error_type", "status",
    "activity_kind", "provenance", "request_id", "metric_name", "metric_type",
    "metric_unit", "metric_temporality", "metric_start_unix_nano", "metric_time_unix_nano",
    "metric_data", "field_provenance", "occurred_at_unix_nano", "usage_kind", "file_path", "file_sha256",
)
NUMBERS = (
    "occurred_at_epoch", "duration_ms", "input_tokens", "output_tokens",
    "cached_tokens", "cache_creation_tokens", "reasoning_tokens", "observed_cost_usd",
    "metric_value", "metric_count", "metric_sum", "metric_min", "metric_max", "normalization_version",
)
CANONICAL_COLUMNS = set(DIMENSIONS + NUMBERS + ("synthetic", "event_json"))
NULL_TEXT = "CAST(NULL AS Nullable(String))"
NULL_NUMBER = "CAST(NULL AS Nullable(Float64))"


class Projection:
    """Only columns returned by RawTree metadata may appear in a projection."""
    def __init__(self, table, columns):
        self.table = table
        self.columns = columns

    def _names(self, names):
        # Native OTLP transforms differ in whether attributes are flattened or
        # nested. Every candidate still has to exist in live table metadata.
        result=[]
        for name in names:
            for candidate in (name,"attributes."+name,"resource.attributes."+name,"resourceAttributes."+name,"resource."+name):
                if candidate in self.columns and candidate not in result:
                    result.append(candidate)
        return result

    def text(self, *names):
        parts = [
            "nullIf(toString(" + self.table + "." + quote(name) + "),'')"
            for name in self._names(names)
        ]
        if not parts:
            return NULL_TEXT
        return parts[0] if len(parts) == 1 else "coalesce(" + ",".join(parts) + ")"

    def number(self, *names):
        parts=[]
        for name in self._names(names):
            parsed="toFloat64OrNull(toString("+self.table+"."+quote(name)+"))"
            parts.append("if(isFinite("+parsed+"),"+parsed+","+NULL_NUMBER+")")
        if not parts:
            return NULL_NUMBER
        return parts[0] if len(parts) == 1 else "coalesce(" + ",".join(parts) + ")"

    def epoch(self):
        parts = []
        if "occurred_at_epoch" in self.columns:
            parts.append(self.number("occurred_at_epoch"))
        for name in ("occurred_at_unix_nano", "timeUnixNano", "startTimeUnixNano", "time_unix_nano", "metric_time_unix_nano"):
            if name in self.columns:
                parts.append("(" + self.number(name) + "/1000000000)")
        for name in ("timestamp", "created_at", "event.timestamp"):
            if name in self.columns:
                parts.append(
                    "(toUnixTimestamp64Milli(parseDateTime64BestEffortOrNull("
                    + self.text(name) + ",3,'UTC'))/1000)"
                )
        return ("coalesce(" + ",".join(parts) + ")" if len(parts) > 1
                else parts[0] if parts else NULL_NUMBER)

    def expressions(self):
        text, number = self.text, self.number
        event_type = text("event_type", "eventName", "event.name", "name")
        kind = text("event.kind", "event_kind")
        normalized = self.table == "dev_platform_events"
        metric = self.table == "dev_metrics"
        # Match completed consumption events, not similarly named raw body logs.
        usage_log = (
            "(lowerUTF8(ifNull(" + event_type + ",'')) IN ('usage','llm.usage','turn.completed')"
            " OR endsWith(lowerUTF8(ifNull(" + event_type + ",'')),'.usage')"
            " OR endsWith(lowerUTF8(ifNull(" + event_type + ",'')),'.api_request')"
            " OR endsWith(lowerUTF8(ifNull(" + event_type + ",'')),'.api_response')"
            " OR endsWith(lowerUTF8(ifNull(" + event_type + ",'')),'.turn.completed')"
            " OR (" + event_type + "='codex.sse_event' AND " + kind + "='response.completed'))"
        )
        usage_scope=text("usage_kind","data.usage_kind","data.usage.scope","usage.scope")
        usage_kind=("multiIf("+usage_scope+"='session','session_total',"+usage_scope+"='turn','request',"
                    +"isNotNull("+usage_scope+"),"+usage_scope+","
                    +literal(self.table)+"='dev_metrics','metric_sample',"
                    +literal(self.table)+"='dev_traces','span',"+usage_log+",'request',"
                    +literal(self.table)+"='dev_logs','log','event')")
        origin_names=("origin_user_id","developer_id","developer.id","user.id","user.account_uuid","user.account_id","enduser.id")
        if not normalized:
            origin_names+= ("user_id",)
        provider=text("provider","gen_ai.provider.name","gen_ai.system","provider_name")
        service=text("service.name","data.source","agent.framework","agent.id","agent")
        provider_fallback=("multiIf(positionCaseInsensitive(ifNull("+service+",''),'codex')>0,'openai',"
                           "positionCaseInsensitive(ifNull("+service+",''),'claude')>0,'anthropic',"
                           "positionCaseInsensitive(ifNull("+service+",''),'gemini')>0,'google',"
                           "positionCaseInsensitive(ifNull("+service+",''),'qwen')>0,'qwen',"+service+")")
        expressions = {name: text(name) for name in DIMENSIONS}
        expressions.update({
            "source_event_id": text("source_event_id", "canonical_id", "event_id", "event.id"),
            "canonical_id": text("canonical_id","source_event_id","event_id","event.id"),
            "timestamp": text("timestamp", "event.timestamp", "created_at"),
            "occurred_at_unix_nano":text("occurred_at_unix_nano","timeUnixNano","startTimeUnixNano","metric_time_unix_nano"),
            "origin_user_id": text(*origin_names),
            "origin_user_name": text("origin_user_name", "developer_name", "developer.name", "user.name", "enduser.name"),
            "origin_id_source": "coalesce("+text("origin_id_source")+",if(isNotNull("+text(*origin_names)+"),"+literal("rawtree:"+self.table+":reported-origin")+","+NULL_TEXT+"))",
            "ingest_user_id": text("ingest_user_id", "user_id") if normalized else text("ingest_user_id"),
            "session_id": text("session_id", "session.id", "conversation.id", "thread.id"),
            "trace_id": text("trace_id", "traceId", "context.trace_id"),
            "span_id": text("span_id", "spanId", "context.span_id"),
            "parent_span_id": text("parent_span_id", "parentSpanId", "context.parent_span_id"),
            "provider": "coalesce("+provider+","+provider_fallback+")",
            "agent": text("agent.id", "agent.name", "gen_ai.agent.name", "agent", "agent_id", "service.name"),
            "agent_id": text("agent_id","agent.id","gen_ai.agent.id"),
            "model": text("model", "agent.model", "gen_ai.response.model", "gen_ai.request.model"),
            "event_type": "coalesce(" + event_type + "," + literal("otel.metrics" if metric else "event") + ")",
            "event_kind": kind,
            "tool": text("tool", "tool_name", "tool.name", "gen_ai.tool.name", "data.name"),
            "error_type": text("error_type", "error.type", "data.error_type"),
            "request_id": text("request_id", "request.id", "gen_ai.response.id", "response.id", "client_request_id"),
            "provenance": "coalesce(" + text("provenance") + "," + literal("rawtree:" + self.table) + ")",
            "activity_kind": "coalesce(" + text("activity_kind") + ",'agent')",
            "metric_name": text("metric_name", "name") if metric else text("metric_name"),
            "metric_type": text("metric_type","type") if metric else text("metric_type"),
            "metric_unit": text("metric_unit", "unit") if metric else text("metric_unit"),
            "usage_kind": usage_kind,
        })
        status = text("status", "data.status")
        status_code = number("status.code")
        severity = number("severityNumber")
        http_status = number("http.response.status_code","status_code")
        success = text("success", "data.success")
        expressions["status"] = (
            "multiIf(lowerUTF8(ifNull("+status+",'')) IN ('error','failed','failure','timeout')"
            " OR lowerUTF8(ifNull(" + success + ",'')) IN ('false','0')"
            " OR " + status_code + "=2 OR "+text("status.code")+"='STATUS_CODE_ERROR'"
            " OR " + severity + ">=17 OR "+http_status+">=400"
            " OR isNotNull("+expressions["error_type"]+")"
            " OR endsWith(ifNull("+event_type+",''),'.api_error'), 'error',"
            "lowerUTF8(ifNull("+status+",'')) IN ('ok','success','succeeded')"
            " OR lowerUTF8(ifNull("+success+",'')) IN ('true','1') OR "+status_code+"=1,'ok',"+NULL_TEXT+")"
        )
        duration = number("duration_ms", "data.duration_ms")
        if "endTimeUnixNano" in self.columns and "startTimeUnixNano" in self.columns:
            duration = "coalesce(" + duration + ",(" + number("endTimeUnixNano") + "-" + number("startTimeUnixNano") + ")/1000000)"
        if "data.seconds" in self.columns:
            duration = "coalesce(" + duration + "," + number("data.seconds") + "*1000)"
        expressions.update({name: number(name) for name in NUMBERS})
        expressions["occurred_at_epoch"] = self.epoch()
        epoch=expressions["occurred_at_epoch"]
        utc_stamp="concat(replaceOne(toString(fromUnixTimestamp64Milli(toInt64("+epoch+"*1000),'UTC')),' ','T'),'Z')"
        expressions["timestamp"]="if(isNotNull("+epoch+"),"+utc_stamp+","+expressions["timestamp"]+")"
        expressions["duration_ms"] = "if("+duration+">=0,"+duration+","+NULL_NUMBER+")"
        aliases = {
            "input_tokens": ("input_tokens", "gen_ai.usage.input_tokens", "input_token_count", "data.input_tokens", "data.usage.input_tokens", "usage.input_tokens"),
            "output_tokens": ("output_tokens", "gen_ai.usage.output_tokens", "output_token_count", "data.output_tokens", "data.usage.output_tokens", "usage.output_tokens"),
            "cached_tokens": ("cached_tokens", "cached_token_count", "cache_read_tokens", "cached_input_tokens", "data.cached_tokens", "data.usage.cached_input_tokens", "data.usage.cache_read_input_tokens", "gen_ai.usage.cache_read.input_tokens"),
            "cache_creation_tokens": ("cache_creation_tokens", "cache_creation_input_tokens", "cache_write_token_count", "data.cache_creation_tokens", "data.usage.cache_creation_input_tokens", "gen_ai.usage.cache_creation.input_tokens"),
            "reasoning_tokens": ("reasoning_tokens","reasoning_token_count","reasoning_output_tokens","data.usage.reasoning_output_tokens"),
            "observed_cost_usd": ("observed_cost_usd", "cost_usd", "data.observed_cost_usd", "data.cost_usd", "data.usage.cost_usd"),
        }
        for name, candidates in aliases.items():
            value = number(*candidates)
            if name=="observed_cost_usd":
                value="coalesce("+value+","+number("cost_usd_micros")+"/1000000)"
            valid=value+">=0"+(" AND "+value+"=floor("+value+")" if name.endswith("tokens") else "")
            value="if("+valid+","+value+","+NULL_NUMBER+")"
            if self.table == "dev_logs":
                value = "if(" + usage_log + "," + value + "," + NULL_NUMBER + ")"
            elif self.table == "dev_events_raw":
                value = "if("+usage_log+" OR "+usage_scope+" IN ('request','turn','event'),"+value+","+NULL_NUMBER+")"
            elif self.table in ("dev_traces", "dev_metrics"):
                value = NULL_NUMBER
            # Cumulative/session-wide summaries remain available as observations
            # but are never added to per-request usage in this projection.
            value="if("+usage_kind+" IN ('span','metric_sample','log','session_total','session','cumulative'),"+NULL_NUMBER+","+value+")"
            expressions[name] = value
        expressions["metric_value"] = number("metric_value", "asDouble", "asInt", "value") if metric else number("metric_value")
        if metric:
            for field,native in (("metric_count","count"),("metric_sum","sum"),("metric_min","min"),("metric_max","max")):
                expressions[field]=number(field,native)
            expressions["metric_start_unix_nano"]=text("metric_start_unix_nano","startTimeUnixNano")
            expressions["metric_time_unix_nano"]=text("metric_time_unix_nano","timeUnixNano")
            temporality=text("metric_temporality","aggregationTemporality","sum.aggregationTemporality","histogram.aggregationTemporality","exponentialHistogram.aggregationTemporality")
            expressions["metric_temporality"]=("multiIf("+temporality+" IN ('1','delta','AGGREGATION_TEMPORALITY_DELTA'),'delta',"
                                               +temporality+" IN ('2','cumulative','AGGREGATION_TEMPORALITY_CUMULATIVE'),'cumulative',"
                                               +temporality+" IN ('0','unspecified','AGGREGATION_TEMPORALITY_UNSPECIFIED'),'unspecified',"+NULL_TEXT+")")
        expressions["synthetic"] = "lowerUTF8(ifNull(" + text("synthetic", "data.synthetic") + ",'')) IN ('true','1')"
        expressions["source_table"] = literal(self.table)
        expressions["source_priority"] = str(0 if normalized else 1)
        # Only an explicit event identity supports cross-table deduplication.
        # Hashing complete raw rows is deliberately avoided (sensitive data).
        source_id = expressions["source_event_id"]
        expressions["dedup_key"] = (
            "if(isNotNull(" + source_id + "),concat('id:'," + source_id + "),"
            + NULL_TEXT + ")"
        )
        return expressions

    def select(self):
        return "SELECT " + ",".join(
            expression + " AS " + quote(name) for name, expression in self.expressions().items()
        ) + " FROM " + self.table


class Analytics:
    TOOLS = {"overview", "agents", "sessions", "errors", "usage", "people", "timeline", "trend", "experiments"}

    def __init__(self, client=None, store=None):
        self.client = client
        self.store = store
        self.shared = SharedSource(store) if store else None
        self._cache = {}
        self._lock = threading.RLock()

    def _client(self):
        return self.client or RawTree(read_only=True)

    def columns(self, table="dev_platform_events", deadline=None):
        if table not in ALL_TABLES:
            raise PermissionError("Table is not authorized")
        client = self._client()
        if not hasattr(client, "request"):
            return None  # Explicit minimal test clients, never a live assumption.
        key = ("schema", table)
        with self._lock:
            cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < 15:
            return cached[1]
        try:
            result = invoke(client.request, "/v1/query", {"sql": "SELECT * FROM " + table + " LIMIT 0"}, deadline=deadline)
            columns = {row["name"] for row in result.get("meta", [])}
        except urllib.error.HTTPError as error:
            message = error.read(4096).decode("utf-8", "replace").lower()
            if error.code in (400, 404) and any(
                pattern in message for pattern in ("unknown table", "does not exist", "table not found", "unknown_table")
            ):
                columns = set()
            else:
                raise RuntimeError("RawTree schema unavailable (HTTP " + str(error.code) + ")") from None
        with self._lock:
            self._cache[key] = (time.monotonic(), columns)
        return columns

    def effective_scope(self, identity, args=None):
        requested = (args or {}).get("source_scope")
        if self.shared:
            return self.shared.scope(identity, requested)
        if requested not in (None, "organization"):
            raise PermissionError("Shared-source access is not configured")
        return "organization"

    def catalog(self, identity, deadline=None):
        result = []
        global_read = self.effective_scope(identity) == "workspace"
        for table in ALL_TABLES:
            allowed = global_read or table in ("dev_platform_events", "dev_investigations")
            if not allowed:
                result.append({"name": table, "state": "requires-source-grant", "authorized": False})
                continue
            try:
                columns = self.columns(table, deadline=deadline)
                result.append({"name": table, "state": "available" if columns else "empty-or-missing", "authorized": True, "field_count": len(columns or [])})
            except Exception as error:
                result.append({"name": table, "state": "unavailable", "authorized": True, "error": type(error).__name__})
                if not self.client:
                    break
        return result

    def _validate(self, args):
        allowed = set(FILTERS) | {"hours", "page", "source_scope", "exclude_internal"}
        if not isinstance(args, dict) or set(args) - allowed:
            raise ValueError("Unknown query argument")
        for name in ("hours", "page"):
            raw = args.get(name, 24 if name == "hours" else 1)
            if isinstance(raw, bool) or not isinstance(raw, (str, int)):
                raise ValueError("Invalid " + name)
            value = int(raw)
            if not (0 <= value <= 87600 if name == "hours" else 1 <= value <= 10000):
                raise ValueError("Query range exceeds limit")
            args[name] = value
        for key in FILTERS:
            if args.get(key) is not None:
                literal(args[key])
        return args

    def source_sql(self, identity, args, deadline=None):
        scope = self.effective_scope(identity, args)
        tables = EVENT_TABLES if scope == "workspace" else ("dev_platform_events",)
        parts, coverage = [], []
        for table in tables:
            columns = self.columns(table, deadline=deadline)
            if columns is None:
                if table != "dev_platform_events":
                    continue
                columns = CANONICAL_COLUMNS
            if not columns:
                coverage.append({"table": table, "state": "empty-or-missing"})
                continue
            projection = Projection(table, columns)
            parts.append(projection.select())
            coverage.append({"table": table, "state": "queried"})
        if not parts:
            return None, scope, coverage
        union = " UNION ALL ".join(parts)
        # Isolate authorized rows before selecting a preferred duplicate; an
        # identical producer ID in another org must not hide this org's event.
        if scope=="organization":
            union="SELECT * FROM ("+union+") WHERE "+self.where(identity,{"hours":0},scope,use_time=False)
        # Native observations without producer IDs are kept separate. Counts are
        # observations, never claimed to equal unique model requests.
        # Include the union once: repeating every schema projection can exceed
        # the SQL parser's query-size limit when many native columns exist.
        output_columns=(*DIMENSIONS,*NUMBERS,"synthetic","source_table","source_priority","dedup_key")
        dedup = (
            "(SELECT "+",".join(quote(column) for column in output_columns)+" FROM ("
            "SELECT *,row_number() OVER (PARTITION BY source_event_id,origin_user_id,session_id "
            "ORDER BY source_priority,event_id) AS __dedup_rank FROM ("+union+")) "
            "WHERE source_event_id IS NULL OR __dedup_rank=1)"
        )
        return dedup, scope, coverage

    def where(self, identity, args, scope, *, use_time=True):
        clauses = ["1"]
        if scope == "organization":
            clauses = ["org_id=" + literal(identity["org_id"])]
            if identity["role"] == "member":
                clauses.append("user_id=" + literal(identity["user_id"]))
            elif identity["role"] == "team_manager":
                key = "team_id" if identity.get("team_id") else "user_id"
                clauses.append(key + "=" + literal(identity[key]))
            elif identity["role"] not in ("admin", "viewer"):
                raise PermissionError("Invalid role")
        if use_time and args["hours"]:
            clauses.append("occurred_at_epoch >= " + str(int(time.time()) - args["hours"] * 3600))
        for key in FILTERS:
            if args.get(key):
                # The dashboard's user selector denotes origin, never the login actor.
                column = "origin_user_id" if scope == "workspace" and key == "user_id" else key
                clauses.append(column + "=" + literal(args[key]))
        if args.get("exclude_internal"):
            clauses.append("coalesce(activity_kind,'agent') NOT IN ('analyst','synthetic','internal')")
            clauses.append("synthetic=false")
        return " AND ".join(clauses)

    def query_tool(self, identity, name, args=None, deadline=None):
        if name not in self.TOOLS:
            raise PermissionError("Tool is not allowed")
        args = self._validate(dict(args or {}))
        deadline = deadline or time.monotonic() + 30
        if name == "experiments":
            return self.experiments(identity, args, deadline)
        source, scope, coverage = self.source_sql(identity, args, deadline)
        scope_info = {**args,"source_scope": scope}
        if self.shared:
            scope_info["source_id"] = self.shared.descriptor["id"]
        if source is None:
            return {"data": [], "sql": None, "source": "RawTree", "scope": scope_info, "coverage": coverage, "hours": args["hours"], "empty_source": True}
        where = self.where(identity, args, scope)
        aggregates = (
            "count() AS events,countIf(status='error') AS errors,"
            "sumOrNull(input_tokens) AS input_tokens,sumOrNull(output_tokens) AS output_tokens,"
            "avgOrNull(duration_ms) AS latency_ms,"
            "countIf(input_tokens IS NOT NULL OR output_tokens IS NOT NULL) AS events_with_usage,"
            "countIf(usage_kind='session_total') AS session_total_reports,"
            "countIf(usage_kind='metric_sample') AS metric_samples"
        )
        if name == "overview":
            select = (
                aggregates + ",countIf(synthetic=true) AS synthetic_events,"
                "sumOrNull(cached_tokens) AS cached_tokens,sumOrNull(cache_creation_tokens) AS cache_creation_tokens,"
                "sumOrNull(reasoning_tokens) AS reasoning_tokens,sumOrNull(observed_cost_usd) AS cost_usd,"
                "uniqExact(session_id) AS sessions,uniqExact(origin_user_id) AS emitters,"
                "countIf(origin_user_id IS NULL) AS unattributed_events,"
                "countIf(observed_cost_usd IS NOT NULL) AS events_with_cost"
            )
            suffix = ""
        elif name in ("agents", "usage"):
            grouping="provider,model,agent"+(",agent_id" if name=="agents" else "")
            select = grouping+","+aggregates+",sumOrNull(cached_tokens) AS cached_tokens,sumOrNull(cache_creation_tokens) AS cache_creation_tokens,sumOrNull(reasoning_tokens) AS reasoning_tokens,sumOrNull(observed_cost_usd) AS observed_cost_usd"
            suffix = " GROUP BY "+grouping+" ORDER BY events DESC LIMIT 100"
        elif name == "sessions":
            select = "session_id,origin_user_id,provider,model," + aggregates + ",max(timestamp) AS last_seen"
            suffix = " GROUP BY session_id,origin_user_id,provider,model ORDER BY last_seen DESC,session_id LIMIT 50 OFFSET " + str((args["page"] - 1) * 50)
        elif name == "errors":
            select = "session_id,provider,tool,error_type,count() AS failures"
            where += " AND status='error'"
            suffix = " GROUP BY session_id,provider,tool,error_type ORDER BY failures DESC LIMIT 50"
        elif name == "people":
            select = "origin_user_id,argMax(origin_user_name,occurred_at_epoch) AS origin_user_name,origin_user_id AS user_id,team_id," + aggregates
            suffix = " GROUP BY origin_user_id,team_id ORDER BY events DESC LIMIT 100"
        elif name=="timeline" and args.get("session_id"):
            fields = list(DIMENSIONS) + list(NUMBERS) + ["synthetic", "source_table"]
            select = ",".join(quote(field) for field in fields)
            suffix = " ORDER BY occurred_at_epoch,event_id,source_table LIMIT 200 OFFSET " + str((args["page"] - 1) * 200)
        else:
            select = "floor(occurred_at_epoch/3600)*3600 AS hour,count() AS events,countIf(status='error') AS errors"
            where += " AND occurred_at_epoch IS NOT NULL"
            suffix = " GROUP BY hour ORDER BY hour DESC LIMIT 1000"
        sql = "SELECT " + select + " FROM " + source + " WHERE " + where + suffix
        key = (identity["org_id"], identity["user_id"], identity["role"], identity.get("team_id"), scope, sql)
        with self._lock:
            cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < 5:
            return {**cached[1], "cached": True}
        data = finite(invoke(self._client().query, sql, deadline=deadline))
        if name == "trend" or name == "timeline" and not args.get("session_id"):
            data = sorted(data, key=lambda row: row.get("hour") or 0)
        result = {
            "sql": sql, "data": data, "source": "RawTree", "hours": args["hours"],
            "scope": scope_info, "coverage": coverage, "queried_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "metric_policy": "Rows are observations. Per-event usage excludes spans, metric samples and cumulative/session totals. session_total_reports and metric_samples show excluded coverage. Input tokens retain each provider's accounting; cached tokens must not be added indiscriminately. Explicit producer IDs are deduplicated; observations without a shared source ID are not assumed to be the same request.",
        }
        with self._lock:
            if len(self._cache) > 160:
                self._cache.clear()
            self._cache[key] = (time.monotonic(), result)
        return result

    def experiments(self, identity, args, deadline=None):
        """Bounded aggregate evaluation records, never raw questions/solutions."""
        scope = self.effective_scope(identity, args)
        tables = ("dev_platform_events", "dev_events_raw") if scope == "workspace" else ("dev_platform_events",)
        items, queries, seen, coverage = [], [], set(), []
        for table in tables:
            columns = self.columns(table, deadline=deadline)
            if not columns or "event_json" not in columns:
                coverage.append({"table": table, "state": "no-evaluation-envelope"})
                continue
            projection = Projection(table, columns)
            where = self.where(identity, args, scope)
            sql = (
                "SELECT event_json AS payload FROM (SELECT " + projection.select()[7:].split(" FROM " + table)[0]
                + "," + quote("event_json") + " AS event_json FROM " + table + ") WHERE " + where
                + " AND event_type IN ('eval.grade','evaluation.result','experiment.result')"
                + " ORDER BY occurred_at_epoch DESC,event_id LIMIT 200"
            )
            queries.append(sql)
            rows = invoke(self._client().query, sql, deadline=deadline)
            coverage.append({"table": table, "state": "queried", "records": len(rows), "limited": len(rows) == 200})
            for raw in rows:
                try:
                    event = json.loads(raw["payload"]) if isinstance(raw.get("payload"), str) else raw.get("payload", {})
                except (TypeError, ValueError):
                    continue
                if not isinstance(event, dict):
                    continue
                data = event.get("evaluation") or event.get("data") or {}
                if not isinstance(data, dict):
                    continue
                event_id = event.get("source_event_id") or event.get("event_id")
                origin=event.get("origin_user_id") or event.get("developer_id")
                identity_key=(event_id,str(origin or ""),str(event.get("session_id") or ""))
                if event_id and identity_key in seen:
                    continue
                if event_id:
                    seen.add(identity_key)
                breakdown = data.get("breakdown", {})
                if not isinstance(breakdown, dict):
                    breakdown = {}
                safe_breakdown = {}
                for key, value in list(breakdown.items())[:100]:
                    if isinstance(value, dict) and isinstance(key, str):
                        safe_breakdown[key[:128]] = {
                            "accuracy": self._number(value.get("accuracy"), fraction=True),
                            "count": self._number(value.get("count",value.get("sample_size"))),
                            "seconds":self._number(value.get("seconds")),
                            "tokens":self._number(value.get("tokens")),
                            "successes":self._number(value.get("successes")),
                            "failures":self._number(value.get("failures")),
                        }
                count = self._number(data.get("count", data.get("sample_size")))
                if count is None:
                    count = safe_breakdown.get("all", {}).get("count")
                config=data.get("recipe_config")
                safe_config={}
                config_hash=self._text(data.get("recipe_config_hash"))
                if isinstance(config,dict):
                    for field in ("name","model","backend","prompt_id","prompt_version"):
                        if isinstance(config.get(field),str): safe_config[field]=self._text(config[field])
                    for field in ("rag_k","temperature","max_tokens"):
                        value=self._number(config.get(field))
                        if value is not None: safe_config[field]=value
                    if not config_hash:
                        try:
                            config_hash=hashlib.sha256(json.dumps(config,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
                        except (ValueError,TypeError): pass
                items.append({
                    "event_id": event_id, "run_id": event.get("run_id"),
                    "recipe": self._text(data.get("recipe")) or self._text(data.get("variant")) or "Sin identificar",
                    "variant": self._text(data.get("variant")) or self._text(data.get("recipe")) or "Sin identificar",
                    "dataset": self._text(data.get("dataset")), "split": self._text(data.get("split")),
                    "suite_version": self._text(data.get("suite_version")),
                    "hardware": self._text(data.get("hardware", data.get("device"))),
                    "accuracy": self._number(data.get("accuracy"), fraction=True),
                    "count": count, "seconds": self._number(data.get("seconds")),
                    "tokens": self._number(data.get("tokens")),
                    "recipe_config":safe_config,"recipe_config_hash":config_hash,
                    "success":data.get("success") if isinstance(data.get("success"),bool) else None,
                    "no_reveal": data.get("no_reveal") if isinstance(data.get("no_reveal"), bool) else None,
                    "breakdown": safe_breakdown, "timestamp": event.get("timestamp"),
                    "source_table": table, "synthetic": event.get("synthetic") is True or data.get("synthetic") is True,
                })
        items.sort(key=lambda row: str(row.get("timestamp") or ""), reverse=True)
        return {
            "data": items, "sql": queries, "source": "RawTree", "scope": {**args,"source_scope": scope,
                **({"source_id":self.shared.descriptor["id"]} if self.shared else {})},
            "coverage": coverage, "hours": args["hours"],
            "metric_policy": "Compare matching dataset, split, suite and hardware. Missing metadata prevents a validated comparison.",
        }

    @staticmethod
    def _number(value, fraction=False):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            return None
        return value if not fraction or value <= 1 else None

    @staticmethod
    def _text(value):
        return value[:128] if isinstance(value, str) and value else None
