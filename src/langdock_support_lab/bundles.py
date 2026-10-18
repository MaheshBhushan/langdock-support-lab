import json
import os
from pathlib import Path
import re
import tempfile
from .errors import LabError
from .incidents import derived_title

LIMITATIONS = ["Observations do not prove root cause.", "Guidance has synthetic-lab-review provenance; no provider endorsement.", "Raw payloads, credentials, provider links, custom titles and configuration are omitted."]


def bundle(storage, incident_id):
    with storage.connection() as conn:
        conn.execute("BEGIN")
        item = storage.incident(incident_id, conn)
        runs = [storage.run(run_id, conn) for run_id in item["run_ids"]]
        initial = runs[0]
        triage = item["triage"]
        guidance = [{**c, "review_status_at_triage": "eligible"} for c in triage["citations"]] if triage else []
        return {"schema_version": 1, "bundle_kind": "synthetic-escalation" if initial["mode"] == "offline" else "live-probe-escalation",
                "incident": {k: item[k] for k in ("id", "state", "version", "created_at", "updated_at")} | {"title": derived_title(initial), "impact": "Synthetic lab exercise; production impact not assessed."},
                "evidence": runs, "timeline": item["events"], "triage": triage,
                "reproduction": [f'lab run --scenario {r["scenario_id"]} --operation {r["operation"]}' if r["mode"] == "offline" else f'lab --role admin live probe --operation {r["operation"]} --probe {r["probe_id"]} --acknowledge-live-request' for r in runs],
                "reviewed_guidance": guidance, "limitations": ["Synthetic fixture evidence; no provider request occurred." if initial["mode"] == "offline" else "Live probe evidence; no production impact assessed.", *LIMITATIONS],
                "redaction": {"policy_version": 1, "raw_payloads_included": False, "custom_title_omitted": item["title"] != derived_title(initial)}}


def escape(text):
    return re.sub(r"([\\`*_{}\[\]()#+.!|<>-])", r"\\\1", str(text))


def markdown(data):
    item = data["incident"]
    lines = [f'# Incident {item["id"]} v{item["version"]}', "", escape(data["bundle_kind"]), "", escape(item["title"]), "", escape(item["impact"]), "", "## Observations", ""]
    for run in data["evidence"]:
        obs = run["observation"]
        lines += ["- " + escape(f'{run["id"]}: {run["provenance"]}; {obs["code"]}; HTTP {obs["upstream_status"]}; {obs["duration_ms"]} ms.'),
                  "  " + escape(f'Results: {obs["result_count"]}; retry hint: {obs["retry_after_seconds"]} seconds; attempts: {obs["attempt_count"]}.')]
    lines += ["", "## Checks and history", ""]
    for event in data["timeline"]:
        payload = event["payload"]
        if event["type"] == "triage":
            detail = payload["triage"]["level"] + "; " + payload["triage"]["recommended_action"]
        else:
            detail = "; ".join(f"{key}: {value}" for key, value in sorted(payload.items()))
        lines.append("- " + escape(f'{event["sequence"]}. {event["created_at"]}; {event["actor_role"]}; {event["type"]}; {detail}'))
    lines += ["", "## Hypotheses and next actions", ""]
    if data["triage"]:
        lines.extend("- " + escape(value) for value in data["triage"]["hypotheses"])
        lines.append("- " + escape(data["triage"]["recommended_action"]))
        lines.extend("- " + escape(value) for value in data["triage"]["limitations"])
    else:
        lines.append("Triage is absent.")
    lines += ["", "## Citations", ""]
    for cite in data["reviewed_guidance"]:
        lines += [escape(cite["id"] + " " + cite["title"]), "", escape("SHA-256: " + cite["sha256"]), "",
                  escape(f'{cite["review_kind"]}; reviewed {cite["reviewed_at"]}; due {cite["review_due_at"]}; eligible at triage.'), "", escape(cite["excerpt"]), ""]
    lines += ["## Reproduction", ""]
    for command in data["reproduction"]:
        lines += ["```sh", command, "```", ""]
    lines += ["## Limits", "", *["- " + escape(value) for value in data["limitations"]], ""]
    return "\n".join(lines).encode()


def write_pair(out, json_bytes, markdown_bytes):
    data = json.loads(json_bytes)
    item = data["incident"]
    if not markdown_bytes.startswith(f'# Incident {item["id"]} v{item["version"]}\n'.encode()):
        raise LabError("VERSION_CONFLICT", 409)
    out = Path(out).absolute()
    if any(p.is_symlink() for p in (out, *out.parents)):
        raise LabError("INVALID_INPUT")
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = out / f'incident-{item["id"]}-v{item["version"]}'
    if target.exists() or target.is_symlink():
        raise LabError("VERSION_CONFLICT", 409)
    with tempfile.TemporaryDirectory(dir=out, prefix=".bundle-") as temp:
        for name, content in (("incident.json", json_bytes), ("incident.md", markdown_bytes)):
            with (Path(temp) / name).open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        # renameat2 RENAME_NOREPLACE prevents replacing a concurrently published directory.
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        result = libc.renameat2(-100, os.fsencode(temp), -100, os.fsencode(target), 1)
        if result != 0:
            raise LabError("VERSION_CONFLICT", 409)
        # TemporaryDirectory tolerates a directory moved to its final name.
    return {"directory": str(target)}
