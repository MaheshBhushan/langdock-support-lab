from collections import Counter
from .runbooks import citation

CATEGORIES = {"UPSTREAM_AUTH": "auth", "UPSTREAM_PERMISSION": "permission", "UPSTREAM_THROTTLED": "throttle", "UPSTREAM_TIMEOUT": "timeout"}
BOOKS = {"auth": "RB-AUTH", "permission": "RB-PERMISSION", "throttle": "RB-THROTTLE", "timeout": "RB-TIMEOUT", "success": "RB-SUCCESS"}


def checks(incident):
    return {e["payload"]["check_id"]: e["payload"]["result"] for e in incident["events"] if e["type"] == "check"}


def applicable_sharing(operation):
    return {"required_scope_confirmed", "agent_shared", "subagents_shared"} if operation == "agent_completion" else {"required_scope_confirmed", "knowledge_viewer_shared"}


def recovery(runs):
    failures = [r for r in runs if r["status"] in ("failed", "interrupted")]
    latest = max((r["created_at"] for r in failures), default="")
    return [r for r in runs if r["status"] == "succeeded" and r["observation"]["code"] == "OK" and (r["observation"]["result_count"] or 0) > 0 and r["created_at"] > latest]


def compute(incident, runs, books):
    failures = [r for r in runs if r["status"] in ("failed", "interrupted")]
    latest = max(enumerate(failures), key=lambda pair: (pair[1]["created_at"], pair[0]))[1]
    code = latest["observation"]["code"]
    category = CATEGORIES.get(code)
    recovered = recovery(runs)
    performed = checks(incident)
    needs_admin = any(performed.get(k) in ("fail", "unknown") for k in applicable_sharing(latest["operation"]))
    repeated = Counter(r["observation"]["code"] for r in failures)[code] >= 2
    level, action = "L1", {"throttle": "wait_then_manual_retry", "timeout": "inspect_deadline"}.get(category, "check_configuration")
    if recovered:
        action, category = "verify_recovery", "success"
    elif category is None or repeated or needs_admin:
        level, action = "L2", "escalate"
    book = books.get(BOOKS.get(category))
    citations = [citation(book, "l2")] if book else []
    limitations = ["Synthetic lab exercise; production impact not assessed.", "Observations do not prove root cause. Checks are operator assertions."]
    if not book:
        limitations.append("No eligible reviewed guidance available")
        if not recovered:
            level, action = "L2", "escalate"
    suggested = {"auth": ["backend_key_present", "required_scope_confirmed"], "permission": sorted(applicable_sharing(latest["operation"])), "throttle": ["retry_window_observed"], "timeout": ["deadline_checked"]}.get(category, [])
    facts = []
    for run in runs:
        obs = run["observation"]
        status = obs["upstream_status"]
        evidence = f"HTTP {status} was observed" if status is not None else "No HTTP status was observed"
        facts.append(f'Run {run["id"]}: {evidence}; observation {obs["code"]}.')
        if obs["retry_after_seconds"] is not None:
            facts.append(f'Run {run["id"]}: bounded retry hint {obs["retry_after_seconds"]} seconds.')
    hypotheses = ["If scope or resource sharing is missing, an administrator may need to change configuration."] if code in ("UPSTREAM_AUTH", "UPSTREAM_PERMISSION") else ["If the failure persists, further evidence is required before choosing a cause."]
    return {"level": level, "observed_codes": list(dict.fromkeys(r["observation"]["code"] for r in runs)), "facts": facts,
            "hypotheses": hypotheses, "suggested_checks": suggested, "recommended_action": action, "citations": citations,
            "evidence_run_ids": incident["run_ids"], "limitations": limitations}
