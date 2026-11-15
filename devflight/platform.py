"""Local enterprise API. RawTree is the analytical engine; SQLite holds identity and outbox."""
import argparse
import contextlib
import datetime as dt
import json
import os
from pathlib import Path
import re
import threading
import time
import secrets
import hmac
import gzip
import io
import urllib.parse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .identity import Store, identifier
from .rawtree import RawTree
from .analytics import Analytics, FILTERS, invoke, literal
from .shared import source_descriptor

def create_app(store=None, analytics=None, analyst=None, workers=True):
    store=store or Store(); store.bootstrap()
    analytics=analytics or Analytics(store=store)
    from .intelligence import Analyst
    from .investigation_jobs import InvestigationJobs
    jobs=InvestigationJobs(store, lambda: analyst or Analyst(analytics,store))
    stopped=threading.Event()
    def uploader():
        while not stopped.is_set():
            try:
                store.sync_once()
                store.archive_confirmed()
            except Exception: pass # Error is retained on the durable outbox row.
            stopped.wait(5)
    @contextlib.asynccontextmanager
    async def lifespan(app):
        worker=threading.Thread(target=uploader,daemon=True)
        if workers: worker.start()
        yield
        stopped.set()
        jobs.shutdown(wait=False)
        if workers: worker.join(timeout=1)
    app=FastAPI(title="DevFlight",docs_url=None,redoc_url=None,lifespan=lifespan)
    app.state.store=store; app.state.analytics=analytics
    from .explorer import Explorer
    explorer=Explorer(store,analytics)
    control_path=store.home/"control.key"
    if not control_path.exists():
        with control_path.open("x",encoding="ascii") as file:
            file.write(secrets.token_hex(32)); file.flush(); os.fsync(file.fileno())
        if os.name!="nt": control_path.chmod(0o600)
    control_key=control_path.read_text().strip()
    if not re.fullmatch("[a-f0-9]{64}",control_key): raise ValueError("Invalid platform control key")

    @app.middleware("http")
    async def local_security(request,call_next):
        host=request.headers.get("host","")
        hostname=host.split(":")[0]
        if hostname not in ("localhost","127.0.0.1","testserver"):
            return JSONResponse({"error":"Invalid host"},status_code=403)
        origin=request.headers.get("origin")
        if origin and origin!="http://"+host and origin!="https://"+host:
            return JSONResponse({"error":"Cross-origin request denied"},status_code=403)
        try: length=int(request.headers.get("content-length","0"))
        except ValueError: return JSONResponse({"error":"Invalid length"},status_code=400)
        if length<0: return JSONResponse({"error":"Invalid length"},status_code=400)
        if request.method in ("POST","PUT","PATCH") and ("content-length" not in request.headers or request.headers.get("transfer-encoding")):
            return JSONResponse({"error":"A bounded Content-Length is required"},status_code=411)
        if length>4*1024*1024: return JSONResponse({"error":"Payload too large"},status_code=413)
        response=await call_next(request)
        response.headers["Cache-Control"]="no-store"
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["X-Frame-Options"]="DENY"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(PermissionError)
    async def denied(request,error): return JSONResponse({"error":str(error)},status_code=403)
    @app.exception_handler(ValueError)
    async def invalid(request,error): return JSONResponse({"error":str(error)},status_code=400)
    @app.exception_handler(KeyError)
    async def missing(request,error): return JSONResponse({"error":"Record not found"},status_code=404)
    @app.exception_handler(Exception)
    async def failure(request,error):
        return JSONResponse({"error":"Backend unavailable: "+type(error).__name__,"source":"RawTree or configured provider","retryable":True},status_code=503,headers={"Retry-After":"5"})
    @app.exception_handler(OSError)
    async def storage_failure(request,error):
        return JSONResponse({"error":"Persistence or connection unavailable; event not confirmed","retryable":True},status_code=503,headers={"Retry-After":"5"})

    def identity(request):
        token=request.cookies.get("devflight_session","")
        try: return store.authenticate(token)
        except PermissionError: raise HTTPException(401,"Sign in required")

    def filters(request):
        return {key:value for key,value in request.query_params.items() if key in (*FILTERS,"hours","page","source_scope")}

    @app.get("/api/health")
    def health():
        from .resources import snapshot
        return {"service":"devflight-platform","source":"RawTree","status":"running","process":snapshot()}

    @app.post("/api/control/stop")
    def stop(request:Request):
        if not hmac.compare_digest(request.headers.get("X-DevFlight-Control",""),control_key):
            raise PermissionError("Control authentication required")
        if not hasattr(app.state,"request_stop"): raise HTTPException(409,"Stop callback unavailable")
        app.state.request_stop()
        return {"stopping":True}

    @app.post("/api/login")
    def login(body:dict):
        account=store.authenticate(body.get("token"),"login")
        session=store.issue(account)
        response=JSONResponse({**account,"mode":"RawTree"})
        response.set_cookie("devflight_session",session,httponly=True,samesite="strict",max_age=28800,path="/api")
        return response

    @app.post("/api/logout")
    def logout(request:Request):
        store.revoke(request.cookies.get("devflight_session",""))
        response=JSONResponse({"signed_out":True}); response.delete_cookie("devflight_session",path="/api")
        return response

    @app.get("/api/me")
    def me(request:Request):
        actor=identity(request)
        return {**actor,"mode":"RawTree","organizations":store.organizations(actor),
                "source_scope":analytics.effective_scope(actor)}

    @app.get("/api/source")
    def source(request:Request):
        actor=identity(request)
        result=(analytics.shared.info(actor) if analytics.shared else
                {**source_descriptor(),"can_read_global":False,"can_manage_source":False,"scope":"organization"})
        result["tables"]=analytics.catalog(actor,deadline=time.monotonic()+15) if result["read_configured"] or analytics.client else []
        result["coverage"]={"mode":"Live SQL projections over known telemetry tables",
                            "attribution":"Explicit emitter identifiers; missing identities remain unknown",
                            "deduplication":"Explicit producer IDs within their origin/session; unidentified observations remain separate"}
        return result

    @app.post("/api/source/grants")
    def grant_source(request:Request,body:dict):
        if not analytics.shared: raise PermissionError("Shared-source access is not configured")
        if type(body.get("enabled",True)) is not bool: raise ValueError("enabled must be boolean")
        return analytics.shared.grant(identity(request),body.get("org_id"),body.get("enabled",True))

    @app.get("/api/delivery")
    def delivery(request:Request):
        actor=identity(request)
        global_read=analytics.effective_scope(actor)=="workspace"
        status=store.status(None if global_read else actor)
        return {**status,"scope":"local-uploader-for-source" if global_read else "organization",
                "oldest_pending_age_seconds":status.get("age_seconds"),
                "write_configured":bool(os.getenv("RAWTREE_API_KEY")),
                "read_configured":bool(os.getenv("RAWTREE_READ_KEY")),
                "visibility_policy":"Acknowledged inserts and dashboard reads are separate confirmations"}

    @app.get("/api/analyst/status")
    def analyst_status(request:Request):
        identity(request)
        endpoint=urllib.parse.urlsplit(os.getenv("HELMCODE_BASE_URL","https://api.helmcode.com/v1"))
        # Do not echo accidental credentials or query parameters from configuration.
        safe_endpoint=(urllib.parse.urlunsplit((endpoint.scheme,endpoint.netloc,endpoint.path,"",""))
                       if endpoint.scheme=="https" and endpoint.hostname and not endpoint.username and not endpoint.password
                       else None)
        return {"configured":bool(os.getenv("HELMCODE_API_KEY")),
                "model":os.getenv("HELMCODE_MODEL") or "qwen3.6",
                "base_url":safe_endpoint,
                "configuration_valid":safe_endpoint is not None and not endpoint.query and not endpoint.fragment,
                "rawtree_configured":bool(os.getenv("RAWTREE_READ_KEY")),
                "connection_state":"not_checked","max_concurrent":2,
                "mode":"live-provider-required"}

    @app.post("/api/analyst/check")
    def check_analyst(request:Request):
        actor=identity(request)
        if actor["role"]=="viewer": raise PermissionError("Investigation permission required")
        from .intelligence import Helmcode
        return Helmcode().check()

    @app.post("/api/organizations/switch")
    def switch(request:Request,body:dict):
        token=store.switch(identity(request),body.get("org_id"))
        response=JSONResponse({"changed":True});response.set_cookie("devflight_session",token,httponly=True,samesite="strict",max_age=28800,path="/api")
        return response

    @app.get("/api/overview")
    def overview(request:Request):
        actor=identity(request); args=filters(request)
        deadline=time.monotonic()+30
        result=analytics.query_tool(actor,"overview",args,deadline=deadline)
        agents=analytics.query_tool(actor,"agents",args,deadline=deadline)["data"]
        trend=analytics.query_tool(actor,"trend",args,deadline=deadline)["data"]
        return {"source":"RawTree","summary":result["data"][0] if result["data"] else {},
                "agents":agents,"trend":trend,"trend_limited":len(trend)==1000,"trend_limit":1000,
                "outbox":store.status(None if analytics.effective_scope(actor,args)=="workspace" else actor),
                "scope":result.get("scope"),"coverage":result.get("coverage"),"metric_policy":result.get("metric_policy")}

    @app.get("/api/agents")
    def agents(request:Request): return limited_items(request,"agents")
    @app.get("/api/people")
    def people(request:Request): return limited_items(request,"people")
    @app.get("/api/usage")
    def usage(request:Request): return {**limited_items(request,"usage"),"cost_policy":"Observed provider costs only; unknown costs remain null"}

    def limited_items(request,name):
        result=analytics.query_tool(identity(request),name,filters(request))
        return {"items":result["data"],"source":"RawTree","limit":100,"limited":len(result["data"])==100,
                "scope":result.get("scope"),"coverage":result.get("coverage"),"metric_policy":result.get("metric_policy")}
    @app.get("/api/sessions")
    def sessions(request:Request):
        args=filters(request); rows=analytics.query_tool(identity(request),"sessions",args)["data"]
        return {"items":rows,"page":int(args.get("page",1)),"has_more":len(rows)==50,"total":None,"source":"RawTree"}
    @app.get("/api/sessions/{session_id}")
    def session(request:Request,session_id:str):
        args={**filters(request),"session_id":session_id}
        result=analytics.query_tool(identity(request),"timeline",args)
        return {"items":result["data"],"source":"RawTree","scope":result.get("scope"),
                "page":int(args.get("page",1)),"has_more":len(result["data"])==200,"total":None,
                "page_size":200}

    @app.get("/api/experiments")
    def experiments(request:Request):
        result=analytics.query_tool(identity(request),"experiments",filters(request))
        items=result["data"]; breakdown=[]
        cohorts={}
        for item in items:
            keys=tuple(item.get(key) for key in ("dataset","split","suite_version","hardware"))
            if all(keys): cohorts.setdefault(keys,[]).append(item)
            for name,value in item.get("breakdown",{}).items():
                if ":" in name:
                    dimension,category=name.split(":",1)
                    breakdown.append({"run_id":item.get("run_id"),"recipe":item.get("recipe"),
                                      "dimension":dimension,"value":category,**value})
        return {"items":items,"breakdown":breakdown,"source":"RawTree",
                "summary":{"runs":len(items),"comparable_groups":sum(len(rows)>1 for rows in cohorts.values()),
                           "latest_accuracy":items[0].get("accuracy") if items else None},
                "scope":result.get("scope"),"coverage":result.get("coverage"),
                "metric_policy":result.get("metric_policy"),"sql":result.get("sql")}

    @app.get("/api/settings")
    def settings(request:Request):
        actor=identity(request); result=store.settings(actor)
        from .integrations import report
        result["integrations"]=report(port=8788) if actor["role"]=="admin" else {}
        result["outbox"]=store.status(actor) if actor["role"]=="admin" else None
        return result
    @app.post("/api/settings")
    def manage(request:Request,body:dict): return store.manage(identity(request),body)

    @app.post("/api/events")
    def ingest(request:Request,body:dict):
        header=request.headers.get("authorization","")
        if not header.startswith("Bearer "): raise PermissionError("Ingestion credential required")
        actor=store.authenticate(header[7:],"ingest")
        event=store.ingest(actor,body)
        return {"event_id":event["event_id"],"durable":True,"pending_sync":True}

    @app.post("/v1/{signal}")
    async def otlp(request:Request,signal:str):
        from .collector import validate_otlp
        field={"logs":"resourceLogs","traces":"resourceSpans","metrics":"resourceMetrics"}.get(signal)
        if not field: raise HTTPException(404,"Unknown OTLP signal")
        authorization=request.headers.get("authorization","")
        if not authorization.startswith("Bearer "): raise PermissionError("Ingestion credential required")
        actor=store.authenticate(authorization[7:],"ingest")
        raw=await request.body()
        encoding=request.headers.get("content-encoding","identity")
        if encoding=="gzip":
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream: raw=stream.read(4*1024*1024+1)
            except (OSError,EOFError): raise ValueError("Invalid gzip body")
        elif encoding!="identity": raise HTTPException(415,"Unsupported content encoding")
        if len(raw)>4*1024*1024: raise HTTPException(413,"Decompressed body exceeds 4 MiB")
        try: body=json.loads(raw)
        except (ValueError,UnicodeDecodeError): raise ValueError("Invalid OTLP JSON")
        validate_otlp(body,field)
        store.ingest_otlp(actor,signal,body)
        return {} # OTLP Export*ServiceResponse: durable acceptance, not remote delivery.

    @app.get("/api/explorer/tables")
    def tables(request:Request): return {"items":explorer.tables(identity(request))}
    @app.post("/api/explorer/query")
    def explore(request:Request,body:dict): return explorer.query(identity(request),body)
    @app.post("/api/explorer/export")
    def export(request:Request,body:dict):
        return Response(explorer.export(identity(request),body),media_type="text/csv",
                        headers={"Content-Disposition":"attachment; filename=devflight-export.csv"})
    @app.get("/api/views")
    def views(request:Request): return {"items":explorer.views(identity(request))}
    @app.post("/api/views")
    def save_view(request:Request,body:dict): return {"items":explorer.views(identity(request),body)}
    @app.post("/api/explorer/assign")
    def assign(request:Request,body:dict): return explorer.assign(identity(request),body.get("table"),body.get("trace_id"))

    @app.get("/api/anomalies")
    def anomalies(request:Request):
        actor=identity(request)
        rows=analytics.query_tool(actor,"errors",{**filters(request),"exclude_internal":True})["data"]
        return {"items":[r for r in rows if int(r.get("failures",0))>=3],"source":"RawTree",
                "rule":"At least 3 agent/development tool errors; analyst, internal and synthetic activity excluded"}

    @app.get("/api/investigations")
    def investigations(request:Request):
        actor=identity(request)
        records=jobs.list(actor,conversation_id=request.query_params.get("conversation_id"))
        selected=filters(request)
        if selected.get("hours") is not None:
            hours=int(selected["hours"])
            if not 0<=hours<=87600: raise ValueError("Invalid period")
            cutoff=time.time()-hours*3600 if hours else 0
            def created(record):
                try: return dt.datetime.fromisoformat(str(record.get("created_at",record.get("timestamp",""))).replace("Z","+00:00")).timestamp()
                except (TypeError,ValueError): return 0
            records=[record for record in records if created(record)>=cutoff]
        for key,value in selected.items():
            if key in FILTERS: records=[record for record in records if record.get("scope",{}).get(key)==value]
        return {"items":records,"history_scope":"private-to-actor"}

    @app.get("/api/investigations/{investigation_id}")
    def investigation(request:Request,investigation_id:str):
        record=jobs.get(identity(request),investigation_id)
        if record.get("journal_unavailable"):
            return {**record,"actions":[]}
        with store.db() as db:
            row=db.execute("SELECT value FROM metadata WHERE key=?",("followup:"+investigation_id,)).fetchone()
        return {**record,"actions":[json.loads(row[0])] if row else []}
    @app.post("/api/investigations")
    def investigate(request:Request,body:dict):
        actor=identity(request)
        if actor["role"]=="viewer": raise PermissionError("Viewer cannot launch investigations")
        question=body.get("question","")
        if not isinstance(question,str) or not 1<=len(question)<=2000: raise ValueError("Question must contain 1–2000 characters")
        scope=body.get("scope") or {}
        if not isinstance(scope,dict): raise ValueError("Invalid investigation scope")
        scope={**scope,"source_scope":analytics.effective_scope(actor,scope)}
        analytics._validate(dict(scope))
        result=jobs.submit(actor,question,scope=scope,conversation_id=body.get("conversation_id"),request_id=body.get("request_id"))
        return JSONResponse(result,status_code=202)

    @app.post("/api/investigations/{investigation_id}/cancel")
    def cancel_investigation(request:Request,investigation_id:str):
        return jobs.cancel(identity(request),investigation_id)

    @app.post("/api/investigations/{investigation_id}/followup-view")
    def followup_view(request:Request,investigation_id:str):
        actor=identity(request)
        if actor["role"]=="viewer": raise PermissionError("Action permission required")
        record=jobs.get(actor,investigation_id)
        if record.get("read_only") or record.get("historical_scope_unverified"):
            raise ValueError("Start a new investigation with the current source before creating a follow-up action")
        if not any(item.get("status")=="ok" for item in record.get("evidence",[])):
            raise ValueError("An investigation with successful query evidence is required")
        from .core import file_lock
        # Serialize retries before creating the view, including across local workers.
        with file_lock(store.home/("followup-"+investigation_id+".lock")):
            return save_followup_view(actor,investigation_id,record)

    def save_followup_view(actor,investigation_id,record):
        key="followup:"+investigation_id
        with store.db() as db:
            existing=db.execute("SELECT value FROM metadata WHERE key=?",(key,)).fetchone()
        scope=record.get("scope") or {}
        analytics.effective_scope(actor,scope)
        config={"table":"dev_all_events","fields":["timestamp","session_id","provider","model","tool","status"],
                "hours":scope.get("hours",24),"source_scope":scope.get("source_scope"),
                "filters":{key:value for key,value in scope.items() if key in FILTERS},"page":1}
        if existing:
            action=json.loads(existing[0])
            if action.get("status")=="verified": return action
        else:
            name="Seguimiento "+investigation_id[:8]
            view_id=identifier()
            action={"kind":"saved-view","status":"created","view_id":view_id,"investigation_id":investigation_id,
                    "created_at":dt.datetime.now(dt.timezone.utc).isoformat(),"name":name}
            if analytics.shared: config["source_id"]=analytics.shared.descriptor["id"]
            # Commit the view and idempotency record together: a process interruption
            # cannot leave a successful action without a retry marker.
            with store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT count(*) FROM saved_views WHERE org_id=? AND user_id=?",(actor["org_id"],actor["user_id"])).fetchone()[0]>=50:
                    raise ValueError("Saved view limit reached")
                db.execute("INSERT INTO saved_views VALUES (?,?,?,?,?)",(view_id,actor["org_id"],actor["user_id"],name,json.dumps(config)))
                db.execute("INSERT INTO metadata VALUES (?,?)",(key,json.dumps(action)))
        # Stable event IDs also recover an interrupted audit without duplicate actions.
        store.ingest(actor,{"event_id":investigation_id+"-view-created","event_type":"analyst.action.created",
                           "activity_kind":"analyst","session_id":investigation_id,"status":"ok",
                           "tool":"save_followup_view","provenance":"user-approved-investigation-action"})
        try:
            verification=explorer.query(actor,config)
            action.update(status="verified",rows_observed=len(verification["data"]),sql=verification["sql"],
                          verified_at=dt.datetime.now(dt.timezone.utc).isoformat())
            store.ingest(actor,{"event_id":investigation_id+"-view-verified","event_type":"analyst.action.verified",
                               "activity_kind":"analyst","session_id":investigation_id,"status":"ok",
                               "tool":"verify_followup_view","provenance":"rawtree-query-result"})
        except Exception as error:
            action.update(status="created_verification_pending",error=type(error).__name__)
        with store.db() as db: db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",(key,json.dumps(action)))
        return action

    @app.post("/api/demo")
    def demo(request:Request):
        actor=identity(request)
        if actor["role"] not in ("admin","team_manager"): raise PermissionError("Manager role required")
        session="synthetic-"+identifier()[:12]
        for i in range(12):
            store.ingest(actor,{"event_id":session+"-"+str(i),"session_id":session,"provider":"synthetic","agent":"demo-producer","model":"synthetic-no-model",
                                "event_type":"tool.result","tool":"synthetic_test_runner","status":"error" if i>=4 else "ok",
                                "error_type":"FixtureTimeout" if i>=4 else None,"input_tokens":100+i*10,"output_tokens":20,"duration_ms":100+i*50,"synthetic":True,"activity_kind":"synthetic","provenance":"explicit-demo-fixture"})
        return {"events":12,"session_id":session,"synthetic":True,"pending_sync":True,"analyst":"Launch an investigation after sync; requires a real configured LLM"}

    web=Path(__file__).parent/"web"
    if web.exists(): app.mount("/",StaticFiles(directory=str(web),html=True),name="dashboard")
    return app

def main():
    parser=argparse.ArgumentParser(description="DevFlight local enterprise platform")
    parser.add_argument("--home",default=os.getenv("DEVFLIGHT_PLATFORM_HOME",".devflight/platform"))
    parser.add_argument("--port",type=int,default=8788)
    args=parser.parse_args()
    store=Store(args.home); path=store.bootstrap()
    print(f"DevFlight http://127.0.0.1:{args.port}; local sign-in credential file: {path}",flush=True)
    import uvicorn
    app=create_app(store)
    server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=args.port,log_level="warning"))
    app.state.request_stop=lambda: setattr(server,"should_exit",True)
    server.run()

if __name__=="__main__": main()
