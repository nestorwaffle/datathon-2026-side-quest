"""Schema-aware read-only exploration with tenant predicates and explicit legacy assignment."""
import csv
import hashlib
import io
import json
import re
import time

from .identity import digest
from .platform import literal
from .rawtree import RawTree

TABLES = {"dev_platform_events", "dev_investigations", "dev_logs", "dev_traces", "dev_metrics", "dev_events_raw", "dev_artifacts_raw"}
LEGACY = TABLES - {"dev_platform_events", "dev_investigations"}
FIELDS = {"event_id","timestamp","event_type","status","provider","agent","model","session_id","user_id","team_id","project_id",
    "trace_id","span_id","parent_span_id","tool","error_type","duration_ms","input_tokens","output_tokens","cached_tokens",
    "observed_cost_usd","run_id","activity_kind","provenance","synthetic","name","traceId","spanId","parentSpanId",
    "startTimeUnixNano","endTimeUnixNano","timeUnixNano","service.name","scope.name","conversation.id","session.id",
    "model","tool_name","severityNumber","severityText","developer_id","input_token_count","output_token_count",
    "data.artifact_id","data.sha256","data.size","data.mime","eventName","provider_name","status.code","id","created_at"}
FIELDS.update({"gen_ai.usage.input_tokens","gen_ai.usage.output_tokens","codex.turn.token_usage.input_tokens",
               "codex.turn.token_usage.output_tokens","cached_token_count","duration_ms","tool_namespace","file_path","file_sha256"})

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
        columns=self.analytics.columns(table)
        return sorted((columns or set()) & FIELDS)

    def tables(self, identity):
        result=[]
        for table in sorted(TABLES):
            allowed=table not in LEGACY
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
        if not isinstance(body,dict) or set(body)-{"table","fields","group_by","hours","page","filters","offline"}:
            raise ValueError("Invalid explorer request")
        table=body.get("table","dev_platform_events")
        if table not in TABLES: raise PermissionError("Table is not authorized")
        scope=digest(json.dumps([identity,{k:v for k,v in body.items() if k!="offline"}],sort_keys=True))
        if body.get("offline") is True:
            with self.store.db() as db: snapshot=db.execute("SELECT created,payload FROM verified_snapshots WHERE scope=?",(scope,)).fetchone()
            if not snapshot: raise ValueError("No verified snapshot exists for this exact authorized query")
            return {**json.loads(snapshot[1]),"source":"Verified RawTree snapshot","snapshot_at":snapshot[0],"live":False}
        columns=self.schema(table)
        fields=body.get("fields") or [f for f in ("timestamp","event_id","session_id","tool","status","activity_kind") if f in columns]
        group=body.get("group_by") or []
        if not isinstance(fields,list) or not isinstance(group,list) or len(fields)>12 or len(group)>3:
            raise ValueError("Select at most 12 fields or 3 grouping dimensions")
        if any(f not in columns for f in fields+group): raise PermissionError("Field is unavailable or sensitive")
        page=body.get("page",1); hours=body.get("hours",24)
        if type(page) is not int or not 1<=page<=100 or type(hours) is not int or not 1<=hours<=720:
            raise ValueError("Range exceeds limit")
        where="org_id="+literal(identity["org_id"])
        if identity["role"]=="member": where+=" AND user_id="+literal(identity["user_id"])
        if identity["role"]=="team_manager":
            where+=" AND "+("team_id="+literal(identity["team_id"]) if identity.get("team_id") else "user_id="+literal(identity["user_id"]))
        if table in LEGACY:
            if identity["role"]!="admin": raise PermissionError("Assigned historical data is limited to administrators")
            with self.store.db() as db:
                traces=[r[0] for r in db.execute("SELECT trace_id FROM legacy_assignments WHERE org_id=? AND table_name=?",(identity["org_id"],table))]
            if not traces: raise PermissionError("Historical data is unassigned")
            trace_column="traceId" if table in ("dev_logs","dev_traces","dev_metrics") else "trace_id"
            if trace_column not in columns: raise ValueError("This historical table has no trace attribution; assignment unavailable")
            where="`"+trace_column+"` IN ("+",".join(literal(t) for t in traces[:100])+")"
        if table=="dev_platform_events": where+=" AND occurred_at_epoch >= "+str(int(time.time())-hours*3600)
        filters=body.get("filters") or {}
        if not isinstance(filters,dict) or len(filters)>8: raise ValueError("Invalid filters")
        for key,value in filters.items():
            if key not in columns: raise PermissionError("Filter field unavailable")
            where+=" AND `"+key+"`="+literal(str(value))
        select=",".join("`"+f+"`" for f in (group or fields))
        if not select: select="count() AS rows"
        if group: select+=",count() AS rows"
        sql="SELECT "+select+" FROM "+table+" WHERE "+where
        if group: sql+=" GROUP BY "+",".join("`"+f+"`" for f in group)+" ORDER BY rows DESC"
        elif "timestamp" in columns: sql+=" ORDER BY timestamp DESC"
        sql+=" LIMIT 100 OFFSET "+str((page-1)*100)
        data=(self.analytics.client or RawTree(read_only=True)).query(sql)
        result={"data":data,"sql":sql,"source":"RawTree","page":page,"has_more":len(data)==100,"live":True}
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
