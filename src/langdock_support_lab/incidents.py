import json
from .errors import LabError
from .models import EventRecord, TriageRecord
from .runs import stamp
from .safety import free_text
from .triage import compute, checks, applicable_sharing, recovery


def derived_title(run):
    return f'Synthetic {run["operation"]} {run["observation"]["code"]}' if run["mode"] == "offline" else f'Live probe {run["operation"]} {run["observation"]["code"]}'


class Incidents:
    def __init__(self, storage, clock, uuid, secrets=()):
        self.storage, self.clock, self.uuid, self.secrets = storage, clock, uuid, secrets

    def event(self, conn, incident_id, sequence, role, kind, payload, now):
        event_id = str(self.uuid())
        EventRecord.model_validate({"id": event_id, "sequence": sequence, "created_at": now, "actor_role": role, "type": kind, "payload": payload})
        conn.execute("INSERT INTO incident_events VALUES (?,?,?,?,?,?,?)", (event_id, incident_id, sequence, now, role, kind, json.dumps(payload, allow_nan=False)))

    def create(self, request, role):
        if request.title is not None:
            free_text(request.title, self.secrets)
        with self.storage.connection(True) as conn:
            run = self.storage.run(request.run_id, conn)
            if run["status"] not in ("failed", "interrupted"):
                raise LabError("INVALID_TRANSITION", 409)
            if conn.execute("SELECT 1 FROM incidents WHERE initial_run_id=?", (run["id"],)).fetchone():
                raise LabError("INCIDENT_EXISTS", 409)
            now, incident_id = stamp(self.clock), str(self.uuid())
            conn.execute("INSERT INTO incidents VALUES (?,?,?,?,?,?,?,NULL)", (incident_id, now, now, request.title or derived_title(run), "open", 1, run["id"]))
            conn.execute("INSERT INTO incident_runs VALUES (?,?,?)", (incident_id, run["id"], now))
            self.event(conn, incident_id, 1, role, "created", {"run_id": run["id"]}, now)
            return self.storage.incident(incident_id, conn)

    def update(self, incident_id, request, role, books=None):
        with self.storage.connection(True) as conn:
            item = self.storage.incident(incident_id, conn)
            if item["version"] != request.expected_version:
                raise LabError("VERSION_CONFLICT", 409)
            kind = getattr(request, "type", "triage")
            runs = [self.storage.run(run_id, conn) for run_id in item["run_ids"]]
            initial = runs[0]
            payload = request.model_dump(exclude={"expected_version", "type"})
            now = stamp(self.clock)
            state, triage = item["state"], item["triage"]
            if state == "resolved" and kind not in ("attach_run", "reopen"):
                raise LabError("INVALID_TRANSITION", 409)
            if kind == "check":
                if (request.check_id in ("agent_shared", "subagents_shared") and initial["operation"] != "agent_completion") or (request.check_id == "knowledge_viewer_shared" and initial["operation"] != "knowledge_search"):
                    raise LabError("INVALID_INPUT")
                triage = None
            elif kind == "attach_run":
                run = self.storage.run(request.run_id, conn)
                if run["id"] in item["run_ids"]:
                    raise LabError("RUN_ALREADY_ATTACHED", 409)
                if run["status"] == "running" or run["mode"] != initial["mode"] or run["operation"] != initial["operation"]:
                    raise LabError("INVALID_INPUT")
                conn.execute("INSERT INTO incident_runs VALUES (?,?,?)", (incident_id, run["id"], now))
                triage = None
            elif kind == "triage":
                triage = TriageRecord.model_validate(compute(item, runs, books or {})).model_dump()
                state = "triaged" if state == "open" else state
                payload = {"triage": triage}
            elif kind == "escalate":
                performed = checks(item)
                if state != "triaged" or triage is None or (not performed and not any(c in ("UPSTREAM_PROTOCOL", "UPSTREAM_NETWORK", "RUN_INTERRUPTED") for c in triage["observed_codes"])):
                    raise LabError("INVALID_TRANSITION", 409)
                if request.reason == "admin_access_required" and not any(performed.get(k) in ("fail", "unknown") for k in applicable_sharing(initial["operation"])):
                    raise LabError("INVALID_TRANSITION", 409)
                if request.reason == "repeated_failure":
                    codes = [r["observation"]["code"] for r in runs if r["status"] == "failed"]
                    if not any(codes.count(c) >= 2 for c in codes):
                        raise LabError("INVALID_TRANSITION", 409)
                state = "escalated"
            elif kind == "resolve":
                eligible = recovery(runs)
                resolution = "synthetic_recovery_verified" if initial["mode"] == "offline" else "live_recovery_observed"
                if state not in ("triaged", "escalated") or triage is None or request.resolution != resolution or request.verification_run_id not in [r["id"] for r in eligible]:
                    raise LabError("INVALID_TRANSITION", 409)
                state = "resolved"
            elif kind == "reopen":
                resolved_at = next((e["created_at"] for e in reversed(item["events"]) if e["type"] == "resolve"), None)
                if state != "resolved" or not resolved_at or not any(r["status"] == "failed" and r["created_at"] > resolved_at for r in runs):
                    raise LabError("INVALID_TRANSITION", 409)
                state, triage = "open", None
            conn.execute("UPDATE incidents SET state=?,version=version+1,updated_at=?,triage_json=? WHERE id=? AND version=?", (state, now, json.dumps(triage, allow_nan=False) if triage else None, incident_id, request.expected_version))
            self.event(conn, incident_id, item["version"] + 1, role, kind, payload, now)
            return self.storage.incident(incident_id, conn)
