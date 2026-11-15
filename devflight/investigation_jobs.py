"""Durable, bounded asynchronous investigations with retry-safe submission.

A request ID identifies one inference job, not a retry permission. Restarted jobs
are exposed as interrupted and are never automatically re-executed. Conversations
are private to the local actor; their analytics scope can cover the shared space.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import inspect
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid

from .core import redact

ACTIVE = frozenset({"queued", "running", "cancelling"})
LOGGER = logging.getLogger(__name__)


def _identifier(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Invalid " + name)
    return value


def _space():
    from .shared import source_descriptor
    return source_descriptor()["id"]


def _fingerprint(question, scope, conversation_id):
    return hashlib.sha256(json.dumps([question.strip(), scope, conversation_id], sort_keys=True,
                                    ensure_ascii=False).encode()).hexdigest()


class InvestigationJournal:
    def __init__(self, store):
        self.store = store
        self.workspace = _space()
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS analyst_jobs(
                    id TEXT PRIMARY KEY,workspace TEXT NOT NULL,owner_org TEXT NOT NULL,
                    owner_user TEXT NOT NULL,conversation_id TEXT NOT NULL,request_id TEXT,
                    fingerprint TEXT,created REAL NOT NULL,updated REAL NOT NULL,
                    status TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS analyst_jobs_request
                    ON analyst_jobs(workspace,owner_org,owner_user,request_id);
                CREATE INDEX IF NOT EXISTS analyst_jobs_conversation
                    ON analyst_jobs(workspace,owner_org,owner_user,conversation_id,created);
            ''')

    def _owner(self, identity):
        return (self.workspace, identity["org_id"], identity["user_id"])

    def find(self, identity, investigation_id):
        _identifier(investigation_id, "investigation ID")
        with self.store.db() as db:
            row = db.execute("SELECT * FROM analyst_jobs WHERE id=?", (investigation_id,)).fetchone()
        if row is None:
            return None
        if (row["workspace"], row["owner_org"], row["owner_user"]) != self._owner(identity):
            raise PermissionError("Investigation belongs to another conversation owner or data space")
        return json.loads(row["payload"])

    def by_request(self, identity, request_id, fingerprint=None):
        with self.store.db() as db:
            row = db.execute("SELECT fingerprint,payload FROM analyst_jobs WHERE workspace=? AND owner_org=? AND owner_user=? AND request_id=?",
                             (*self._owner(identity), request_id)).fetchone()
        if row is None:
            return None
        if fingerprint is not None and row["fingerprint"] != fingerprint:
            raise ValueError("request_id already belongs to a different question or scope")
        return json.loads(row["payload"])

    def create(self, identity, record, fingerprint=None):
        _identifier(record["id"], "investigation ID")
        _identifier(record["conversation_id"], "conversation ID")
        if record.get("request_id"):
            _identifier(record["request_id"], "request ID")
        if hasattr(self.store, "check_capacity"):
            self.store.check_capacity()
        payload = json.dumps(redact(record), ensure_ascii=False, allow_nan=False)
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if record.get("request_id"):
                old = db.execute("SELECT fingerprint,payload FROM analyst_jobs WHERE workspace=? AND owner_org=? AND owner_user=? AND request_id=?",
                                 (*self._owner(identity), record["request_id"])).fetchone()
                if old is not None:
                    if old["fingerprint"] != fingerprint:
                        raise ValueError("request_id already belongs to a different question or scope")
                    return json.loads(old["payload"]), False
            # A caller cannot attach a conversation ID that belongs to someone else.
            owners = db.execute("SELECT DISTINCT workspace,owner_org,owner_user FROM analyst_jobs WHERE conversation_id=?",
                                (record["conversation_id"],)).fetchall()
            if any(tuple(owner) != self._owner(identity) for owner in owners):
                raise PermissionError("Conversation belongs to another owner or data space")
            now = time.time()
            db.execute("INSERT INTO analyst_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                record["id"], *self._owner(identity), record["conversation_id"], record.get("request_id"),
                fingerprint, now, now, record["status"], payload))
        return record, True

    def save(self, identity, record):
        payload = json.dumps(redact(record), ensure_ascii=False, allow_nan=False)
        with self.store.db() as db:
            result = db.execute("UPDATE analyst_jobs SET status=?,updated=?,payload=? WHERE id=? AND workspace=? AND owner_org=? AND owner_user=?",
                (record["status"], time.time(), payload, record["id"], *self._owner(identity)))
            if result.rowcount != 1:
                raise PermissionError("Investigation checkpoint owner mismatch")

    def request_cancel(self, identity, investigation_id):
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,payload FROM analyst_jobs WHERE id=? AND workspace=? AND owner_org=? AND owner_user=?",
                             (investigation_id, *self._owner(identity))).fetchone()
            if row is None:
                raise KeyError("Investigation not found")
            record = json.loads(row["payload"])
            if row["status"] not in ACTIVE:
                return record
            record.update(status="cancelling", cancel_requested=True,
                cancellation_note="No se iniciarán más pasos; la llamada en curso puede terminar y consumir tokens.")
            db.execute("UPDATE analyst_jobs SET status='cancelling',updated=?,payload=? WHERE id=?",
                       (time.time(), json.dumps(record, ensure_ascii=False, allow_nan=False), investigation_id))
            return record

    def list(self, identity, conversation_id=None, limit=100):
        where = "workspace=? AND owner_org=? AND owner_user=?"
        args = list(self._owner(identity))
        if conversation_id is not None:
            _identifier(conversation_id, "conversation ID")
            where += " AND conversation_id=?"
            args.append(conversation_id)
        with self.store.db() as db:
            rows = db.execute("SELECT payload FROM analyst_jobs WHERE "+where+" ORDER BY created DESC LIMIT ?",
                              (*args, min(200, max(1, int(limit))))).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def history(self, identity, conversation_id, exclude=None):
        rows = self.list(identity, conversation_id, limit=12)
        return list(reversed([row for row in rows if row["id"] != exclude and row["status"] not in ACTIVE][:4]))

    def recover_interrupted(self):
        """Persist the interruption; do not replay a possibly billed model call."""
        recovered = []
        with self.store.db() as db:
            rows = db.execute("SELECT * FROM analyst_jobs WHERE workspace=? AND status IN ('queued','running','cancelling')",
                              (self.workspace,)).fetchall()
            for row in rows:
                record = json.loads(row["payload"])
                record.update(status="interrupted", phase="interrupted", partial=bool(record.get("evidence") or record.get("calls")),
                    error="El proceso se interrumpió. Se conserva el progreso; no se repitió ninguna inferencia automáticamente.")
                record.setdefault("progress_events", []).append({"at": _stamp(), "phase": "interrupted", "message": record["error"]})
                db.execute("UPDATE analyst_jobs SET status='interrupted',updated=?,payload=? WHERE id=?",
                           (time.time(), json.dumps(record, ensure_ascii=False, allow_nan=False), record["id"]))
                recovered.append(({"org_id": row["owner_org"], "user_id": row["owner_user"], "role": "member"}, record))
        return recovered


def _stamp():
    from .intelligence import stamp
    return stamp()


class InvestigationJobs:
    def __init__(self, store, analyst_factory, max_workers=2, max_pending=8, recover=True):
        self.store, self.analyst_factory = store, analyst_factory
        self.journal = InvestigationJournal(store)
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max(1, min(int(max_pending), 16)))
        self._executor = ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), 2)), thread_name_prefix="devflight-analyst")
        self._futures, self._cancel, self._identities, self._volatile = {}, {}, {}, {}
        self._volatile_owners = {}
        self._closed = False
        if recover:
            for actor, record in self.journal.recover_interrupted():
                try:
                    self.store.save_investigation(actor, record)
                except Exception as error:
                    LOGGER.error("Could not queue recovered investigation %s: %s", record["id"], type(error).__name__)
                    record["persistence_status"] = "local_checkpoint_only"
                    record["audit_error"] = redact(str(error))[:240]
                    self.journal.save(actor, record)

    def submit(self, identity, question, scope=None, conversation_id=None, request_id=None):
        from .intelligence import normalize_scope
        if identity.get("role") == "viewer":
            raise PermissionError("Viewer cannot launch investigations")
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            raise ValueError("Question must contain 1..2000 characters")
        scope = normalize_scope(scope)
        if conversation_id is not None:
            _identifier(conversation_id, "conversation ID")
        request_id = request_id or str(uuid.uuid4())
        _identifier(request_id, "request ID")
        fingerprint = _fingerprint(question, scope, conversation_id)
        previous = self.journal.by_request(identity, request_id, fingerprint)
        if previous is not None:
            return self._accepted(previous)
        with self._lock:
            if self._closed:
                raise RuntimeError("Analyst is shutting down; retry after restart")
        if not self._slots.acquire(blocking=False):
            raise RuntimeError("Investigation queue is full; retry the same request_id shortly")
        record = {"id": str(uuid.uuid4()), "request_id": request_id,
                  "conversation_id": conversation_id or str(uuid.uuid4()), "question": redact(question.strip()),
                  "scope": scope, "status": "queued", "phase": "queued", "created_at": _stamp(),
                  "timestamp": _stamp(), "conclusion": "", "evidence": [], "usage": {}, "calls": [],
                  "iterations": 0, "query_count": 0, "cost_usd": None,
                  "progress_events": [{"at": _stamp(), "phase": "queued", "message": "Investigación guardada y en espera."}]}
        try:
            record, created = self.journal.create(identity, record, fingerprint)
            if not created:
                self._slots.release()
                return self._accepted(record)
            cancel = threading.Event()
            with self._lock:
                self._cancel[record["id"]] = cancel
                self._identities[record["id"]] = dict(identity)
                self._volatile_owners[record["id"]] = self.journal._owner(identity)
            future = self._executor.submit(self._run, dict(identity), record, cancel)
            with self._lock:
                self._futures[record["id"]] = future
            future.add_done_callback(lambda completed, job_id=record["id"]: self._finished(job_id, completed))
        except Exception as error:
            # Failure to launch a persisted job must not leave it queued forever.
            try:
                existing = self.journal.find(identity, record["id"])
                if existing is not None and existing["status"] == "queued":
                    existing.update(status="failed", phase="failed", error=redact(str(error))[:300])
                    self.journal.save(identity, existing)
            except Exception as persistence_error:
                LOGGER.error("Could not persist launch failure: %s", type(persistence_error).__name__)
            with self._lock:
                self._cancel.pop(record["id"], None)
                self._identities.pop(record["id"], None)
            self._slots.release()
            raise
        return self._accepted(record)

    @staticmethod
    def _accepted(record):
        return {"id": record["id"], "status": record["status"], "conversation_id": record["conversation_id"],
                "request_id": record.get("request_id")}

    def _checkpoint(self, record):
        # Analyst already persisted the checkpoint. This copy also lets the API
        # disclose a physical disk failure that prevents the final write.
        with self._lock:
            self._volatile[record["id"]] = record

    def _run(self, identity, record, cancel):
        result = None
        try:
            if cancel.is_set():
                return self._finish_cancelled(identity, record)
            engine = self.analyst_factory() if callable(self.analyst_factory) else self.analyst_factory
            parameters = inspect.signature(engine.run).parameters
            options = {"scope": record["scope"], "conversation_id": record["conversation_id"],
                       "investigation_id": record["id"], "progress": self._checkpoint,
                       "cancellation": cancel.is_set,
                       "history": self.journal.history(identity, record["conversation_id"], exclude=record["id"])}
            accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
            options = {key: value for key, value in options.items() if accepts_kwargs or key in parameters}
            result = engine.run(identity, record["question"], **options)
            if not isinstance(result, dict):
                raise ValueError("Invalid investigation result")
            result = {**record, **result, "id": record["id"], "conversation_id": record["conversation_id"]}
            self._checkpoint(result)
            self.journal.save(identity, result)
            return result
        except Exception as error:
            if result is not None:
                # A failed last checkpoint must not replace the completed answer
                # with the earlier, possibly empty, durable running record.
                current = dict(result)
                current.update(status="persistence_failed", phase="persistence_failed", persistence_status="failed",
                               error="No se pudo guardar el último estado: "+redact(str(error))[:240])
            else:
                try:
                    current = self.journal.find(identity, record["id"]) or record
                except (OSError, sqlite3.Error):
                    with self._lock:
                        current = dict(self._volatile.get(record["id"], record))
                current.update(status="failed", phase="failed", error=redact(str(error))[:300])
            try:
                self.journal.save(identity, current)
                self.store.save_investigation(identity, current)
            except Exception as persistence_error:
                current["persistence_status"] = "failed"
                current["audit_error"] = redact(str(persistence_error))[:240]
                LOGGER.error("Investigation %s could not persist failure: %s", record["id"], type(persistence_error).__name__)
            self._checkpoint(current)
            return current

    def _finished(self, job_id, future):
        # Worker exceptions remain observable even if no HTTP client is polling.
        try:
            if not future.cancelled():
                future.result()
        except Exception as error:
            LOGGER.error("Investigation %s worker failed: %s", job_id, type(error).__name__)
            with self._lock:
                record = self._volatile.get(job_id, {"id": job_id})
                self._volatile[job_id] = {**record, "status": "failed", "phase": "failed",
                                        "error": redact(str(error))[:300], "persistence_status": "failed"}
        finally:
            self._slots.release()
            with self._lock:
                self._futures.pop(job_id, None)
                self._cancel.pop(job_id, None)
                self._identities.pop(job_id, None)
                # Durable results need no unbounded in-memory mirror.
                if len(self._volatile) > 200:
                    for key in list(self._volatile):
                        if key not in self._futures and key != job_id:
                            self._volatile.pop(key, None)
                            self._volatile_owners.pop(key, None)
                            if len(self._volatile) <= 150:
                                break

    def get(self, identity, investigation_id):
        _identifier(investigation_id, "investigation ID")
        with self._lock:
            volatile = self._volatile.get(investigation_id)
            owner = self._volatile_owners.get(investigation_id)
            cancel = self._cancel.get(investigation_id)
        try:
            record = self.journal.find(identity, investigation_id)
        except (OSError, sqlite3.Error):
            if volatile is None or owner != self.journal._owner(identity):
                raise
            return {**volatile, "persistence_status": "failed", "journal_unavailable": True,
                    "audit_error": "El almacenamiento local no responde; este resultado se conserva temporalmente en memoria."}
        if record is None:
            record = next((row for row in self._legacy(identity) if row["id"] == investigation_id), None)
            if record is None:
                raise KeyError("Investigation not found")
        if volatile is not None and volatile.get("persistence_status") == "failed":
            record = volatile
        if cancel is not None and cancel.is_set() and record["status"] in ACTIVE:
            record = {**record, "status": "cancelling", "cancel_requested": True}
        return record

    def list(self, identity, conversation_id=None):
        rows = self.journal.list(identity, conversation_id)
        # Preserve access to the user's pre-journal investigations without mixing
        # another person's prompts into the private conversational history.
        if conversation_id is None:
            known = {row["id"] for row in rows}
            for row in self._legacy(identity):
                if row["id"] not in known:
                    rows.append(row)
        return sorted(rows, key=lambda row: row.get("created_at", row.get("timestamp", "")), reverse=True)[:100]

    def _legacy(self, identity):
        if not hasattr(self.store, "list_investigations"):
            return []
        from .shared import source_descriptor
        current = source_descriptor()
        result = []
        for row in self.store.list_investigations(identity):
            if row.get("user_id") != identity["user_id"] or row.get("org_id") != identity["org_id"] or not row.get("id"):
                continue
            scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
            source = row.get("rawtree_source") or row.get("source")
            source = source if isinstance(source, dict) else {}
            source_id = source.get("id") or source.get("source_id") or scope.get("source_id")
            if source_id and source_id != current["id"]:
                continue
            if source.get("database") and source["database"] != current["database"]:
                continue
            endpoint = source.get("endpoint")
            if isinstance(endpoint, str) and endpoint.rstrip("/") != current["endpoint"]:
                continue
            verified = bool(source_id == current["id"] or (
                source.get("database") == current["database"] and endpoint == current["endpoint"]))
            result.append({**row, "conversation_id": row.get("conversation_id") or row["id"],
                "scope": scope or {"source_scope": "organization", "hours": 24},
                "read_only": True, "legacy_history": True, "context_eligible": False,
                "historical_scope_unverified": not verified})
        return result

    def _finish_cancelled(self, identity, record):
        record = {**record, "status": "cancelled", "phase": "cancelled", "cancel_requested": True}
        record.setdefault("progress_events", []).append({"at": _stamp(), "phase": "cancelled",
                                                        "message": "Cancelada antes de iniciar otra inferencia."})
        self.journal.save(identity, record)
        self.store.save_investigation(identity, record)
        self._checkpoint(record)
        return record

    def cancel(self, identity, investigation_id):
        record = self.get(identity, investigation_id)
        if record["status"] not in ACTIVE:
            return record
        with self._lock:
            event = self._cancel.get(investigation_id)
            future = self._futures.get(investigation_id)
        if event is not None:
            event.set()
        if future is not None and future.cancel():
            return self._finish_cancelled(identity, record)
        return self.journal.request_cancel(identity, investigation_id)

    def shutdown(self, wait=False):
        with self._lock:
            self._closed = True
            active = list(self._identities.items())
        for job_id, identity in active:
            try:
                self.cancel(identity, job_id)
            except Exception as error:
                LOGGER.error("Could not record shutdown cancellation %s: %s", job_id, type(error).__name__)
        self._executor.shutdown(wait=wait, cancel_futures=False)
