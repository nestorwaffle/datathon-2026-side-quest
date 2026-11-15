import unittest
from unittest.mock import patch
import os
import json
import tempfile

from devflight.intelligence import Analyst, normalize_scope, narrow_scope


class IntelligenceTests(unittest.TestCase):
    def run_agent(self, responses, env=None):
        class Client:
            model = "test-double-no-inference"
            def complete(self, *args, **kwargs): return responses.pop(0)
        class Analytics:
            def __init__(self): self.calls = []
            def query_tool(self, identity, name, args):
                self.calls.append((identity, name, args))
                return {"sql": "SELECT count() WHERE org_id = 'authorized'", "data": [{"errors": 3}], "source": "test-double"}
        class Store:
            def __init__(self): self.records = []
            def save_investigation(self, identity, record): self.records.append(record.copy())
        analytics, store = Analytics(), Store()
        with patch.dict(os.environ, env or {}):
            record = Analyst(analytics, store, Client()).run({"org_id": "authorized"}, "Investiga errores")
        self.assertEqual(len(store.records), 1)
        return record, analytics

    def tool(self, name="errors", arguments='{"hours":24}'):
        return {"choices": [{"message": {"tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": name, "arguments": arguments}}]}}], "usage": {"total_tokens": 25}}

    def test_real_loop_contract_preserves_evidence_and_authorization(self):
        record, analytics = self.run_agent([self.tool(), {"choices": [{"message": {"content": "Tres errores; revisar la herramienta."}}]}])
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["query_count"], 1)
        self.assertEqual(analytics.calls[0][0], {"org_id": "authorized"})
        self.assertEqual(record["evidence"][0]["data"], [{"errors": 3}])

    def test_no_tools_is_never_reported_as_investigation(self):
        record, analytics = self.run_agent([{"choices": [{"message": {"content": "Invented answer"}}]}])
        self.assertEqual(record["status"], "no_tool_evidence")
        self.assertEqual(record["conclusion"], "")
        self.assertFalse(analytics.calls)

    def test_arbitrary_sql_tool_and_org_arguments_rejected(self):
        for response in (self.tool("run_sql", '{"sql":"DROP TABLE x"}'), self.tool(arguments='{"hours":24,"org_id":"victim"}')):
            record, analytics = self.run_agent([response])
            self.assertEqual(record["status"], "failed")
            self.assertFalse(analytics.calls)

    def test_iteration_budget_stops_infinite_tool_loop(self):
        record, _ = self.run_agent([self.tool()], {"DEVFLIGHT_ANALYST_MAX_ITERATIONS": "1"})
        self.assertEqual(record["status"], "iteration_budget_exhausted")
        self.assertEqual(record["iterations"], 1)

    def test_invalid_arguments_never_reach_query_builder(self):
        for arguments in ('[]', '{"hours":10000}', '{"hours":true}', '{"hours":24,"session_id":{}}'):
            record, analytics = self.run_agent([self.tool(arguments=arguments)])
            self.assertEqual(record["status"], "failed")
            self.assertFalse(analytics.calls)

    def test_global_scope_and_all_history_can_only_be_narrowed(self):
        self.assertEqual(normalize_scope(), {"source_scope": "workspace", "hours": 24})
        scope = normalize_scope({"hours": 0, "provider": "codex"})
        self.assertEqual(narrow_scope(scope, {"hours": 168})["provider"], "codex")
        with self.assertRaises(ValueError):
            narrow_scope(scope, {"hours": 24, "provider": "claude"})
        with self.assertRaises(ValueError):
            narrow_scope(normalize_scope({"hours": 24}), {"hours": 0})
        with self.assertRaises(ValueError):
            narrow_scope(scope, {"hours": 24, "source_scope": "organization"})

    def test_final_answer_cannot_skip_reported_token_budget(self):
        final = {"choices": [{"message": {"content": "Conclusión parcial"}, "finish_reason": "stop"}],
                 "usage": {"total_tokens": 700}}
        first = self.tool()
        first["usage"]["total_tokens"] = 100
        with patch("devflight.intelligence._estimate_tokens", return_value=20):
            record, _ = self.run_agent([first, final], {"DEVFLIGHT_ANALYST_TOTAL_TOKENS": "512"})
        self.assertEqual(record["status"], "token_budget_exhausted")
        self.assertEqual(record["usage"]["total_tokens"], 800)
        self.assertEqual(record["conclusion"], "Conclusión parcial")

    def test_provider_truncation_is_never_completed(self):
        final = {"choices": [{"message": {"content": "La respuesta se cortó"}, "finish_reason": "length"}],
                 "usage": {"total_tokens": 25}}
        record, _ = self.run_agent([self.tool(), final])
        self.assertEqual(record["status"], "truncated")
        self.assertTrue(record["truncated"])
        self.assertTrue(record["partial"])

    def test_deadline_stops_before_remaining_queries_and_is_propagated(self):
        clock = [0.0]
        seen = []
        response = self.tool()
        response["choices"][0]["message"]["tool_calls"] *= 4
        class Client:
            model = "test-double"
            def complete(self, *args, **kwargs):
                return response
        class Queries:
            def query_tool(self, identity, name, args, deadline=None):
                seen.append(deadline)
                clock[0] += 8
                return {"data": [{"errors": 3}], "source": "test-double", "sql": "SELECT 1"}
        class Memory:
            def save_investigation(self, identity, record):
                pass
        with patch("devflight.intelligence.time.monotonic", side_effect=lambda: clock[0]), patch.dict(os.environ, {"DEVFLIGHT_ANALYST_TIMEOUT": "5"}):
            record = Analyst(Queries(), Memory(), Client()).run({"org_id": "test"}, "Investiga")
        self.assertEqual(record["status"], "timeout")
        self.assertEqual(record["query_count"], 1)
        self.assertEqual(seen, [5.0])

    def test_capacity_failure_happens_before_inference(self):
        from devflight.identity import Store
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as home:
            store = Store(home)
            store.bootstrap()
            identity = store.authenticate((store.home/"admin.token").read_text().strip(), "login")
            client = Mock(model="test-double")
            with patch.dict(os.environ, {"DEVFLIGHT_PLATFORM_MAX_BYTES": "1"}):
                with self.assertRaises(OSError):
                    Analyst(Mock(), store, client).run(identity, "Investiga")
            client.complete.assert_not_called()

    def test_federated_sql_is_audited_but_does_not_displace_model_evidence(self):
        long_sql = "SELECT " + ("observed_column, "*12000) + "1"
        messages_seen = []
        responses = [self.tool(), {"choices": [{"message": {"content": "Hay tres errores"}}], "usage": {"total_tokens": 25}}]
        class Client:
            model = "test-double"
            def complete(self, messages, *args, **kwargs):
                messages_seen.append(json.loads(json.dumps(messages)))
                return responses.pop(0)
        class Queries:
            def query_tool(self, *args, **kwargs):
                return {"sql": long_sql, "data": [{"errors": 3}], "source": "test-double", "coverage": {"sources": 4}}
        class Memory:
            def save_investigation(self, identity, record):
                pass
        record = Analyst(Queries(), Memory(), Client()).run({"org_id": "test"}, "Investiga")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["evidence"][0]["sql"], long_sql)
        tool = json.loads(next(message["content"] for message in messages_seen[1] if message["role"] == "tool"))
        self.assertEqual(tool["data"], [{"errors": 3}])
        self.assertEqual(len(tool["sql_hash"]), 64)
        self.assertNotIn(long_sql, json.dumps(tool))

    def test_followup_includes_old_scope_but_queries_the_new_scope(self):
        seen = []
        responses = [self.tool(arguments='{"hours":24}'), {"choices": [{"message": {"content": "Respuesta nueva"}}], "usage": {"total_tokens": 25}}]
        class Client:
            model = "test-double"
            def complete(self, messages, *args, **kwargs):
                seen.append(json.loads(json.dumps(messages)))
                return responses.pop(0)
        class Queries:
            def query_tool(self, identity, name, args):
                self.args = args
                return {"data": [{"errors": 3}], "source": "test-double"}
        class Memory:
            def save_investigation(self, identity, record):
                pass
        queries = Queries()
        record = Analyst(queries, Memory(), Client()).run({"org_id": "test"}, "¿Y Claude?",
            scope={"hours": 168, "provider": "claude"}, conversation_id="conversation-one",
            history=[{"question": "¿Cómo va Codex?", "conclusion": "Observación anterior", "scope": {"provider": "codex", "hours": 24}, "status": "completed"}])
        self.assertEqual(record["conversation_id"], "conversation-one")
        self.assertEqual(queries.args["provider"], "claude")
        self.assertEqual(queries.args["source_scope"], "workspace")
        self.assertIn("Observación anterior", json.dumps(seen[0], ensure_ascii=False))

    def test_last_iteration_reserves_synthesis_without_tools(self):
        tool_counts = []
        responses = [self.tool(), self.tool(), {"choices": [{"message": {"content": "Conclusión con evidencia"}}], "usage": {"total_tokens": 25}}]
        class Client:
            model = "test-double"
            def complete(self, messages, tools, *args, **kwargs):
                tool_counts.append(len(tools))
                return responses.pop(0)
        class Queries:
            def query_tool(self, *args, **kwargs):
                return {"data": [{"errors": 3}], "source": "test-double"}
        class Memory:
            def save_investigation(self, identity, record):
                pass
        record = Analyst(Queries(), Memory(), Client()).run({"org_id": "test"}, "Investiga")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(tool_counts[-1], 0)
