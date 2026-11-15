"""Explicit grants to one RawTree source; access identity is not event attribution.

The installation owner's initial workspace is authorized to read the configured
source. Other organizations remain isolated until that owner grants source read.
Changing the database creates a different source, never a broader wildcard.
"""
import hashlib
import os
import time
import urllib.parse


EVENT_TABLES = ("dev_platform_events", "dev_events_raw", "dev_logs", "dev_traces", "dev_metrics")
ALL_TABLES = (*EVENT_TABLES, "dev_investigations", "dev_artifacts_raw")


def source_descriptor():
    endpoint = os.getenv("RAWTREE_BASE_URL", "https://api.rawtree.com").rstrip("/")
    parsed = urllib.parse.urlsplit(endpoint)
    # Credentials and query parameters never belong in a connection identifier.
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("RAWTREE_BASE_URL cannot contain credentials or query parameters")
    if not parsed.hostname or (parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")
    )):
        raise ValueError("RawTree requires HTTPS (or an explicit loopback test server)")
    database = os.getenv("RAWTREE_DATABASE", "datathon_mathops")
    identifier = hashlib.sha256((endpoint + "\n" + database).encode()).hexdigest()[:24]
    return {
        "id": identifier,
        "name": os.getenv("DEVFLIGHT_SOURCE_NAME", "RawTree compartido"),
        "endpoint": endpoint,
        "database": database,
        "read_configured": bool(os.getenv("RAWTREE_READ_KEY")),
        "write_configured": bool(os.getenv("RAWTREE_API_KEY")),
    }


class SharedSource:
    def __init__(self, store):
        self.store = store
        self.descriptor = source_descriptor()
        with store.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS source_grants("
                "source_id TEXT,org_id TEXT,owner INTEGER DEFAULT 0,"
                "created REAL,PRIMARY KEY(source_id,org_id))"
            )
            # Persist the initial owner identity once. A newly created organization
            # is deliberately not granted source access just because it has an admin.
            owner = db.execute("SELECT value FROM metadata WHERE key='source_owner'").fetchone()
            if owner is None:
                token_path = store.home / "admin.token"
                root = store.authenticate(token_path.read_text().strip(), "login")
                import json
                root = {"org_id": root["org_id"], "user_id": root["user_id"]}
                db.execute("INSERT INTO metadata VALUES ('source_owner',?)", (json.dumps(root),))
            else:
                import json
                root = json.loads(owner[0])
            self.owner = root
            db.execute(
                "INSERT OR IGNORE INTO source_grants VALUES (?,?,1,?)",
                (self.descriptor["id"], root["org_id"], time.time()),
            )

    def can_read(self, identity):
        if identity.get("role") not in ("admin", "team_manager", "member", "viewer"):
            return False
        with self.store.db() as db:
            # Check current membership as well as the source grant on every call.
            row = db.execute(
                "SELECT 1 FROM source_grants g JOIN memberships m ON m.org_id=g.org_id "
                "WHERE g.source_id=? AND g.org_id=? AND m.user_id=?",
                (self.descriptor["id"], identity.get("org_id"), identity.get("user_id")),
            ).fetchone()
        return row is not None

    def is_owner(self, identity):
        return (
            identity.get("role") == "admin"
            and identity.get("org_id") == self.owner["org_id"]
            and identity.get("user_id") == self.owner["user_id"]
        )

    def grant(self, identity, org_id, enabled=True):
        if not self.is_owner(identity):
            raise PermissionError("Only the local source owner can grant shared-source access")
        if not isinstance(org_id, str):
            raise ValueError("An organization ID is required")
        if org_id == self.owner["org_id"] and not enabled:
            raise ValueError("The installation owner must retain source access")
        with self.store.db() as db:
            if not db.execute("SELECT 1 FROM organizations WHERE id=?", (org_id,)).fetchone():
                raise ValueError("Unknown organization")
            if enabled:
                db.execute(
                    "INSERT OR IGNORE INTO source_grants VALUES (?,?,0,?)",
                    (self.descriptor["id"], org_id, time.time()),
                )
            else:
                db.execute(
                    "DELETE FROM source_grants WHERE source_id=? AND org_id=?",
                    (self.descriptor["id"], org_id),
                )
        return {"org_id": org_id, "workspace_read": bool(enabled)}

    def scope(self, identity, requested=None):
        allowed = self.can_read(identity)
        requested = requested or ("workspace" if allowed else "organization")
        if requested not in ("workspace", "organization"):
            raise ValueError("Unknown source scope")
        if requested == "workspace" and not allowed:
            raise PermissionError("This organization has no grant to the shared RawTree source")
        return requested

    def info(self, identity):
        result = {
            **self.descriptor,
            "can_read_global": self.can_read(identity),
            "can_manage_source": self.is_owner(identity),
            "scope": self.scope(identity),
            "identity_policy": "Explicit emitter identifiers; shared API keys do not identify people.",
            "tables": [],
        }
        if self.is_owner(identity):
            with self.store.db() as db:
                result["grants"] = [
                    dict(row) for row in db.execute(
                        "SELECT g.org_id,o.name,g.owner FROM source_grants g "
                        "JOIN organizations o ON o.id=g.org_id WHERE g.source_id=?",
                        (self.descriptor["id"],),
                    )
                ]
        return result
