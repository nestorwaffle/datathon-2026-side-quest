import unittest
from unittest.mock import patch
import os

from devflight.intelligence import Analyst


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
