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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .identity import Store, identifier
from .rawtree import RawTree

def literal(value):
    if not isinstance(value,str) or len(value)>256 or any(ord(c)<32 for c in value):
        raise ValueError("Invalid query filter")
    return "'"+value.replace("\\","\\\\").replace("'","\\'")+"'"

class Analytics:
    TOOLS = {"overview","agents","sessions","errors","usage","people","timeline"}
    def __init__(self, client=None):
        self.client=client
        self._cache={}
        self._lock=threading.Lock()

    def columns(self, table="dev_platform_events"):
        client=self.client or RawTree(read_only=True)
        if not hasattr(client,"request"): return None # Explicit test clients.
        key=("schema",table)
        with self._lock:
            cached=self._cache.get(key)
        if cached and time.monotonic()-cached[0]<10: return cached[1]
        result=client.request("/v1/query",{"sql":"SELECT * FROM "+table+" LIMIT 0"})
        columns={r["name"] for r in result.get("meta",[])}
        with self._lock: self._cache[key]=(time.monotonic(),columns)
        return columns

    def query_tool(self, identity, name, args=None):
        args=args or {}
        if name not in self.TOOLS: raise PermissionError("Tool is not allowed")
        if set(args)-{"hours","page","session_id","provider","project_id","model","user_id","team_id","run_id","activity_kind"}: raise ValueError("Unknown query argument")
        hours=int(args.get("hours",24)); page=int(args.get("page",1))
        if not 1<=hours<=720 or not 1<=page<=100: raise ValueError("Query range exceeds limit")
        where="org_id="+literal(identity["org_id"])
        if identity["role"]=="member": where+=" AND user_id="+literal(identity["user_id"])
        elif identity["role"]=="team_manager":
            if identity.get("team_id"): where+=" AND team_id="+literal(identity["team_id"])
            else: where+=" AND user_id="+literal(identity["user_id"])
        elif identity["role"] not in ("admin","viewer"): raise PermissionError("Invalid role")
        where+=" AND occurred_at_epoch >= "+str(int(time.time())-hours*3600)
        columns=self.columns()
        for key in ("session_id","provider","project_id","model","user_id","team_id","run_id","activity_kind"):
            if args.get(key): where+=" AND "+(key+"="+literal(args[key]) if columns is None or key in columns else "0")
        def dimension(name):
            return ("`"+name+"`" if columns is None or name in columns else "CAST(NULL AS Nullable(String))")+" AS "+name
        def numeric(name):
            return "toFloat64OrNull(toString(`"+name+"`))" if columns is None or name in columns else "CAST(NULL AS Nullable(Float64))"
        aggregates=("count() AS events,countIf(status='error') AS errors,"
                    "sumOrNull("+numeric("input_tokens")+") AS input_tokens,sumOrNull("+numeric("output_tokens")+") AS output_tokens,"
                    "avg("+numeric("duration_ms")+") AS latency_ms")
        if name=="overview": select="SELECT "+aggregates+",countIf(synthetic=true) AS synthetic_events,sumOrNull("+numeric("cached_tokens")+") AS cached_tokens,sumOrNull("+numeric("observed_cost_usd")+") AS cost_usd,uniqExact(session_id) AS sessions FROM dev_platform_events WHERE "+where
        elif name in ("agents","usage"):
            dimensions=",".join(dimension(n) for n in ("provider","model"))
            select="SELECT "+dimensions+","+aggregates+",sumOrNull("+numeric("cached_tokens")+") AS cached_tokens,sumOrNull("+numeric("observed_cost_usd")+") AS observed_cost_usd FROM dev_platform_events WHERE "+where+" GROUP BY provider,model ORDER BY events DESC LIMIT 100"
        elif name=="sessions":
            select="SELECT "+",".join(dimension(n) for n in ("session_id","provider","model"))+","+aggregates+",max(timestamp) AS last_seen FROM dev_platform_events WHERE "+where+" GROUP BY session_id,provider,model ORDER BY last_seen DESC LIMIT 50 OFFSET "+str((page-1)*50)
        elif name=="errors":
            select="SELECT "+",".join(dimension(n) for n in ("session_id","provider","tool","error_type"))+",count() AS failures FROM dev_platform_events WHERE "+where+" AND status='error' GROUP BY session_id,provider,tool,error_type ORDER BY failures DESC LIMIT 30"
        elif name=="people":
            select="SELECT "+",".join(dimension(n) for n in ("user_id","team_id"))+","+aggregates+" FROM dev_platform_events WHERE "+where+" GROUP BY user_id,team_id ORDER BY events DESC LIMIT 100"
        else:
            if args.get("session_id"):
                select="SELECT "+",".join(dimension(n) for n in ("event_id","timestamp","session_id","trace_id","span_id","parent_span_id","provider","model","event_type","tool","error_type","status","duration_ms","input_tokens","output_tokens","run_id","activity_kind","provenance"))+" FROM dev_platform_events WHERE "+where+" ORDER BY occurred_at_epoch LIMIT 200"
            else:
                select="SELECT intDiv(toUInt64(occurred_at_epoch),3600)*3600 AS hour,count() AS events,countIf(status='error') AS errors FROM dev_platform_events WHERE "+where+" GROUP BY hour ORDER BY hour LIMIT 720"
        client=self.client or RawTree(read_only=True)
        cachekey=(identity["org_id"],identity["user_id"],identity["role"],identity.get("team_id"),select)
        with self._lock: cached=self._cache.get(cachekey)
        if cached and time.monotonic()-cached[0]<5:
            return {**cached[1],"cached":True}
        data=client.query(select)
        # Driver/JSON numeric edge cases must not become invalid HTTP JSON.
        import math
        data=[{k:(None if isinstance(v,float) and not math.isfinite(v) else v) for k,v in row.items()} for row in data]
        result={"sql":select,"data":data,"source":"RawTree","hours":hours}
        with self._lock:
            if len(self._cache)>128: self._cache.clear()
            self._cache[cachekey]=(time.monotonic(),result)
        return result

def create_app(store=None, analytics=None, analyst=None, workers=True):
    store=store or Store(); store.bootstrap()
    analytics=analytics or Analytics()
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
        if length>1024*1024: return JSONResponse({"error":"Payload too large"},status_code=413)
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
        return {key:value for key,value in request.query_params.items() if key in ("hours","page","provider","project_id","session_id","model","user_id","team_id","run_id","activity_kind")}

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
        return {**actor,"mode":"RawTree","organizations":store.organizations(actor)}

    @app.post("/api/organizations/switch")
    def switch(request:Request,body:dict):
        token=store.switch(identity(request),body.get("org_id"))
        response=JSONResponse({"changed":True});response.set_cookie("devflight_session",token,httponly=True,samesite="strict",max_age=28800,path="/api")
        return response

    @app.get("/api/overview")
    def overview(request:Request):
        actor=identity(request); args=filters(request)
        result=analytics.query_tool(actor,"overview",args)
        return {"source":"RawTree","summary":result["data"][0] if result["data"] else {},
                "agents":analytics.query_tool(actor,"agents",args)["data"],
                "trend":analytics.query_tool(actor,"timeline",args)["data"],"outbox":store.status(actor) if actor["role"]=="admin" else None}

    @app.get("/api/agents")
    def agents(request:Request): return {"items":analytics.query_tool(identity(request),"agents",filters(request))["data"],"source":"RawTree"}
    @app.get("/api/people")
    def people(request:Request): return {"items":analytics.query_tool(identity(request),"people",filters(request))["data"],"source":"RawTree"}
    @app.get("/api/usage")
    def usage(request:Request): return {"items":analytics.query_tool(identity(request),"usage",filters(request))["data"],"source":"RawTree","cost_policy":"Observed provider costs only; unknown costs remain null"}
    @app.get("/api/sessions")
    def sessions(request:Request):
        args=filters(request); rows=analytics.query_tool(identity(request),"sessions",args)["data"]
        return {"items":rows,"page":int(args.get("page",1)),"has_more":len(rows)==50,"total":None,"source":"RawTree"}
    @app.get("/api/sessions/{session_id}")
    def session(request:Request,session_id:str):
        return {"items":analytics.query_tool(identity(request),"timeline",{**filters(request),"session_id":session_id})["data"],"source":"RawTree"}

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
    def otlp(request:Request,signal:str,body:dict):
        from .collector import validate_otlp
        field={"logs":"resourceLogs","traces":"resourceSpans","metrics":"resourceMetrics"}.get(signal)
        if not field: raise HTTPException(404,"Unknown OTLP signal")
        validate_otlp(body,field)
        authorization=request.headers.get("authorization","")
        if not authorization.startswith("Bearer "): raise PermissionError("Ingestion credential required")
        return store.ingest_otlp(store.authenticate(authorization[7:],"ingest"),signal,body)

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
        rows=analytics.query_tool(actor,"errors",{**filters(request),"activity_kind":"development"})["data"]
        return {"items":[r for r in rows if int(r.get("failures",0))>=3],"source":"RawTree",
                "rule":"At least 3 development tool errors in the selected window; internal/analyst traffic excluded"}

    @app.get("/api/investigations")
    def investigations(request:Request): return {"items":store.list_investigations(identity(request))}
    @app.post("/api/investigations")
    def investigate(request:Request,body:dict):
        actor=identity(request)
        if actor["role"]=="viewer": raise PermissionError("Viewer cannot launch investigations")
        question=body.get("question","")
        if not isinstance(question,str) or not 1<=len(question)<=2000: raise ValueError("Question must contain 1–2000 characters")
        if analyst is None:
            from .intelligence import Analyst
            engine=Analyst(analytics,store)
        else: engine=analyst
        return engine.run(actor,question)

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
