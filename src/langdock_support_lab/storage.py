from contextlib import contextmanager
import json
import os
import sqlite3
from .errors import LabError
from .models import RunRecord, IncidentRecord
from .adapters.base import observation

SCHEMA = """
CREATE TABLE runs (
 id TEXT PRIMARY KEY, created_at TEXT NOT NULL, finished_at TEXT,
 mode TEXT NOT NULL CHECK(mode IN ('offline','live')),
 operation TEXT NOT NULL CHECK(operation IN ('agent_completion','knowledge_search')),
 scenario_id TEXT, probe_id TEXT NOT NULL CHECK(probe_id IN ('health-text','runbook-auth')),
 status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed','interrupted')), observation_json TEXT);
CREATE TABLE incidents (
 id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, title TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('open','triaged','escalated','resolved')), version INTEGER NOT NULL CHECK(version>=1),
 initial_run_id TEXT NOT NULL UNIQUE REFERENCES runs(id), triage_json TEXT);
CREATE TABLE incident_runs (
 incident_id TEXT NOT NULL REFERENCES incidents(id), run_id TEXT NOT NULL REFERENCES runs(id), attached_at TEXT NOT NULL,
 PRIMARY KEY(incident_id,run_id));
CREATE TABLE incident_events (
 id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id), sequence INTEGER NOT NULL,
 created_at TEXT NOT NULL, actor_role TEXT NOT NULL CHECK(actor_role IN ('reader','operator','admin')),
 type TEXT NOT NULL CHECK(type IN ('created','check','attach_run','triage','escalate','resolve','reopen')),
 payload_json TEXT NOT NULL, UNIQUE(incident_id,sequence));
PRAGMA user_version=1;
"""


class Storage:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connection(self, write=False):
        if self.path.is_symlink():
            raise LabError("STORAGE_UNAVAILABLE", 503)
        conn = None
        try:
            conn = sqlite3.connect(self.path, timeout=2)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=2000")
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except sqlite3.OperationalError as exc:
            if conn:
                conn.rollback()
            code = "STORAGE_BUSY" if getattr(exc, "sqlite_errorcode", None) in (5, 6) else "STORAGE_UNAVAILABLE"
            raise LabError(code, 503) from None
        except sqlite3.DatabaseError:
            if conn:
                conn.rollback()
            raise LabError("STORAGE_UNAVAILABLE", 503) from None
        finally:
            if conn:
                conn.close()

    def initialize(self):
        with self.connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise LabError("STORAGE_UNAVAILABLE", 503)
            conn.execute("PRAGMA journal_mode=WAL")
            if version == 0:
                conn.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")
        os.chmod(self.path, 0o600)

    def recover(self, timestamp):
        with self.connection(True) as conn:
            conn.execute("UPDATE runs SET status='interrupted', finished_at=?, observation_json=? WHERE status='running'",
                         (timestamp, json.dumps(observation("RUN_INTERRUPTED"))))

    def insert_run(self, run):
        run = RunRecord.model_validate(run).model_dump()
        with self.connection(True) as conn:
            conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)", tuple(run[k] for k in ("id", "created_at", "finished_at", "mode", "operation", "scenario_id", "probe_id", "status")) + (None,))

    def finalize_run(self, run):
        run = RunRecord.model_validate(run).model_dump()
        with self.connection(True) as conn:
            conn.execute("UPDATE runs SET finished_at=?,status=?,observation_json=? WHERE id=?", (run["finished_at"], run["status"], json.dumps(run["observation"], allow_nan=False), run["id"]))

    def run(self, run_id, conn=None):
        if conn is None:
            with self.connection() as conn:
                return self.run(run_id, conn)
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise LabError("NOT_FOUND", 404)
        item = dict(row)
        encoded_observation = item.pop("observation_json")
        item["observation"] = json.loads(encoded_observation) if encoded_observation else None
        item["provenance"] = "synthetic" if item["mode"] == "offline" else "live"
        return RunRecord.model_validate(item).model_dump()

    def incident(self, incident_id, conn=None):
        if conn is None:
            with self.connection() as conn:
                conn.execute("BEGIN")
                return self.incident(incident_id, conn)
        row = conn.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None:
            raise LabError("NOT_FOUND", 404)
        item = dict(row)
        encoded_triage = item.pop("triage_json")
        item["triage"] = json.loads(encoded_triage) if encoded_triage else None
        events = []
        for event in conn.execute("SELECT * FROM incident_events WHERE incident_id=? ORDER BY sequence", (incident_id,)):
            entry = dict(event)
            entry.pop("incident_id")
            entry["payload"] = json.loads(entry.pop("payload_json"))
            events.append(entry)
        item["events"] = events
        item["run_ids"] = [e["payload"]["run_id"] for e in events if e["type"] in ("created", "attach_run")]
        return IncidentRecord.model_validate(item).model_dump()

    def listing(self, kind, limit, offset):
        table = "runs" if kind == "runs" else "incidents"
        with self.connection() as conn:
            conn.execute("BEGIN")
            total = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            ids = conn.execute(f"SELECT id FROM {table} ORDER BY created_at,id LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            getter = self.run if table == "runs" else self.incident
            return {"items": [getter(row[0], conn) for row in ids], "total": total, "limit": limit, "offset": offset}
