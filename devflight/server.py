"""Loopback-only development UI and JSON/OTLP receiver."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
from .core import Trace, redact

HTML = '''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevFlight · Math Copilot</title><style>
:root{font-family:system-ui;color:#e5edf5;background:#101923}body{max-width:1060px;margin:48px auto;padding:0 24px}header{display:flex;justify-content:space-between;align-items:center}h1{font-size:40px;margin:0}small,.muted{color:#95aabb}section{background:#172532;border:1px solid #304454;border-radius:16px;padding:24px;margin:24px 0}button,select,input,textarea{font:inherit;padding:12px;border:1px solid #496070;border-radius:8px;background:#0d1720;color:inherit}button{background:#b7efb0;color:#13231b;cursor:pointer}textarea{width:calc(100% - 26px);min-height:95px}pre{white-space:pre-wrap;overflow-wrap:anywhere}label{display:block;margin:16px 0 8px}.row{display:flex;gap:12px;flex-wrap:wrap}.badge{color:#b7efb0}.result{font-size:22px;min-height:32px}table{width:100%;text-align:left}td,th{padding:10px;border-bottom:1px solid #304454}</style>
<header><div><small>DATATHON FME · LOCAL FIRST</small><h1>DevFlight</h1></div><span class="badge">● Sin dependencia de Internet</span></header>
<p class="muted">Memoria de agentes · Decisiones con evidencia · Matemáticas en el dispositivo</p>
<section><h2>Math Copilot</h2><div class="row"><select id="mode"><option value="study">Study / Teach</option><option value="challenge">Challenge / Reason</option></select><select id="backend"><option value="llama">Modelo local (llama.cpp)</option><option value="demo">Demo aritmética (sin modelo)</option></select><select id="language"><option>es</option><option>ca</option><option>en</option></select></div>
<label for="problem">Problema</label><textarea id="problem">1/2 + 1/4</textarea><label for="options">Opciones A–E (JSON)</label><input style="width:90%" id="options" value='{"A":0.25,"B":0.5,"C":0.75,"D":1,"E":1.25}'>
<label for="step">Tu paso o idea</label><input id="step" placeholder="He buscado un denominador común"><p><button id="ask">Continuar</button></p><div id="answer" class="result" aria-live="polite"></div><small id="timing"></small></section>
<section><h2>Memoria local</h2><div id="status"></div><p><button id="refresh">Actualizar</button></p><table><thead><tr><th>Evento</th><th>Agente</th><th>Estado</th></tr></thead><tbody id="events"></tbody></table></section>
<section><h2>Recetas promovidas</h2><pre id="recipes">Sin promociones</pre></section>
<script>
const byId=id=>document.getElementById(id);let token='';
async function load(){const r=await fetch('/status');const s=await r.json();byId('status').textContent=`${s.total} eventos · ${s.pending} pendientes de sincronizar`;const data=await(await fetch('/events')).json();byId('events').replaceChildren();for(const e of data.slice(-12).reverse()){const tr=document.createElement('tr');for(const v of [e.event_type,e.agent.id,e.status]){const td=document.createElement('td');td.textContent=v;tr.append(td)}byId('events').append(tr)}byId('recipes').textContent=JSON.stringify(await(await fetch('/recipes')).json(),null,2)}
byId('refresh').onclick=load;byId('ask').onclick=async()=>{byId('ask').disabled=true;byId('answer').textContent='Pensando…';try{const r=await fetch('/solve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:byId('mode').value,backend:byId('backend').value,step:byId('step').value,problem:{id:'ui',text:byId('problem').value,options:JSON.parse(byId('options').value),language:byId('language').value}})});const d=await r.json();byId('answer').textContent=d.hint||d.answer||d.error;byId('timing').textContent=`${d.backend||''} · ${Number(d.seconds||0).toFixed(2)} s · ${d.status||r.status}`;await load()}catch(e){byId('answer').textContent=e.message}finally{byId('ask').disabled=false}};load();
</script></html>'''

def make_server(queue, port=8787):
    # Student interactions use a separate never-synced queue.
    from .core import Queue
    private_queue = Queue(queue.home / "private")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, value, html=False):
            body = value.encode() if html else json.dumps(redact(value), ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers(); self.wfile.write(body)

        def trusted(self):
            host = self.headers.get("Host", "")
            valid_hosts = (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")
            return host in valid_hosts and self.headers.get("Origin", "http://" + host) == "http://" + host

        def do_GET(self):
            if not self.trusted(): return self.respond(403, {"error":"Invalid origin"})
            if self.path == "/": self.respond(200, HTML, True)
            elif self.path == "/status": self.respond(200, queue.status())
            elif self.path == "/events": self.respond(200, queue.events())
            elif self.path == "/recipes":
                path=queue.home/"recipes.json"
                self.respond(200,json.loads(path.read_text()) if path.exists() else {})
            else: self.respond(404, {"error":"Not found"})

        def do_POST(self):
            if not self.trusted(): return self.respond(403, {"error":"Invalid origin"})
            token=os.getenv("DEVFLIGHT_HTTP_TOKEN")
            if self.path != "/solve" and token and not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                return self.respond(401, {"error":"Unauthorized"})
            try:
                length=int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 4*1024*1024: return self.respond(413, {"error":"Body must be between 1 byte and 4 MiB"})
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self.respond(415, {"error":"Use OTLP/HTTP JSON; protobuf is not supported by this local receiver"})
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict): raise ValueError("Expected JSON object")
                if self.path == "/solve":
                    from copilot.pipeline import solve
                    trace=Trace(private_queue,agent="board-ui")
                    trace.emit("ui.action",body)
                    result=solve(body["problem"],mode=body.get("mode","study"),backend=body.get("backend","llama"),step=body.get("step",""),trace=trace)
                    return self.respond(200,result)
                trace=Trace(queue,agent=body.get("agent","http") if isinstance(body.get("agent","http"),str) else "http")
                context=body.get("context",{})
                import re
                for key,size in (("trace_id",32),("span_id",16),("parent_span_id",16)):
                    if key in context:
                        if not re.fullmatch("[a-fA-F0-9]{"+str(size)+"}",context[key]): raise ValueError("Invalid trace context")
                        setattr(trace,key,context[key])
                if self.path == "/events":
                    event=trace.emit(body["event_type"],body.get("data",{}))
                    self.respond(201,{"event_id":event["event_id"]})
                elif self.path in ("/v1/traces","/v1/logs","/v1/metrics"):
                    signal=self.path.rsplit("/",1)[1]
                    field={"traces":"resourceSpans","logs":"resourceLogs","metrics":"resourceMetrics"}[signal]
                    if not isinstance(body.get(field),list): raise ValueError("Missing OTLP resource array")
                    trace.emit("otel."+signal,body); self.respond(200,{})
                else: self.respond(404,{"error":"Not found"})
            except (ValueError, KeyError, TypeError) as error:
                self.respond(400,{"error":str(error)})
    return ThreadingHTTPServer(("127.0.0.1",port),Handler)

def serve(queue,port=8787):
    server=make_server(queue,port)
    print(f"DevFlight: http://127.0.0.1:{server.server_port}",flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
