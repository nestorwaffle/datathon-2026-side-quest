"""Schema-aware shared-source exploration with explicit grants and private saved views."""
import csv
import hashlib
import io
import json
import re
import time

from .identity import digest
from .analytics import CANONICAL_COLUMNS, DIMENSIONS, NUMBERS, Projection, finite, invoke, literal, quote
from .rawtree import RawTree

TABLES = {"dev_all_events", "dev_platform_events", "dev_investigations", "dev_logs", "dev_traces", "dev_metrics", "dev_events_raw", "dev_artifacts_raw"}
LEGACY = TABLES - {"dev_all_events", "dev_platform_events", "dev_investigations"}
FIELDS = {"event_id","timestamp","event_type","status","provider","agent","model","session_id","user_id","team_id","project_id",
    "trace_id","span_id","parent_span_id","tool","error_type","duration_ms","input_tokens","output_tokens","cached_tokens",
    "observed_cost_usd","run_id","activity_kind","provenance","synthetic","name","traceId","spanId","parentSpanId",
    "startTimeUnixNano","endTimeUnixNano","timeUnixNano","service.name","scope.name","conversation.id","session.id",
    "model","tool_name","severityNumber","severityText","developer_id","input_token_count","output_token_count",
    "data.artifact_id","data.sha256","data.size","data.mime","eventName","provider_name","status.code","id","created_at"}
FIELDS.update({"gen_ai.usage.input_tokens","gen_ai.usage.output_tokens","codex.turn.token_usage.input_tokens",
               "codex.turn.token_usage.output_tokens","cached_token_count","duration_ms","tool_namespace","file_path","file_sha256"})
FIELDS.update(set(DIMENSIONS) | set(NUMBERS) | {"source_table","metric_data","asDouble","asInt","unit","event.name","event.kind","success","cost_usd"})

class Explorer:
    def __init__(self, store, analytics):
        self.store,self.analytics=store,analytics
        with store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS legacy_assignments(table_name TEXT,trace_id TEXT,org_id TEXT,PRIMARY KEY(table_name,trace_id));
              CREATE TABLE IF NOT EXISTS saved_views(id TEXT PRIMARY KEY,org_id TEXT,user_id TEXT,name TEXT,config TEXT);
              CREATE INDEX IF NOT EXISTS saved_views_owner ON saved_views(org_id,user_id);
              CREATE INDEX IF NOT EXISTS assignments_org ON legacy_assignments(org_id,table_name);
              CREATE TABLE IF NOT EXISTS verified_snapshots(scope TEXT PRIMARY KEY,created REAL,payload TEXT);''')

    def schema(self, table):
        if table not in TABLES: raise PermissionError("Table is not authorized")
        if table=="dev_all_events": return sorted((CANONICAL_COLUMNS|{"source_table"}) & FIELDS)
        columns=self.analytics.columns(table)
        return sorted((columns or set()) & FIELDS)

    def tables(self, identity):
        result=[]
        for table in sorted(TABLES):
            allowed=table not in LEGACY or self.analytics.effective_scope(identity)=="workspace"
            if not allowed and identity["role"]=="admin":
                with self.store.db() as db:
                    allowed=bool(db.execute("SELECT 1 FROM legacy_assignments WHERE org_id=? AND table_name=?",(identity["org_id"],table)).fetchone())
            try:
                fields=self.schema(table) if allowed else []
                state="available" if allowed else "historical-unassigned"
            except Exception:
                fields=[]; state="unavailable"
            result.append({"name":table,"authorized":allowed,"state":state,"fields":fields})
        return result

    def assign(self, identity, table, trace):
        # Only the locally bootstrapped operator can assign unauthenticated historical data.
        root=self.store.authenticate((self.store.home/"admin.token").read_text().strip(),"login")
        if identity["role"]!="admin" or identity["user_id"]!=root["user_id"]:
            raise PermissionError("Local data-owner authorization required")
        if table not in LEGACY or not isinstance(trace,str) or not re.fullmatch("[a-fA-F0-9]{32}",trace):
            raise ValueError("A permitted historical table and exact trace ID are required")
        with self.store.db() as db:
            old=db.execute("SELECT org_id FROM legacy_assignments WHERE table_name=? AND trace_id=?",(table,trace)).fetchone()
            if old and old[0]!=identity["org_id"]: raise PermissionError("History already belongs to another organization")
            db.execute("INSERT OR IGNORE INTO legacy_assignments VALUES (?,?,?)",(table,trace,identity["org_id"]))
        return {"assigned":True,"table":table,"trace_id":trace}

    def query(self, identity, body):
        if not isinstance(body,dict) or set(body)-{"table","fields","group_by","hours","page","filters","offline","source_scope","source_id"}:
            raise ValueError("Invalid explorer request")
        table=body.get("table","dev_all_events")
        if table not in TABLES: raise PermissionError("Table is not authorized")
        source_scope=self.analytics.effective_scope(identity,{"source_scope":body.get("source_scope")} if body.get("source_scope") else {})
        source_id=self.analytics.shared.descriptor["id"] if self.analytics.shared else "organization"
        if body.get("source_id") not in (None,source_id): raise PermissionError("Saved view belongs to another RawTree source")
        # Recheck authorization even when a previously verified snapshot is used.
        if table in LEGACY and source_scope!="workspace":
            if identity["role"]!="admin": raise PermissionError("Shared-source access required")
            with self.store.db() as db:
                if not db.execute("SELECT 1 FROM legacy_assignments WHERE org_id=? AND table_name=?",(identity["org_id"],table)).fetchone():
                    raise PermissionError("Historical data is unassigned")
        scope=digest(json.dumps([identity,source_id,source_scope,{k:v for k,v in body.items() if k!="offline"}],sort_keys=True))
        if body.get("offline") is True:
            with self.store.db() as db: snapshot=db.execute("SELECT created,payload FROM verified_snapshots WHERE scope=?",(scope,)).fetchone()
            if not snapshot: raise ValueError("No verified snapshot exists for this exact authorized query")
            return {**json.loads(snapshot[1]),"source":"Verified RawTree snapshot","snapshot_at":snapshot[0],"live":False}
        columns=self.schema(table)
        fields=body.get("fields") or [f for f in ("timestamp","event_id","session_id","tool","status","activity_kind",
                                                   "timeUnixNano","startTimeUnixNano","traceId","spanId","name","metric_name") if f in columns][:12]
        group=body.get("group_by") or []
        if not isinstance(fields,list) or not isinstance(group,list) or len(fields)>12 or len(group)>3:
            raise ValueError("Select at most 12 fields or 3 grouping dimensions")
        if any(f not in columns for f in fields+group): raise PermissionError("Field is unavailable or sensitive")
        page=body.get("page",1); hours=body.get("hours",24)
        if type(page) is not int or not 1<=page<=10000 or type(hours) is not int or not 0<=hours<=87600:
            raise ValueError("Range exceeds limit")
        where=self.analytics.where(identity,{"hours":0},source_scope,use_time=False)
        if table in LEGACY and source_scope!="workspace":
            if identity["role"]!="admin": raise PermissionError("Assigned historical data is limited to administrators")
            with self.store.db() as db:
                traces=[r[0] for r in db.execute("SELECT trace_id FROM legacy_assignments WHERE org_id=? AND table_name=?",(identity["org_id"],table))]
            if not traces: raise PermissionError("Historical data is unassigned")
            trace_column="traceId" if table in ("dev_logs","dev_traces","dev_metrics") else "trace_id"
            if trace_column not in columns: raise ValueError("This historical table has no trace attribution; assignment unavailable")
            where="`"+trace_column+"` IN ("+",".join(literal(t) for t in traces[:100])+")"
        deadline=time.monotonic()+30
        query_source=table
        coverage=[]
        if table=="dev_all_events":
            query_source,_,coverage=self.analytics.source_sql(identity,{"source_scope":source_scope},deadline)
            if query_source is None:
                return {"data":[],"sql":None,"source":"RawTree","page":page,"has_more":False,"live":True,"coverage":coverage}
            if hours: where+=" AND occurred_at_epoch >= "+str(int(time.time())-hours*3600)
        elif hours:
            complete_columns=self.analytics.columns(table)
            if complete_columns is None: complete_columns=CANONICAL_COLUMNS if table=="dev_platform_events" else set(columns)
            epoch=Projection(table,complete_columns).epoch()
            if epoch=="CAST(NULL AS Nullable(Float64))": raise ValueError("This table has no supported timestamp; choose Todo el historial")
            where+=" AND "+epoch+" >= "+str(int(time.time())-hours*3600)
        filters=body.get("filters") or {}
        if not isinstance(filters,dict) or len(filters)>12: raise ValueError("Invalid filters")
        for key,value in filters.items():
            if table=="dev_all_events" and source_scope=="workspace" and key=="user_id":
                key="origin_user_id"
            if key not in columns: raise PermissionError("Filter field unavailable")
            where+=" AND `"+key+"`="+literal(str(value))
        select=",".join("`"+f+"`" for f in (group or fields))
        if not select: select="count() AS rows"
        if group: select+=",count() AS rows"
        sql="SELECT "+select+" FROM "+query_source+" WHERE "+where
        if group: sql+=" GROUP BY "+",".join("`"+f+"`" for f in group)+" ORDER BY rows DESC"
        elif fields and "timestamp" in columns: sql+=" ORDER BY timestamp DESC"+(",event_id" if "event_id" in columns else "")
        elif fields and "created_at" in columns: sql+=" ORDER BY created_at DESC"
        elif fields and "timeUnixNano" in columns: sql+=" ORDER BY timeUnixNano DESC"
        elif fields and "startTimeUnixNano" in columns: sql+=" ORDER BY startTimeUnixNano DESC"
        sql+=" LIMIT 100 OFFSET "+str((page-1)*100)
        data=finite(invoke((self.analytics.client or RawTree(read_only=True)).query,sql,deadline=deadline))
        result={"data":data,"sql":sql,"source":"RawTree","page":page,"has_more":len(data)==100,"live":True,
                "coverage":coverage,"queried_at":time.time(),"scope":{"source_scope":source_scope,"source_id":source_id,"hours":hours,"filters":filters}}
        with self.store.db() as db:
            db.execute("INSERT OR REPLACE INTO verified_snapshots VALUES (?,?,?)",(scope,time.time(),json.dumps(result)))
            db.execute("DELETE FROM verified_snapshots WHERE scope NOT IN (SELECT scope FROM verified_snapshots ORDER BY created DESC LIMIT 200)")
        return result

    def views(self, identity, body=None):
        with self.store.db() as db:
            if body is not None:
                from .identity import identifier,safe_text
                name=safe_text(body.get("name"))
                if not name: raise ValueError("View name required")
                config=body.get("config",{})
                if not isinstance(config,dict): raise ValueError("Invalid view configuration")
                if self.analytics.shared: config={**config,"source_id":self.analytics.shared.descriptor["id"]}
                if len(json.dumps(config))>4000: raise ValueError("View configuration too large")
                if db.execute("SELECT count(*) FROM saved_views WHERE org_id=? AND user_id=?",(identity["org_id"],identity["user_id"])).fetchone()[0]>=50:
                    raise ValueError("Saved view limit reached")
                db.execute("INSERT INTO saved_views VALUES (?,?,?,?,?)",(identifier(),identity["org_id"],identity["user_id"],name,json.dumps(config)))
            return [{"id":r[0],"name":r[1],"config":json.loads(r[2])} for r in db.execute("SELECT id,name,config FROM saved_views WHERE org_id=? AND user_id=?",(identity["org_id"],identity["user_id"]))]

    def export(self, identity, body):
        result=self.query(identity,{**body,"page":1})
        stream=io.StringIO(); writer=csv.writer(stream)
        fields=list(result["data"][0]) if result["data"] else []
        writer.writerow(fields)
        for row in result["data"]:
            writer.writerow([("'"+str(row.get(f))) if str(row.get(f,"")).startswith(("=","+","-","@")) else row.get(f) for f in fields])
        return stream.getvalue()
