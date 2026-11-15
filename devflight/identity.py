"""Transactional identities and durable enterprise outbox; never imports legacy telemetry."""
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import uuid
import gzip

from .core import redact
from .normalization import normalize_event, normalize_otlp

ROLES = {"admin", "team_manager", "member", "viewer"}

def identifier():
    return uuid.uuid4().hex

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def safe_text(value, limit=128):
    return redact(value[:limit]) if isinstance(value, str) and value else None

class Store:
    def __init__(self, home=None):
        self.home = Path(home or os.getenv("DEVFLIGHT_PLATFORM_HOME", ".devflight/platform")).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "platform.sqlite3"
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS organizations(id TEXT PRIMARY KEY,name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS teams(id TEXT PRIMARY KEY,org_id TEXT NOT NULL,name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,org_id TEXT NOT NULL,name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memberships(org_id TEXT,user_id TEXT,role TEXT,team_id TEXT,PRIMARY KEY(org_id,user_id));
            CREATE TABLE IF NOT EXISTS credentials(hash TEXT PRIMARY KEY,org_id TEXT,user_id TEXT,purpose TEXT,expires REAL,revoked INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,org_id TEXT NOT NULL,table_name TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL,acked REAL,attempts INTEGER DEFAULT 0,last_error TEXT);
            CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(acked,created);
            CREATE INDEX IF NOT EXISTS outbox_org ON outbox(org_id,created);
            CREATE TABLE IF NOT EXISTS investigations(id TEXT PRIMARY KEY,org_id TEXT,user_id TEXT,team_id TEXT,created TEXT,payload TEXT);
            CREATE INDEX IF NOT EXISTS investigations_org ON investigations(org_id,created);
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
            ''')

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def bootstrap(self):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                return self.home / "admin.token"
            org, user, token = identifier(), identifier(), secrets.token_urlsafe(40)
            db.execute("INSERT INTO organizations VALUES (?,?)", (org, "My workspace"))
            db.execute("INSERT INTO users VALUES (?,?)", (user, "Local administrator"))
            db.execute("INSERT INTO memberships VALUES (?,?,?,NULL)", (org, user, "admin"))
            db.execute("INSERT INTO credentials(hash,org_id,user_id,purpose,expires) VALUES (?,?,?,?,NULL)", (digest(token),org,user,"login"))
            path = self.home / "admin.token"
            with path.open("x", encoding="ascii") as file:
                file.write(token)
                file.flush(); os.fsync(file.fileno())
            if os.name != "nt": path.chmod(0o600)
        return path

    def authenticate(self, token, purpose="session"):
        if not isinstance(token,str) or not 20 <= len(token) <= 256:
            raise PermissionError("Authentication required")
        with self.db() as db:
            row = db.execute('''SELECT c.org_id,c.user_id,m.role,m.team_id,u.name
                FROM credentials c JOIN memberships m ON m.org_id=c.org_id AND m.user_id=c.user_id
                JOIN users u ON u.id=c.user_id WHERE c.hash=? AND c.purpose=? AND c.revoked=0
                AND (c.expires IS NULL OR c.expires>?)''',(digest(token),purpose,time.time())).fetchone()
        if row is None: raise PermissionError("Invalid or expired credential")
        return dict(row)

    def issue(self, identity, purpose="session", user_id=None):
        user = user_id or identity["user_id"]
        if user != identity["user_id"] and identity["role"] != "admin":
            raise PermissionError("Admin role required")
        if purpose not in ("login","session","ingest"):
            raise ValueError("Invalid credential purpose")
        token = secrets.token_urlsafe(40)
        with self.db() as db:
            row = db.execute("SELECT role FROM memberships WHERE org_id=? AND user_id=?",(identity["org_id"],user)).fetchone()
            if not row: raise PermissionError("User is not a member of this organization")
            if purpose == "ingest" and row["role"] == "viewer": raise PermissionError("Viewer cannot ingest")
            db.execute("INSERT INTO credentials(hash,org_id,user_id,purpose,expires) VALUES (?,?,?,?,?)",
                       (digest(token),identity["org_id"],user,purpose,time.time()+28800 if purpose=="session" else None))
        return token

    def revoke(self, token):
        with self.db() as db: db.execute("UPDATE credentials SET revoked=1 WHERE hash=?",(digest(token),))

    def manage(self, identity, body):
        if identity["role"] != "admin": raise PermissionError("Admin role required")
        kind = body.get("kind")
        name = safe_text(body.get("name"))
        if kind == "ingest_key": return {"credential":self.issue(identity,"ingest",body.get("user_id"))}
        if kind == "revoke_key":
            with self.db() as db:
                cursor=db.execute("UPDATE credentials SET revoked=1 WHERE hash=? AND org_id=?",
                                  (body.get("credential_id"),identity["org_id"]))
                if not cursor.rowcount: raise PermissionError("Credential not found in this organization")
            return {"revoked":True}
        if kind == "retention":
            days=body.get("archive_after_days",0)
            if type(days) is not int or not 0<=days<=3650: raise ValueError("Invalid retention interval")
            with self.db() as db:
                db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",("retention:"+identity["org_id"],str(days)))
            return {"archive_after_days":days,"policy":"Archive confirmed payloads losslessly; never delete pending or historical files"}
        if kind == "membership":
            role=body.get("role");team=body.get("team_id");user=body.get("user_id")
            if role not in ROLES: raise ValueError("Invalid role")
            with self.db() as db:
                old=db.execute("SELECT role FROM memberships WHERE org_id=? AND user_id=?",(identity["org_id"],user)).fetchone()
                if not old: raise PermissionError("User not in this organization")
                if team and not db.execute("SELECT 1 FROM teams WHERE id=? AND org_id=?",(team,identity["org_id"])).fetchone():raise PermissionError("Team access denied")
                if old[0]=="admin" and role!="admin" and db.execute("SELECT count(*) FROM memberships WHERE org_id=? AND role='admin'",(identity["org_id"],)).fetchone()[0]<=1:
                    raise ValueError("Cannot remove the last organization administrator")
                db.execute("UPDATE memberships SET role=?,team_id=? WHERE org_id=? AND user_id=?",(role,team,identity["org_id"],user))
            return {"updated":True}
        if not name: raise ValueError("A name is required")
        with self.db() as db:
            value = identifier()
            if kind in ("team","project"):
                table = "teams" if kind=="team" else "projects"
                db.execute(f"INSERT INTO {table} VALUES (?,?,?)",(value,identity["org_id"],name))
            elif kind == "organization":
                db.execute("INSERT INTO organizations VALUES (?,?)",(value,name))
                db.execute("INSERT INTO memberships VALUES (?,?,?,NULL)",(value,identity["user_id"],"admin"))
            elif kind == "user":
                role = body.get("role","member")
                if role not in ROLES: raise ValueError("Invalid role")
                team = body.get("team_id")
                if team and not db.execute("SELECT 1 FROM teams WHERE id=? AND org_id=?",(team,identity["org_id"])).fetchone():
                    raise ValueError("Unknown team")
                db.execute("INSERT INTO users VALUES (?,?)",(value,name))
                db.execute("INSERT INTO memberships VALUES (?,?,?,?)",(identity["org_id"],value,role,team))
            else: raise ValueError("Unknown management operation")
        if kind == "user": return {"id":value,"credential":self.issue(identity,"login",value)}
        return {"id":value}

    def organizations(self, identity):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT o.id,o.name,m.role FROM organizations o JOIN memberships m ON m.org_id=o.id WHERE m.user_id=?",(identity["user_id"],))]

    def switch(self,identity,org_id):
        with self.db() as db:
            row = db.execute("SELECT role,team_id FROM memberships WHERE org_id=? AND user_id=?",(org_id,identity["user_id"])).fetchone()
        if not row: raise PermissionError("Organization access denied")
        return self.issue({**identity,**dict(row),"org_id":org_id})

    def settings(self, identity):
        with self.db() as db:
            org=identity["org_id"]
            users=[dict(r) for r in db.execute("SELECT u.id,u.name,m.role,m.team_id FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.org_id=?",(org,))]
            if identity["role"] == "member": users=[u for u in users if u["id"]==identity["user_id"]]
            if identity["role"] == "team_manager":
                users=[u for u in users if u["team_id"]==identity["team_id"]] if identity.get("team_id") else [u for u in users if u["id"]==identity["user_id"]]
            result={"users":users,"teams":[dict(r) for r in db.execute("SELECT id,name FROM teams WHERE org_id=?",(org,))],
                    "projects":[dict(r) for r in db.execute("SELECT id,name FROM projects WHERE org_id=?",(org,))],"mode":"RawTree","organizations":self.organizations(identity)}
            if identity["role"]=="admin":
                result["credentials"]=[dict(r) for r in db.execute("SELECT hash AS id,user_id,purpose,revoked,expires FROM credentials WHERE org_id=? AND purpose!='session'",(org,))]
        return result

    def normalize(self, identity, body):
        if identity["role"] == "viewer": raise PermissionError("Viewer cannot ingest")
        row=normalize_event(body)
        now=time.time()
        timestamp=row.get("timestamp")
        if timestamp is not None:
            parsed=dt.datetime.fromisoformat(str(timestamp).replace("Z","+00:00"))
            if parsed.tzinfo is None: raise ValueError("Timestamp must include timezone")
            now=parsed.timestamp()
        # Authentication and reported origin are separate. A shared ingest key
        # must never turn every originating developer into its credential owner.
        row.update(org_id=identity["org_id"], user_id=identity["user_id"],
                   ingest_user_id=identity["user_id"], ingest_org_id=identity["org_id"],
                   team_id=identity.get("team_id"),
                   timestamp=dt.datetime.fromtimestamp(now,dt.timezone.utc).isoformat(),
                   occurred_at_epoch=now)
        project=row.get("project_id")
        if project:
            with self.db() as db:
                if not db.execute("SELECT 1 FROM projects WHERE id=? AND org_id=?",(project,identity["org_id"])).fetchone():
                    raise PermissionError("Project access denied")
        row["project_id"]=project
        source_id=row.get("source_event_id")
        row["event_id"]=digest(identity["org_id"]+":"+identity["user_id"]+":"+source_id) if source_id else identifier()
        row["source_event_id"]=source_id or row["event_id"]
        row["canonical_id"]=row.get("canonical_id") or row["source_event_id"]
        return row

    def ingest(self, identity, body):
        row=self.normalize(identity,body)
        payload=json.dumps(row,allow_nan=False)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing=db.execute("SELECT payload FROM outbox WHERE id=?",(row["event_id"],)).fetchone()
            if existing:
                saved=json.loads(existing[0])
                return row if "archive_file" in saved else saved
            self.check_capacity(len(payload.encode("utf-8")))
            db.execute("INSERT OR IGNORE INTO outbox(id,org_id,table_name,payload,created) VALUES (?,?,?,?,?)",
                       (row["event_id"],identity["org_id"],"dev_platform_events",payload,time.time()))
        return row

    def check_capacity(self, incoming_bytes=0):
        limit=int(os.getenv("DEVFLIGHT_PLATFORM_MAX_BYTES","536870912"))
        if limit<0: raise ValueError("DEVFLIGHT_PLATFORM_MAX_BYTES must be nonnegative")
        size=sum(p.stat().st_size for pattern in ("platform.sqlite3*","archive-*.jsonl.gz") for p in self.home.glob(pattern))
        if limit and size+incoming_bytes>=limit:
            raise OSError("Enterprise storage limit reached; no event accepted. Archive externally or increase the configured limit.")

    def ingest_otlp(self, identity, signal, body):
        if identity["role"] == "viewer": raise PermissionError("Viewer cannot ingest")
        rows=[self.normalize(identity,event) for event in normalize_otlp(signal,body)]
        payloads=[(row,json.dumps(row,allow_nan=False)) for row in rows]
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            fresh=[]
            seen=set()
            for row,payload in payloads:
                if row["event_id"] not in seen and not db.execute("SELECT 1 FROM outbox WHERE id=?",(row["event_id"],)).fetchone():
                    fresh.append((row,payload))
                    seen.add(row["event_id"])
            if fresh: self.check_capacity(sum(len(payload.encode("utf-8")) for _,payload in fresh))
            db.executemany("INSERT OR IGNORE INTO outbox(id,org_id,table_name,payload,created) VALUES (?,?,?,?,?)",
                           [(row["event_id"],identity["org_id"],"dev_platform_events",payload,time.time()) for row,payload in fresh])
        return {"accepted":len(rows),"persisted":len(fresh),"duplicates":len(rows)-len(fresh)}

    def save_investigation(self, identity, record):
        return self.save_analyst_result(identity, record)

    def save_analyst_result(self, identity, record, usage_event=None):
        """Atomically persist a terminal investigation, its audit and model usage.

        Running checkpoints belong in analyst_jobs; terminal audit payloads are
        immutable outbox events so a network retry always has identical bytes.
        """
        record=redact(dict(record))
        record.setdefault("id",identifier()); record.setdefault("created_at",stamp())
        record.update(org_id=identity["org_id"],user_id=identity["user_id"],team_id=identity.get("team_id"))
        payload=json.dumps(record,allow_nan=False)
        usage=self.normalize(identity,usage_event) if usage_event is not None else None
        usage_payload=json.dumps(usage,allow_nan=False) if usage is not None else None
        audit={**record,"event_id":record["id"],"timestamp":record["created_at"],"event_type":"analyst.investigation"}
        audit_payload=json.dumps(audit,allow_nan=False)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check_capacity(len(payload.encode("utf-8"))+len(audit_payload.encode("utf-8"))+len((usage_payload or "").encode("utf-8")))
            db.execute("INSERT OR REPLACE INTO investigations VALUES (?,?,?,?,?,?)",(record["id"],identity["org_id"],identity["user_id"],identity.get("team_id"),record["created_at"],payload))
            db.execute("INSERT OR IGNORE INTO outbox(id,org_id,table_name,payload,created) VALUES (?,?,?,?,?)",(record["id"],identity["org_id"],"dev_investigations",audit_payload,time.time()))
            if usage is not None:
                db.execute("INSERT OR IGNORE INTO outbox(id,org_id,table_name,payload,created) VALUES (?,?,?,?,?)",(usage["event_id"],identity["org_id"],"dev_platform_events",usage_payload,time.time()))
        return record

    def list_investigations(self,identity):
        where="org_id=?"; args=[identity["org_id"]]
        if identity["role"]=="member": where+=" AND user_id=?"; args.append(identity["user_id"])
        if identity["role"]=="team_manager":
            if identity.get("team_id"): where+=" AND team_id=?"; args.append(identity["team_id"])
            else: where+=" AND user_id=?"; args.append(identity["user_id"])
        with self.db() as db: return [json.loads(r[0]) for r in db.execute("SELECT payload FROM investigations WHERE "+where+" ORDER BY created DESC LIMIT 100",args)]

    def status(self, identity=None):
        where=" WHERE org_id=?" if identity else ""
        args=(identity["org_id"],) if identity else ()
        with self.db() as db:
            row=dict(db.execute("SELECT count(*) AS total,sum(CASE WHEN acked IS NULL THEN 1 ELSE 0 END) AS pending,max(acked) AS last_sync,sum(attempts) AS retries,min(CASE WHEN acked IS NULL THEN created END) AS oldest_pending_epoch FROM outbox"+where,args).fetchone())
            error=db.execute("SELECT last_error FROM outbox WHERE last_error IS NOT NULL"+(" AND org_id=?" if identity else "")+" ORDER BY created DESC LIMIT 1",args).fetchone()
            state=db.execute("SELECT value FROM metadata WHERE key=?",("uploader:"+identity["org_id"] if identity else "uploader",)).fetchone()
            state=json.loads(state[0]) if state else {}
        oldest=row.pop("oldest_pending_epoch")
        return {**row,"pending":row["pending"] or 0,"retries":row["retries"] or 0,
                "last_error":error[0] if error else state.get("last_error"),
                "last_attempt":state.get("last_attempt"),"last_success":state.get("last_success"),
                "offline":os.getenv("DEVFLIGHT_OFFLINE")=="1",
                "oldest_pending":dt.datetime.fromtimestamp(oldest,dt.timezone.utc).isoformat() if oldest else None,
                "age_seconds":max(0,time.time()-oldest) if oldest else 0,
                "disk_bytes":None if identity else sum(p.stat().st_size for p in self.home.glob("platform.sqlite3*"))}

    def _upload_state(self, db, organizations, **updates):
        for key in ["uploader", *("uploader:"+org for org in sorted(set(organizations)))]:
            saved=db.execute("SELECT value FROM metadata WHERE key=?",(key,)).fetchone()
            state=json.loads(saved[0]) if saved else {}
            state.update(updates)
            db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",(key,json.dumps(state,allow_nan=False)))

    def archive_confirmed(self):
        """Opt-in payload compaction. Complete acknowledged envelopes remain in gzip archives."""
        from .core import file_lock
        with file_lock(self.home/"archive.lock"):
            with self.db() as db:
                policies=db.execute("SELECT key,value FROM metadata WHERE key LIKE 'retention:%'").fetchall()
                for policy in policies:
                    days=int(policy["value"])
                    if not days: continue
                    org=policy["key"].split(":",1)[1]
                    rows=db.execute("SELECT * FROM outbox WHERE org_id=? AND acked IS NOT NULL AND acked<? AND payload NOT LIKE '{\"archive_file\":%' LIMIT 200",(org,time.time()-days*86400)).fetchall()
                    if not rows: continue
                    archive=self.home/("archive-"+identifier()+".jsonl.gz")
                    raw="".join(json.dumps(dict(row),ensure_ascii=False)+"\n" for row in rows).encode()
                    with archive.open("xb") as file:
                        file.write(gzip.compress(raw,mtime=0));file.flush();os.fsync(file.fileno())
                    db.executemany("UPDATE outbox SET payload=? WHERE id=? AND acked IS NOT NULL",[(json.dumps({"archive_file":archive.name,"event_id":row["id"]}),row["id"]) for row in rows])

    def sync_once(self, client=None):
        from .rawtree import RawTree
        from .core import file_lock
        with file_lock(self.home/"enterprise-sync.lock"):
            with self.db() as db:
                saved=db.execute("SELECT value FROM metadata WHERE key='outbox_manifest'").fetchone()
                if saved:
                    manifest=json.loads(saved[0])
                    pending=[db.execute("SELECT id,org_id,table_name,payload FROM outbox WHERE id=?",(i,)).fetchone() for i in manifest]
                    if any(r is None for r in pending): raise ValueError("Outbox manifest references missing telemetry")
                else:
                    pending=db.execute("SELECT id,org_id,table_name,payload FROM outbox WHERE acked IS NULL ORDER BY created,id LIMIT 100").fetchall()
                    if pending:
                        db.execute("INSERT OR REPLACE INTO metadata VALUES ('outbox_manifest',?)",(json.dumps([r["id"] for r in pending]),))
            if not pending: return 0
            if os.getenv("DEVFLIGHT_OFFLINE")=="1":
                return 0
            organizations={row["org_id"] for row in pending}
            with self.db() as db:
                self._upload_state(db,organizations,last_attempt=time.time())
            try:
                client=client or RawTree()
            except Exception as exc:
                message=redact(str(exc))[:500]
                with self.db() as db:
                    db.executemany("UPDATE outbox SET attempts=attempts+1,last_error=? WHERE id=?",[(message,row["id"]) for row in pending])
                    self._upload_state(db,organizations,last_error=message)
                raise
            for table in sorted({r["table_name"] for r in pending}):
                batch=[r for r in pending if r["table_name"]==table]
                token=digest(table+":"+":".join(r["id"] for r in batch))
                try:
                    rows=[json.loads(r["payload"]) for r in batch]
                    client.insert(table,rows,token)
                except Exception as exc:
                    message=redact(str(exc))[:500]
                    with self.db() as db:
                        db.executemany("UPDATE outbox SET attempts=attempts+1,last_error=? WHERE id=?",[(message,r["id"]) for r in batch])
                        self._upload_state(db,{r["org_id"] for r in batch},last_error=message)
                    raise
                with self.db() as db:
                    db.executemany("UPDATE outbox SET acked=?,last_error=NULL WHERE id=?",[(time.time(),r["id"]) for r in batch])
                    self._upload_state(db,{r["org_id"] for r in batch},last_error=None,last_success=time.time())
                    remaining=[r["id"] for r in pending if r["table_name"]>table]
                    if remaining: db.execute("INSERT OR REPLACE INTO metadata VALUES ('outbox_manifest',?)",(json.dumps(remaining),))
                    else: db.execute("DELETE FROM metadata WHERE key='outbox_manifest'")
            return len(pending)
