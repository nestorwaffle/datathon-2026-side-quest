"""Regression fixtures for documented provider formats and durable acknowledgments.

These tests are local only: no provider inference, RawTree credentials or remote
ingestion are needed. They were added for the user's own verification run.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from devflight.core import Queue, Trace
from devflight.identity import Store
from devflight.normalization import normalize_event, normalize_otlp


def attrs(**values):
    def value(item):
        if isinstance(item, bool): return {"boolValue": item}
        if isinstance(item, int): return {"intValue": str(item)}
        if isinstance(item, float): return {"doubleValue": item}
        return {"stringValue": item}
    return [{"key": key, "value": value(item)} for key, item in values.items()]


def log(record, service="codex", **resource):
    return {"resourceLogs": [{"resource": {"attributes": attrs(**{"service.name": service, **resource})},
                              "scopeLogs": [{"logRecords": [record]}]}]}


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(self.temporary.name)
        self.identity = self.store.authenticate(self.store.bootstrap().read_text(), "login")

    def rows(self):
        with self.store.db() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM outbox ORDER BY created,id")]

    def test_legacy_sdk_envelope_keeps_context_usage_and_reported_origin(self):
        row = self.store.ingest(self.identity, {
            "schema_version": 1, "event_id": "stable-sdk-id", "event_type": "llm.usage",
            "org_id": "forged-org", "user_id": "forged-user", "developer_id": "developer-alice",
            "project_id": "external-repository", "session_id": "session-a",
            "agent": {"id": "codex", "model": "actual-model"},
            "context": {"trace_id": "a" * 32, "span_id": "b" * 16},
            "data": {"usage": {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 40,
                               "cost_usd": .3, "scope": "turn"}},
        })
        self.assertEqual((row["org_id"], row["user_id"], row["ingest_user_id"]),
                         (self.identity["org_id"], self.identity["user_id"], self.identity["user_id"]))
        self.assertEqual(row["origin_user_id"], "developer-alice")
        self.assertEqual(row["origin_id_source"], "developer_id")
        self.assertFalse(row["origin_identity_verified"])
        self.assertEqual((row["agent"], row["model"], row["provider"]), ("codex", "actual-model", "openai"))
        self.assertEqual((row["trace_id"], row["span_id"]), ("a" * 32, "b" * 16))
        self.assertEqual((row["input_tokens"], row["output_tokens"], row["cached_tokens"], row["observed_cost_usd"]), (100, 20, 40, .3))
        self.assertEqual(row["usage_kind"], "request")
        self.assertEqual(row["origin_project_id"], "external-repository")
        self.assertIsNone(row["project_id"])
        self.assertEqual(row["source_event_id"], "stable-sdk-id")

    def test_shared_ingest_actor_does_not_replace_originating_people(self):
        first=self.store.ingest(self.identity,{"event_id":"a","origin_user_id":"alice","agent":"codex"})
        second=self.store.ingest(self.identity,{"event_id":"b","origin_user_id":"bob","agent":"claude_code"})
        unknown=self.store.ingest(self.identity,{"event_id":"c","agent":"third-client"})
        self.assertEqual(first["ingest_user_id"],second["ingest_user_id"])
        self.assertEqual({first["origin_user_id"],second["origin_user_id"]},{"alice","bob"})
        self.assertIsNone(unknown["origin_user_id"])

    def test_codex_completed_event_name_and_numeric_strings(self):
        record = {"timeUnixNano": "1700000000000000123", "observedTimeUnixNano": "1700000000000000999",
                  "attributes": attrs(**{"event.name": "codex.sse_event", "event.kind": "response.completed",
                                          "input_token_count": "100", "output_token_count": "20",
                                          "cached_token_count": 40, "reasoning_token_count": 8,
                                          "model": "actual-model", "conversation.id": "source-session",
                                          "user.id": "real-developer"})}
        result = self.store.ingest_otlp(self.identity, "logs", log(record))
        self.assertEqual(result["persisted"], 1)
        row = self.rows()[0]
        self.assertEqual(row["event_type"], "codex.sse_event")
        self.assertEqual((row["input_tokens"], row["output_tokens"], row["cached_tokens"], row["reasoning_tokens"]), (100, 20, 40, 8))
        self.assertEqual(row["occurred_at_unix_nano"], "1700000000000000123")
        self.assertEqual(row["origin_user_id"], "real-developer")
        self.assertEqual(row["usage_kind"], "request")
        # A retry's collector-observed timestamp is not a new source event.
        record["observedTimeUnixNano"] = "1700000000000001999"
        self.assertEqual(self.store.ingest_otlp(self.identity,"logs",log(record))["duplicates"], 1)
        self.assertEqual(len(self.rows()), 1)

    def test_claude_request_retains_cache_cost_duration_and_failure_fields(self):
        request = {"eventName": "claude_code.api_request", "timeUnixNano": "1700000000000000000",
                   "attributes": attrs(**{"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 40,
                                           "cache_creation_tokens": 5, "cost_usd": .3, "duration_ms": 250,
                                           "model": "claude-model", "session.id": "claude-session", "request_id": "request-one"})}
        row=normalize_otlp("logs",log(request,"claude_code"))[0]
        self.assertEqual((row["cached_tokens"],row["cache_creation_tokens"],row["observed_cost_usd"],row["duration_ms"]),(40,5,.3,250))
        self.assertEqual(row["request_id"],"request-one")
        failed={"eventName":"claude_code.tool_result","severityNumber":9,
                "attributes":attrs(**{"success":"false","tool_name":"Bash","error_type":"ShellError","duration_ms":"150"})}
        row=normalize_otlp("logs",log(failed,"claude_code"))[0]
        self.assertEqual((row["status"],row["tool"],row["error_type"],row["duration_ms"]),("error","Bash","ShellError",150))

    def test_all_otlp_metric_types_preserve_values_without_summing_as_usage(self):
        points = [
            {"name":"cpu","unit":"1","gauge":{"dataPoints":[{"asDouble":.75,"timeUnixNano":"1000"}]}},
            {"name":"tokens","sum":{"aggregationTemporality":2,"isMonotonic":True,"dataPoints":[{"asInt":"200","startTimeUnixNano":"500","timeUnixNano":"1000","attributes":attrs(input_tokens=200)}]}},
            {"name":"latency","histogram":{"aggregationTemporality":1,"dataPoints":[{"count":"3","sum":6.0,"min":1.0,"max":3.0,"explicitBounds":[2.0],"bucketCounts":["2","1"],"timeUnixNano":"1000"}]}},
            {"name":"summary","summary":{"dataPoints":[{"count":"3","sum":6.0,"quantileValues":[{"quantile":.5,"value":2.0}],"timeUnixNano":"1000"}]}},
            {"name":"exp","exponentialHistogram":{"aggregationTemporality":2,"dataPoints":[{"count":"3","sum":6.0,"scale":-1,"zeroCount":"0","positive":{"offset":-2,"bucketCounts":["1","2"]},"negative":{"offset":0,"bucketCounts":[]},"timeUnixNano":"1000"}]}},
        ]
        body={"resourceMetrics":[{"scopeMetrics":[{"metrics":points}]}]}
        self.assertEqual(self.store.ingest_otlp(self.identity,"metrics",body)["persisted"],5)
        rows={row["metric_name"]:row for row in self.rows()}
        self.assertEqual(rows["cpu"]["metric_value"],.75)
        self.assertEqual(rows["tokens"]["metric_value"],200)
        self.assertEqual(rows["tokens"]["metric_temporality"],"cumulative")
        self.assertEqual(rows["latency"]["metric_data"]["bucketCounts"],[2,1])
        self.assertEqual(rows["summary"]["metric_data"]["quantileValues"],[{"quantile":.5,"value":2.0}])
        self.assertEqual(rows["exp"]["metric_data"]["positive"],{"offset":-2,"bucketCounts":[1,2]})
        for row in rows.values():
            self.assertIsNone(row["input_tokens"])
            self.assertEqual(row["usage_kind"],"metric_sample")

    def test_unsupported_signal_is_rejected_before_any_acknowledgment(self):
        body={"resourceMetrics":[{"scopeMetrics":[{"metrics":[{"name":"unsupported","unrecognizedMetric":{"dataPoints":[{}]}}]}]}]}
        with self.assertRaises(ValueError): self.store.ingest_otlp(self.identity,"metrics",body)
        self.assertEqual(self.rows(),[])

    def test_content_is_omitted_and_malformed_usage_is_not_silently_accepted(self):
        record={"eventName":"usage","attributes":attrs(**{"input_tokens":"12","prompt":"private prompt content","api_key":"private credential","user.id":"alice"})}
        row=normalize_otlp("logs",log(record))[0]
        self.assertNotIn("private prompt content",json.dumps(row))
        self.assertNotIn("private credential",json.dumps(row))
        self.assertEqual(row["input_tokens"],12)
        with self.assertRaises(ValueError): normalize_event({"input_tokens":"NaN"})
        with self.assertRaises(ValueError): normalize_event({"input_tokens":True})
        with self.assertRaises(ValueError): normalize_event({"input_tokens":1.5})

    def test_safe_evaluation_retains_comparability_without_private_prompt(self):
        row=normalize_event({"event_type":"eval.grade","data":{"recipe":"candidate","dataset":"same","split":"validation","suite_version":"v1","hardware":"cpu","accuracy":.9,"sample_size":20,"seconds":2,"tokens":200,"recipe_config":{"prompt":"private prompt","rag_k":3},"problem":"private question","answer":"private answer"}})
        self.assertEqual(row["evaluation"]["sample_size"],20)
        self.assertEqual(row["evaluation"]["recipe_config"],{"rag_k":3})
        self.assertEqual(len(row["evaluation"]["recipe_config_hash"]),64)
        self.assertNotIn("private",json.dumps(row))

    def test_missing_writer_configuration_is_a_visible_durable_error(self):
        self.store.ingest(self.identity,{"event_id":"pending"})
        with patch.dict(os.environ,{"DEVFLIGHT_OFFLINE":"0"}), patch("devflight.rawtree.RawTree",side_effect=ValueError("Configure RAWTREE_API_KEY")):
            with self.assertRaises(ValueError): self.store.sync_once()
        status=Store(self.temporary.name).status(self.identity)
        self.assertEqual(status["pending"],1)
        self.assertEqual(status["retries"],1)
        self.assertIn("Configure",status["last_error"])
        self.assertIsNotNone(status["last_attempt"])
        self.assertIsNotNone(status["oldest_pending"])

    def test_offline_outbox_and_atomic_terminal_investigation(self):
        record={"id":"investigation-one","status":"complete","conclusion":"A conclusion"}
        usage={"event_id":"usage-one","event_type":"llm.usage","input_tokens":10,"output_tokens":5}
        self.store.save_analyst_result(self.identity,record,usage)
        self.assertEqual(self.store.status()["pending"],2)
        with patch.dict(os.environ,{"DEVFLIGHT_OFFLINE":"1"}),patch("devflight.rawtree.RawTree",side_effect=AssertionError("No network")):
            self.assertEqual(self.store.sync_once(),0)
        with self.assertRaises(ValueError):
            self.store.save_analyst_result(self.identity,{"id":"invalid-result"},{"input_tokens":-1})
        self.assertEqual(len(self.store.list_investigations(self.identity)),1)

    def test_external_retry_id_is_deduplicated_in_legacy_queue_too(self):
        queue=Queue(Path(self.temporary.name)/"legacy")
        trace=Trace(queue)
        first=trace.emit("tool.result",{"value":1},event_id="client-stable-event")
        second=Trace(queue).emit("tool.result",{"value":1},event_id="client-stable-event")
        self.assertEqual(first,second)
        self.assertEqual(len(queue.events()),1)

    @unittest.skipUnless(shutil.which("node"),"Node is needed for the JavaScript SDK check")
    def test_javascript_sdk_retries_identical_prepared_event_after_lost_reply(self):
        sdk=(Path(__file__).resolve().parents[1]/"sdk"/"devflight.mjs").as_uri()
        program="""
import {DevFlight} from SDK;
const packets=[];
globalThis.fetch=async (url,options)=>{
 packets.push({url,body:options.body});
 if(packets.length===1) throw new Error('accepted but reply lost');
 return {ok:true,json:async()=>({event_id:JSON.parse(options.body).event_id})};
};
const sdk=new DevFlight({endpoint:'http://127.0.0.1:8788',attempts:2});
const prepared=await sdk.prepare('llm.usage',{input_tokens:10},'codex');
await sdk.send(prepared);
if(packets.length!==2 || packets[0].body!==packets[1].body || !packets[0].url.endsWith('/api/events')) throw new Error('retry identity changed');
""".replace("SDK",json.dumps(sdk))
        result=subprocess.run([shutil.which("node"),"--input-type=module","-e",program],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=="__main__": unittest.main()
