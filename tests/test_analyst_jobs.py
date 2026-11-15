"""Local test doubles only: these tests never call Helmcode or RawTree.

Added for the user's later verification; not executed during implementation.
"""
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from devflight.identity import Store
from devflight.intelligence import Analyst
from devflight.investigation_jobs import InvestigationJobs, InvestigationJournal, _fingerprint


class AnalystJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.store.bootstrap()
        self.actor = self.store.authenticate((self.store.home/"admin.token").read_text().strip(), "login")

    def blocking_engine(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        class Engine:
            def run(self, identity, question, **kwargs):
                calls.append(question)
                started.set()
                if not release.wait(5):
                    raise RuntimeError("Test double was not released")
                return {"status": "completed", "conclusion": "Test-double result; no live inference."}
        return Engine(), started, release, calls

    def test_request_retry_is_idempotent_and_conflicting_body_rejected(self):
        engine, started, release, calls = self.blocking_engine()
        manager = InvestigationJobs(self.store, engine)
        try:
            first = manager.submit(self.actor, "Investiga", request_id="retry-one")
            self.assertTrue(started.wait(2))
            retry = manager.submit(self.actor, "Investiga", request_id="retry-one")
            self.assertEqual(first["id"], retry["id"])
            with self.assertRaises(ValueError):
                manager.submit(self.actor, "Otra pregunta", request_id="retry-one")
            self.assertEqual(calls, ["Investiga"])
        finally:
            release.set()
            manager.shutdown(wait=True)
        self.assertEqual(manager.get(self.actor, first["id"])["status"], "completed")

    def test_queued_cancellation_never_invokes_second_model(self):
        engine, started, release, calls = self.blocking_engine()
        manager = InvestigationJobs(self.store, engine, max_workers=1)
        try:
            manager.submit(self.actor, "Primera", request_id="first")
            self.assertTrue(started.wait(2))
            second = manager.submit(self.actor, "Segunda", request_id="second")
            cancelled = manager.cancel(self.actor, second["id"])
            self.assertEqual(cancelled["status"], "cancelled")
        finally:
            release.set()
            manager.shutdown(wait=True)
        self.assertEqual(calls, ["Primera"])

    def test_queue_is_bounded_and_full_requests_can_be_retried(self):
        engine, started, release, calls = self.blocking_engine()
        manager = InvestigationJobs(self.store, engine, max_workers=1, max_pending=1)
        try:
            manager.submit(self.actor, "Primera", request_id="one")
            self.assertTrue(started.wait(2))
            with self.assertRaises(RuntimeError):
                manager.submit(self.actor, "Segunda", request_id="two")
            self.assertIsNone(manager.journal.by_request(self.actor, "two"))
        finally:
            release.set()
            manager.shutdown(wait=True)

    def test_restart_exposes_interruption_without_replaying_inference(self):
        journal = InvestigationJournal(self.store)
        scope = {"source_scope": "workspace", "hours": 24}
        record = {"id": "interrupted-one", "conversation_id": "conversation-one", "request_id": "request-one",
                  "status": "running", "phase": "model", "question": "Investiga", "scope": scope,
                  "calls": [{"status": "running"}], "evidence": [], "conclusion": "", "created_at": "2026-01-01T00:00:00Z"}
        journal.create(self.actor, record, _fingerprint("Investiga", scope, None))
        calls = []
        class Engine:
            def run(self, *args, **kwargs):
                calls.append(True)
        manager = InvestigationJobs(self.store, Engine())
        try:
            self.assertEqual(manager.get(self.actor, record["id"])["status"], "interrupted")
            replay = manager.submit(self.actor, "Investiga", request_id="request-one")
            self.assertEqual(replay["id"], record["id"])
            self.assertEqual(replay["status"], "interrupted")
            self.assertFalse(calls)
        finally:
            manager.shutdown(wait=True)

    def test_conversation_privacy_does_not_change_global_data_scope(self):
        journal = InvestigationJournal(self.store)
        record = {"id": "owned-one", "conversation_id": "private-conversation", "status": "completed",
                  "scope": {"source_scope": "workspace", "hours": 0}, "question": "Privada", "conclusion": "Datos globales"}
        journal.create(self.actor, record)
        member = self.store.manage(self.actor, {"kind": "user", "name": "Another member", "role": "member"})
        identity = self.store.authenticate(member["credential"], "login")
        self.assertEqual(journal.list(identity), [])
        with self.assertRaises(PermissionError):
            journal.find(identity, record["id"])
        with self.assertRaises(PermissionError):
            journal.create(identity, {**record, "id": "new-id"})
        self.assertEqual(journal.find(self.actor, record["id"])["scope"]["source_scope"], "workspace")

    def test_running_checkpoint_exists_before_provider_and_evidence_is_durable(self):
        journal = InvestigationJournal(self.store)
        seen = []
        responses = [
            {"choices": [{"message": {"tool_calls": [{"id": "call-one", "type": "function",
              "function": {"name": "errors", "arguments": '{"hours":24}'}}]}}], "usage": {"total_tokens": 25}},
            {"choices": [{"message": {"content": "Tres errores observados."}, "finish_reason": "stop"}], "usage": {"total_tokens": 25}},
        ]
        actor = self.actor
        class Client:
            model = "test-double"
            def complete(self, *args, **kwargs):
                rows = journal.list(actor)
                seen.append(rows[0])
                return responses.pop(0)
        class Queries:
            def query_tool(self, identity, name, arguments, deadline=None):
                return {"sql": "SELECT 3 AS errors", "data": [{"errors": 3}], "source": "test-double"}
        result = Analyst(Queries(), self.store, Client()).run(self.actor, "Investiga", investigation_id="durable-one")
        self.assertEqual(seen[0]["status"], "running")
        self.assertEqual(seen[0]["phase"], "model")
        self.assertEqual(seen[1]["evidence"][0]["data"], [{"errors": 3}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(journal.find(self.actor, "durable-one")["status"], "completed")
        with self.store.db() as db:
            rows = db.execute("SELECT table_name,payload FROM outbox").fetchall()
        self.assertEqual({row["table_name"] for row in rows}, {"dev_investigations", "dev_platform_events"})
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(json.loads(row["payload"]) for row in rows))

    def test_completed_job_cannot_be_overwritten_by_late_cancel(self):
        journal = InvestigationJournal(self.store)
        record = {"id": "finished", "conversation_id": "finished-conversation", "status": "completed", "conclusion": "Saved"}
        journal.create(self.actor, record)
        self.assertEqual(journal.request_cancel(self.actor, record["id"])["status"], "completed")

    def test_capacity_rejection_submits_no_job_or_inference(self):
        calls = []
        class Engine:
            def run(self, *args, **kwargs):
                calls.append(True)
        manager = InvestigationJobs(self.store, Engine())
        try:
            with patch.dict("os.environ", {"DEVFLIGHT_PLATFORM_MAX_BYTES": "1"}):
                with self.assertRaises(OSError):
                    manager.submit(self.actor, "Investiga", request_id="capacity-one")
            self.assertFalse(calls)
            self.assertIsNone(manager.journal.by_request(self.actor, "capacity-one"))
        finally:
            manager.shutdown(wait=True)
