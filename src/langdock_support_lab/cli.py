import argparse
import json
import logging
import sys
import httpx
from .config import Config, ConfigError, initialize, root_path
from .errors import LabError
from .runbooks import IDS, CHECKS, snapshot, review
from .runs import utc_now
from .bundles import write_pair

OPS = ("agent_completion", "knowledge_search")


def parser():
    p = argparse.ArgumentParser(prog="lab", description="Synthetic TARGET support lab; live verification is separate.")
    p.add_argument("--root")
    p.add_argument("--credentials-file")
    p.add_argument("--role", choices=("reader", "operator", "admin"), default="operator")
    p.add_argument("--json", action="store_true")
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("serve")
    scenarios = commands.add_parser("scenarios").add_subparsers(dest="action", required=True)
    scenarios.add_parser("list")
    run = commands.add_parser("run")
    run.add_argument("--scenario", required=True)
    run.add_argument("--operation", choices=OPS, required=True)
    runs = commands.add_parser("runs").add_subparsers(dest="action", required=True)
    runs.add_parser("list")
    runs.add_parser("show").add_argument("id")
    inc = commands.add_parser("incidents").add_subparsers(dest="action", required=True)
    create = inc.add_parser("create")
    create.add_argument("--run", required=True)
    inc.add_parser("show").add_argument("id")
    for action in ("check", "attach", "triage", "escalate", "resolve", "reopen", "export"):
        sub = inc.add_parser(action)
        sub.add_argument("id")
        if action != "export":
            sub.add_argument("--version", required=True, type=int)
        if action in ("attach", "resolve"):
            sub.add_argument("--run", required=True)
        if action == "check":
            sub.add_argument("--check", required=True)
            sub.add_argument("--result", choices=("pass", "fail", "unknown"), required=True)
        if action == "escalate":
            sub.add_argument("--reason", required=True)
        if action == "resolve":
            sub.add_argument("--resolution", required=True)
        if action == "export":
            sub.add_argument("--out", required=True)
    ask = commands.add_parser("support").add_subparsers(dest="action", required=True).add_parser("ask")
    ask.add_argument("--question", required=True)
    books = commands.add_parser("runbooks").add_subparsers(dest="action", required=True)
    books.add_parser("check")
    rev = books.add_parser("review")
    rev.add_argument("id", choices=IDS)
    rev.add_argument("--reviewer", required=True)
    rev.add_argument("--days", type=int, default=180)
    for flag in CHECKS:
        rev.add_argument("--" + flag.replace("_", "-"), action="store_true", required=True)
    smoke = commands.add_parser("smoke")
    smoke.add_argument("--json", action="store_true")
    smoke.add_argument("--export", action="store_true")
    live = commands.add_parser("live").add_subparsers(dest="action", required=True)
    for action in ("probe", "verify"):
        sub = live.add_parser(action)
        sub.add_argument("--acknowledge-live-request", action="store_true", required=True)
        if action == "probe":
            sub.add_argument("--operation", choices=OPS, required=True)
            sub.add_argument("--probe", required=True)
    return p


class API:
    def __init__(self, config, role):
        self.config = config
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{config.port}", headers={"Authorization": "Bearer " + config.tokens[role]}, trust_env=False, follow_redirects=False, timeout=30)

    def request(self, method, path, data=None, expected=None, raw=False):
        response = self.client.request(method, path, json=data) if data is not None else self.client.request(method, path)
        if expected is not None:
            if response.status_code != expected:
                raise AssertionError("Unexpected local response status")
        elif response.status_code >= 300:
            code = {401: 4, 403: 4, 409: 6, 503: 5, 500: 5}.get(response.status_code, 2)
            print(json.dumps(response.json()), file=sys.stderr)
            raise SystemExit(code)
        return response.content if raw else response.json()

    def close(self):
        self.client.close()


def live_pass(runs):
    return len(runs) == 2 and {r["operation"] for r in runs} == set(OPS) and all(r["provenance"] == "live" and r["status"] == "succeeded" and r["observation"]["response_shape_valid"] is True and r["observation"]["probe_expectation_met"] is True for r in runs)


def smoke(api, export=False):
    if api.config.mode != "offline":
        raise LabError("MODE_MISMATCH", 409)
    steps, created = [], []

    def passed(name):
        steps.append({"gate": name, "status": "passed"})
        print(name + ": passed", file=sys.stderr)

    with httpx.Client(base_url=f"http://127.0.0.1:{api.config.port}", trust_env=False) as public:
        assert public.get("/healthz").json() == {"status": "ok"}
        assert public.get("/v1/scenarios").status_code == 401
    reader = API(api.config, "reader")
    try:
        reader.request("POST", "/v1/runs", {"mode": "offline", "operation": OPS[0], "scenario_id": "success"}, expected=403)
    finally:
        reader.close()
    passed("access_control")
    catalog = api.request("GET", "/v1/scenarios")["items"]
    failures = []
    for row in catalog:
        for op in row["operations"]:
            run = api.request("POST", "/v1/runs", {"mode": "offline", "operation": op, "scenario_id": row["id"]})
            created.append(run["id"])
            obs = run["observation"]
            assert obs["code"] == row["expected_code"] and obs["attempt_count"] == 1
            assert run["status"] == ("succeeded" if row["id"] in ("success", "knowledge-empty") else "failed")
            assert obs["retry_after_seconds"] == (7 if row["id"] == "throttled" else None)
            assert obs["upstream_status"] == {"success": 200, "knowledge-empty": 200, "auth-missing": 401, "auth-invalid": 401, "permission-denied": 403, "throttled": 429, "timeout": None}[row["id"]]
            assert obs["result_count"] == (1 if row["id"] == "success" else 0 if row["id"] == "knowledge-empty" else None)
            if row["id"] == "permission-denied" and op == OPS[0]:
                failures.append(run)
    assert len(created) == 13
    passed("thirteen_scenarios")
    item = api.request("POST", "/v1/incidents", {"run_id": failures[0]["id"]})
    incident_id = item["id"]

    def event(kind, **values):
        nonlocal item
        previous = item["version"]
        item = api.request("POST", f"/v1/incidents/{incident_id}/events", {"expected_version": previous, "type": kind, **values})
        assert item["version"] == previous + 1

    def triage():
        nonlocal item
        previous = item["version"]
        item = api.request("POST", f"/v1/incidents/{incident_id}/triage", {"expected_version": previous})
        assert item["version"] == previous + 1

    event("check", check_id="agent_shared", result="unknown")
    triage()
    assert item["triage"]["level"] == "L2" and item["triage"]["citations"][0]["runbook_id"] == "RB-PERMISSION"
    event("escalate", reason="admin_access_required")
    assert item["state"] == "escalated"
    passed("escalation")
    run = api.request("POST", "/v1/runs", {"mode": "offline", "operation": OPS[0], "scenario_id": "success"})
    created.append(run["id"])
    event("attach_run", run_id=run["id"])
    triage()
    assert item["triage"]["recommended_action"] == "verify_recovery"
    event("resolve", verification_run_id=run["id"], resolution="synthetic_recovery_verified")
    assert item["state"] == "resolved" and failures[0]["id"] in item["run_ids"]
    assert [e["sequence"] for e in item["events"]] == list(range(1, item["version"] + 1))
    api.request("POST", f"/v1/incidents/{incident_id}/events", {"expected_version": 1, "type": "reopen", "reason": "recurrence"}, expected=409)
    assert api.request("GET", f"/v1/incidents/{incident_id}") == item
    passed("recovery_and_conflict")
    result = api.request("POST", "/v1/support/ask", {"question": "403 permission sharing"})
    assert result["status"] == "answered"
    for part in result["parts"]:
        assert part["text"] == next(c["excerpt"] for c in result["citations"] if c["id"] == part["citation_id"])
    assert api.request("POST", "/v1/support/ask", {"question": "How do I configure payroll?"})["reason"] == "NO_MATCH"
    passed("grounded_answers")
    pairs = [api.request("GET", f"/v1/incidents/{incident_id}/bundle?format={fmt}", raw=True) for fmt in ("json", "markdown")]
    for fmt, content in zip(("json", "markdown"), pairs):
        assert content == api.request("GET", f"/v1/incidents/{incident_id}/bundle?format={fmt}", raw=True)
        assert not any(secret and secret.encode() in content for secret in api.config.secrets)
    assert json.loads(pairs[0])["redaction"]["raw_payloads_included"] is False
    if export:
        write_pair(api.config.root / ".local/exports", *pairs)
    passed("stable_redacted_bundles")
    return {"offline_acceptance": "passed", "live_gate": "unverified", "steps": steps, "incident_id": incident_id, "run_ids": created}


def execute(args):
    if args.command == "init":
        return initialize(args.root), 0
    if args.command == "runbooks":
        root = root_path(args.root)
        if args.action == "check":
            books, diagnostics = snapshot(root, utc_now())
            return {"eligible": sorted(books), "diagnostics": diagnostics}, 0 if len(books) == 5 else 3
        return review(root, args.id, args.reviewer, args.days, utc_now()), 0
    try:
        config = Config.load(args.root, args.credentials_file)
    except ConfigError:
        if args.command == "live" and args.action == "verify":
            return {"live_gate": "unverified", "reason": "Missing valid live prerequisites."}, 7
        raise
    if args.command == "serve":
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(config), host="127.0.0.1", port=config.port, workers=1, proxy_headers=False, access_log=False, log_level="warning")
        return None, 0
    api = API(config, args.role)
    try:
        if args.command == "smoke":
            books, _ = snapshot(config.root, utc_now(), config.secrets)
            if len(books) != 5:
                return {"offline_acceptance": "failed", "reason": "Review eligibility required.", "live_gate": "unverified"}, 3
            return smoke(api, args.export), 0
        if args.command == "live":
            if config.mode != "live":
                return {"live_gate": "unverified", "reason": "Live configuration required."}, 7
            operations = [(args.operation, args.probe)] if args.action == "probe" else [(OPS[0], "health-text"), (OPS[1], "runbook-auth")]
            runs = [api.request("POST", "/v1/runs", {"mode": "live", "operation": op, "probe_id": probe, "acknowledge_live_request": True}) for op, probe in operations]
            if args.action == "probe":
                return runs[0], 0 if runs[0]["status"] == "succeeded" else 3
            return {"live_gate": "passed" if live_pass(runs) else "failed", "runs": runs}, 0 if live_pass(runs) else 3
        if args.command == "run":
            run = api.request("POST", "/v1/runs", {"mode": "offline", "operation": args.operation, "scenario_id": args.scenario})
            return run, 0 if run["status"] == "succeeded" else 3
        if args.command == "scenarios":
            return api.request("GET", "/v1/scenarios"), 0
        if args.command == "runs":
            return api.request("GET", "/v1/runs" + ("/" + args.id if args.action == "show" else "")), 0
        if args.command == "support":
            return api.request("POST", "/v1/support/ask", {"question": args.question}), 0
        if args.command == "incidents":
            if args.action == "create":
                return api.request("POST", "/v1/incidents", {"run_id": args.run}), 0
            path = "/v1/incidents/" + args.id
            if args.action == "show":
                return api.request("GET", path), 0
            if args.action == "export":
                pair = [api.request("GET", path + "/bundle?format=" + fmt, raw=True) for fmt in ("json", "markdown")]
                return write_pair(args.out, *pair), 0
            payload = {"expected_version": args.version}
            if args.action == "triage":
                return api.request("POST", path + "/triage", payload), 0
            payload["type"] = {"attach": "attach_run"}.get(args.action, args.action)
            if args.action == "check":
                payload.update(check_id=args.check, result=args.result)
            elif args.action == "attach":
                payload["run_id"] = args.run
            elif args.action == "resolve":
                payload.update(verification_run_id=args.run, resolution=args.resolution)
            elif args.action in ("reopen", "escalate"):
                payload["reason"] = "recurrence" if args.action == "reopen" else args.reason
            return api.request("POST", path + "/events", payload), 0
        raise ValueError("Invalid command")
    finally:
        api.close()


def main():
    for name in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(name).disabled = True
    try:
        result, code = execute(parser().parse_args())
        if result is not None:
            print(json.dumps(result, sort_keys=True, allow_nan=False))
    except (ConfigError, ValueError, OSError):
        print('{"error":"Invalid local input or configuration."}', file=sys.stderr)
        code = 2
    except LabError as exc:
        print(json.dumps({"error": exc.code}), file=sys.stderr)
        code = 6 if exc.status == 409 else 5 if exc.status >= 500 else 2
    except httpx.HTTPError:
        print('{"error":"Local server unavailable."}', file=sys.stderr)
        code = 5
    except AssertionError:
        print('{"error":"Verification failed."}', file=sys.stderr)
        code = 3
    raise SystemExit(code)
