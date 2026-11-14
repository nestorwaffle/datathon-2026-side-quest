import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
from devflight import Queue, Trace, redact
from devflight.core import restore_artifact, MASK
from devflight.rawtree import sync
from devflight.analyst import analyze
from devflight.adapters import import_record
from devflight.server import make_server
from copilot.pipeline import solve, Index

class FakeRawTree:
    def __init__(self): self.rows={}; self.tokens=set(); self.timeout=True
    def insert(self,table,rows,token):
        if token not in self.tokens:
            self.rows.setdefault(table,[]).extend(rows); self.tokens.add(token)
        if self.timeout:
            self.timeout=False
            raise TimeoutError("accepted, response lost")

class Tests(unittest.TestCase):
    def setUp(self):
        clean_env = dict(os.environ)
        for name in ("DEVFLIGHT_RUN_ID", "DEVFLIGHT_TRACE_ID", "DEVFLIGHT_SPAN_ID", "DEVFLIGHT_SESSION_ID"):
            clean_env.pop(name, None)
        env_patch = patch.dict(os.environ, clean_env, clear=True)
        env_patch.start(); self.addCleanup(env_patch.stop)
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.queue=Queue(self.temp.name,rotate_bytes=1800)
        self.trace=Trace(self.queue)

    def test_secret_redaction_and_types(self):
        with patch.dict(os.environ,{"RAWTREE_API_KEY":"test-exact-credential"}):
            event=self.trace.emit("llm.request",{"api_key":"secret", "prompt":"password=abc Bearer credential sk-123456789abcdef test-exact-credential"})
        self.assertNotIn("credential",json.dumps(event))
        self.assertEqual(event["data"]["api_key"],MASK)
        for value in (1,"text",True,[1],{"a":2},None): self.trace.emit("tool.result",{"value":value})
        self.assertEqual([r["data"]["value"] for r in self.queue.events()[1:]],[1,"text",True,[1],{"a":2},None])

    def test_parent_tool_rag_skill_artifact(self):
        self.trace.emit("run.started")
        with self.trace.child("worker") as child:
            with child.tool("search",{"q":"fractions"}) as result: result["hits"]=[1,2]
            child.emit("rag.retrieved",{"hits":[{"id":1}]}); child.emit("skill.invoked",{"name":"hint"})
            child.emit("eval.grade",{"success":True})
            path=Path(self.temp.name)/"skill.txt"; path.write_text("new content\npassword=fake-secret",encoding="utf-8")
            artifact=child.artifact(path,"old content\n")
            child.artifact(path)
        rows=self.queue.events()
        self.assertEqual(len({r["trace_id"] for r in rows}),1)
        self.assertEqual(rows[1]["parent_span_id"],self.trace.span_id)
        self.assertIn(b"new content",restore_artifact(rows,artifact["artifacts"][0]))
        self.assertNotIn(b"fake-secret",restore_artifact(rows,artifact["artifacts"][0]))
        self.assertEqual(sum(e["event_type"]=="artifact.chunk" for e in rows),1)

    def test_timeout_restart_and_new_events_preserve_batch(self):
        for i in range(5): self.trace.emit("tool.result",{"value":i})
        remote=FakeRawTree()
        with self.assertRaises(TimeoutError): sync(self.queue,remote,attempts=1)
        self.assertEqual(self.queue.status()["pending"],5)
        self.trace.emit("llm.response",{"text":"later"})
        sync(Queue(self.temp.name),remote,attempts=1)
        self.assertEqual(self.queue.status()["pending"],0)
        self.assertEqual(len(remote.rows["dev_events_raw"]),6)
        self.assertEqual(len({r["event_id"] for r in remote.rows["dev_events_raw"]}),6)
        self.assertEqual(len(self.queue.events()),6)

    def test_concurrency_rotation_recovery(self):
        threads=[threading.Thread(target=lambda:[Trace(self.queue).emit("ui.action",{"v":i}) for i in range(8)]) for _ in range(4)]
        for t in threads:t.start()
        for t in threads:t.join()
        with self.queue.active.open("ab") as f:f.write(b'{"partial":')
        self.trace.emit("run.finished")
        rows=self.queue.events()
        self.assertEqual(len(rows),33)
        self.assertEqual([e["sequence"] for e in rows],list(range(1,34)))
        self.assertTrue(list(self.queue.home.glob("damaged-*")))

    def evaluations(self, candidate_success=True, dataset="same", reveal=True):
        for name in ("baseline","short-prompt"):
            for i in range(3):
                trace=Trace(self.queue,kind="m3kang_eval")
                trace.emit("eval.grade",{"recipe":name,"dataset":"same" if name=="baseline" else dataset,
                    "split":"validation","recipe_config":{"prompt":name,"rag_k":0},
                    "success":True if name=="baseline" else candidate_success,"accuracy":1,
                    "seconds":10 if name=="baseline" else 8,"tokens":100 if name=="baseline" else 50,
                    "no_reveal":reveal})

    def test_analyst_promotes_and_persists(self):
        self.evaluations()
        result=analyze(self.queue,self.queue.events(),"m3kang_eval",policy=True)
        self.assertTrue(result["promoted"])
        self.assertTrue((self.queue.home/"policy-pack.json").exists())
        self.assertEqual(json.loads((self.queue.home/"recipes.json").read_text())["m3kang_eval"]["name"],"short-prompt")
        self.assertFalse(analyze(self.queue,self.queue.events(),"m3kang_eval")["promoted"])

    def test_analyst_rejects_mismatch_failure_and_leak(self):
        self.evaluations(dataset="other")
        self.assertFalse(analyze(self.queue,self.queue.events(),"m3kang_eval")["promoted"])
        with tempfile.TemporaryDirectory() as root:
            self.queue=Queue(root); self.evaluations(reveal=False)
            self.assertFalse(analyze(self.queue,self.queue.events(),"m3kang_eval",policy=True)["promoted"])
        with tempfile.TemporaryDirectory() as root:
            self.queue=Queue(root); self.evaluations(candidate_success=False)
            self.assertFalse(analyze(self.queue,self.queue.events(),"m3kang_eval")["promoted"])

    def test_adapters_preserve_unknown(self):
        for source,record in [("codex",{"type":"item.completed","item":{"type":"command_execution","aggregated_output":"full output"}}),
            ("claude",{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"path":"file"}}]}}),
            ("codex",{"type":"future_type","new_field":[1,2]})]:
            event=import_record(self.trace,source,record)
            self.assertEqual(event["data"]["record"],record)

    def test_offline_modes_and_no_remote_requests(self):
        problem={"id":"x","text":"1/2 + 1/4","language":"es","options":{"A":.5,"B":.75}}
        with patch("urllib.request.urlopen",side_effect=AssertionError("No network")),patch("copilot.pipeline.local_post",side_effect=AssertionError("No network")):
            study=solve(problem,mode="study",backend="demo",trace=self.trace)
            challenge=solve(problem,backend="demo",trace=self.trace)
        self.assertNotIn("0.75",study["hint"]); self.assertNotIn("B",study["hint"])
        self.assertEqual(challenge["answer"],"B")
        self.assertGreater(self.queue.status()["pending"],0)
        from copilot.pipeline import local_post
        with self.assertRaises(ValueError):local_post("https://example.com",{})

    def test_model_endpoint_and_safe_hint_selection(self):
        problem={"id":"x","text":"problem","options":{"A":1},"language":"en"}
        with patch("copilot.pipeline.local_post",return_value={"model":"local-qwen","choices":[{"message":{"content":"The answer is A"}}]}):
            result=solve(problem,mode="study",trace=self.trace)
        self.assertEqual(result["hint"],"What do you know, and what does the problem ask?")
        self.assertEqual(result["model"],"local-qwen")

    def test_helmcode_backend_inference(self):
        problem={"id":"h1","text":"1 + 1","options":{"A":1,"B":2},"language":"en"}
        mock_resp={"model":"deepseek-v4-flash","choices":[{"message":{"content":"B"}}],"usage":{"prompt_tokens":15}}
        with patch("copilot.pipeline.helmcode_post",return_value=mock_resp):
            res=solve(problem,backend="helmcode",trace=self.trace)
        self.assertEqual(res["answer"],"B")
        self.assertEqual(res["model"],"deepseek-v4-flash")

    def test_rag_excludes_same_problem(self):
        p={"id":"a","text":"fraction math"}
        hits=Index([p,{"id":"b","text":"fraction exercise"}]).search(p)
        self.assertEqual(hits[0][1]["id"],"b")

    def test_http_ingestion_otlp_and_private_student_data(self):
        server=make_server(self.queue,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base=f"http://127.0.0.1:{server.server_port}"
        def post(path,body):
            req=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req) as r:return json.load(r)
        self.assertIn("event_id",post("/events",{"event_type":"ui.action","data":{"password":"abc"}}))
        self.assertEqual(post("/v1/traces",{"resourceSpans":[]}),{})
        post("/solve",{"backend":"demo","mode":"study","problem":{"id":"student","text":"1 + 1"}})
        self.assertEqual(len(self.queue.events()),2)
        self.assertTrue(Queue(self.queue.home/"private").events())
        req=urllib.request.Request(base+"/events",data=b"{}",headers={"Content-Type":"application/json","Origin":"https://evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
        self.assertEqual(error.exception.code,403)

    def test_cli_captures_exit_stdout_stderr_and_child(self):
        cmd=[sys.executable,"-m","devflight","--home",self.temp.name,"run","--no-sync","--agent","test","--",sys.executable,"-c",
            "import sys; from devflight import Trace; Trace().emit('skill.invoked',{'name':'test'}); print('full stdout'); print('full stderr',file=sys.stderr); sys.exit(3)"]
        result=subprocess.run(cmd,capture_output=True)
        self.assertEqual(result.returncode,3,result.stderr)
        rows=self.queue.events()
        command=next(e for e in rows if e["event_type"]=="command.finished")
        self.assertEqual(command["data"]["stdout"],"full stdout"+os.linesep)
        self.assertEqual(command["data"]["stderr"],"full stderr"+os.linesep)
        self.assertEqual(len({e["trace_id"] for e in rows}),1)

    def test_recommendation_changes_next_process(self):
        self.evaluations()
        analyze(self.queue,self.queue.events(),"m3kang_eval")
        cmd=[sys.executable,"-m","devflight","--home",self.temp.name,"run","--no-sync","--kind","m3kang_eval","--recommend","--",sys.executable,"-c","import os,json; print(json.loads(os.environ['DEVFLIGHT_RECIPE'])['prompt'])"]
        result=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("short-prompt",result.stdout)

    def test_policy_rejects_accuracy_regression_and_latency(self):
        self.evaluations()
        rows=self.queue.events()
        for row in rows:
            if row["data"].get("recipe")=="short-prompt": row["data"]["accuracy"]=.9
        self.assertFalse(analyze(self.queue,rows,"m3kang_eval",policy=True)["promoted"])
        for row in rows:
            if row["data"].get("recipe")=="short-prompt":
                row["data"]["accuracy"]=1; row["data"]["seconds"]=11
        self.assertFalse(analyze(self.queue,rows,"m3kang_eval",policy=True)["promoted"])

    def test_board_jsonl_integration(self):
        problem={"id":"board-test","text":"6 * 7","options":{"A":36,"B":42}}
        payload="\n".join(json.dumps({"mode":mode,"problem":problem}) for mode in ("study","challenge"))+"\n"
        env=dict(os.environ,BOARD_QUEUE=str(self.queue.home/"board-private"))
        result=subprocess.run([sys.executable,"board/run.py","--demo"],input=payload,text=True,capture_output=True,env=env)
        self.assertEqual(result.returncode,0,result.stderr)
        responses=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertIn("hint",responses[0]);self.assertEqual(responses[1]["answer"],"B")
        self.assertEqual(self.queue.events(),[])

    def test_rawtree_http_contract(self):
        from devflight.rawtree import RawTree
        captured=[]
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        def fake(req,timeout):
            captured.append(req)
            return Response(b'{"written_rows":"1"}')
        with patch.dict(os.environ,{"RAWTREE_API_KEY":"fake-test-key","RAWTREE_READ_KEY":"read-only-key"}),patch("urllib.request.urlopen",side_effect=fake):
            client=RawTree();client.insert("dev_events_raw",[{"event_id":"stable"}],"stable-batch")
            self.assertIn("insert_deduplication_token=stable-batch",captured[0].full_url)
            self.assertIn("deduplicate_insert=enable",captured[0].full_url)
            wire=json.loads(captured[0].data)
            self.assertEqual(wire[0]["event_id"],"stable")
            self.assertEqual(json.loads(wire[0]["event_json"]),{"event_id":"stable"})
            with self.assertRaises(PermissionError):RawTree(read_only=True).insert("dev_events_raw",[],"x")

if __name__=="__main__":unittest.main()
