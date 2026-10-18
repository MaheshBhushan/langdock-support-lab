import json
import httpx

OPERATIONS = ["agent_completion", "knowledge_search"]
EXPECTED = {"success": "OK", "auth-missing": "UPSTREAM_AUTH", "auth-invalid": "UPSTREAM_AUTH", "permission-denied": "UPSTREAM_PERMISSION", "throttled": "UPSTREAM_THROTTLED", "timeout": "UPSTREAM_TIMEOUT", "knowledge-empty": "OK_EMPTY"}


def registry(root):
    rows = json.loads((root / "fixtures/scenarios.json").read_text())
    if not isinstance(rows, list) or len(rows) != 7 or {r["id"] for r in rows} != set(EXPECTED):
        raise ValueError("Invalid scenario registry")
    for row in rows:
        if row["expected_code"] != EXPECTED[row["id"]] or row["provenance"] != "synthetic" or row["operations"] != (["knowledge_search"] if row["id"] == "knowledge-empty" else OPERATIONS) or not all(isinstance(row[k], str) and row[k] for k in ("label", "fault")):
            raise ValueError("Invalid scenario registry")
    return rows


def transport(root, scenario, operation):
    # Each invocation captures immutable bytes; it has no counters or live fallback.
    body = (root / "fixtures" / ("agent-success.json" if operation == "agent_completion" else "knowledge-success.json")).read_bytes()

    def handler(request):
        expected = None if scenario == "auth-missing" else "Bearer synthetic-invalid" if scenario == "auth-invalid" else "Bearer synthetic-valid"
        assert request.headers.get("authorization") == expected
        if scenario == "timeout":
            raise httpx.ReadTimeout("Synthetic timeout")
        status = {"auth-missing": 401, "auth-invalid": 401, "permission-denied": 403, "throttled": 429}.get(scenario, 200)
        content = b'{"error":"synthetic failure"}' if status != 200 else b'{"status":"success","result":[]}' if scenario == "knowledge-empty" else body
        return httpx.Response(status, content=content, headers={"Content-Type": "application/json", **({"Retry-After": "7"} if status == 429 else {})})

    return httpx.MockTransport(handler)
