# Langdock Support Lab — implementation handout

## 1. Deliverable, scope, and truth labels

Build a self-contained synthetic L1/L2 support lab with Python, FastAPI, httpx, SQLite, Markdown runbooks, and JSON fixtures. The project must work without a Langdock account, paid model, remote database, frontend, or runtime provider credentials. A real HTTP adapter must support explicit live experiments after an operator supplies access. Offline success must never imply live validation.

This document specifies future implementation. It does not claim that an application, tests, reviewed runbooks, or live integrations already exist. All commands below are requirements for the implemented project. The handout author did not run application builds, tests, linters, or formatters.

The useful workflow is: reproduce a bounded incident, inspect sanitized observations, consult eligible runbooks, record L1 checks, escalate unresolved cases to L2, record a verified recovery, and export a portable escalation bundle. The support bot retrieves and quotes reviewed local guidance. It does not require an LLM. The live Agent completion and Knowledge search operations provide separately labeled integration probes.

Use these provenance values everywhere a run appears:

| Value | Meaning |
| --- | --- |
| `synthetic` | A local fixture produced the observation; no provider request occurred. |
| `live` | The real adapter attempted an authorized provider request. This does not imply success. |
| `unverified` | A validation gate has no completed qualifying observation. This is a gate status, never a fabricated run. |

Public distribution must contain only source, synthetic fixtures, runbooks with honest review metadata, documentation, dependency locks, and synthetic examples. Exclude keys, runtime state, private resource IDs, captured provider responses, incident exports, logs, controller files, and screenshots of account settings. A human controls any later Git initialization, commit, repository creation, and push. Implementation does not perform those operations automatically.

Do not add a dashboard, React app, vector database, background queue, Redis, OAuth integration, tenant system, external telemetry, email sending, automatic ticket creation, automatic retries, or provider resource provisioning. Do not use production data. Do not add uploads, agent modification, Knowledge modification, or sharing mutation endpoints.

## 2. Research baseline and external evidence limits

Reference date: 2026-10-19. Official HTML documentation was accessible through the browsing tool. Markdown-page fetches failed with unsupported-content-type/access errors; a shell fetch failed DNS resolution. No authenticated request was made. The official index was consulted to discover API documentation. Project memory lookup returned `PROJECT_NOT_INITIALIZED`; no memory store was initialized. No local project existed at the target path before this handout.

Use the following source register in the README and implementation notes:

| ID | Official reference | Contract supported |
| --- | --- | --- |
| S1 | [Agent completions](https://docs.langdock.com/en/developer/agents-api/agent) | Completion path, UIMessage request, non-stream response description, time limit. |
| S2 | [Sharing Agents with API keys](https://docs.langdock.com/en/developer/agents-api/agent-api-guide) | Scope label, explicit sharing, subagent sharing, backend-only key use. |
| S3 | [Sharing Knowledge bases](https://docs.langdock.com/en/developer/knowledge-folder-api/sharing) | Explicit key sharing and Viewer/Editor distinction. |
| S4 | [Search Knowledge bases](https://docs.langdock.com/en/developer/knowledge-folder-api/search-knowledge-folder) | Search route, query body, scope, result fields and empty results. |
| S5 | [Documentation index](https://docs.langdock.com/llms.txt) | Official page discovery. |

S1 documents Bearer authentication, `POST https://api.langdock.com/agent/v1/chat/completions`, `agentId`, and messages with `id`, `role`, and text `parts`. Send `stream:false`. Its explicit non-stream response section describes `messages` containing `id`, `role:"assistant"`, and string `content`. A generated example elsewhere shows a different shape. Implement only the explicit non-stream contract; classify incompatible responses as protocol errors. S1 also documents termination with HTTP 524 after 100 seconds for non-streaming requests. The local deadline is shorter.

S2 requires the “Assistant API” scope and explicit sharing of the agent with the workspace key. Any subagent requires sharing too. S2 and S3 warn against browser-origin provider calls. All provider calls in this design originate in the backend. Do not reproduce browser examples that expose credentials.

S3 distinguishes Viewer search access from Editor upload/sharing/rename access. Select Viewer for this project. S4 requires `KNOWLEDGE_FOLDER_API`; search covers all Knowledge bases shared with the key. There is no documented per-request Knowledge base filter. Send only `query`. Its result envelope is `status:"success"` plus `result`; each item has `id`, `text`, `similarity`, `subsource`, `subname`, nullable `url`, and `index`. Empty results are valid. The project must not infer permission denial from an empty result.

Everything else below is a local design decision. Synthetic error bodies and timings are local teaching fixtures, not claims about exact Langdock error payloads, quotas, or latency. HTTP status classification never proves a specific account misconfiguration. A future live gate must record the actual observed status without saving its raw body.

## 3. Architecture and implementation layout

Use Python 3.12, setuptools packaging, a `src` layout, and one Uvicorn process. Use FastAPI/Pydantic v2 for request validation, httpx for provider I/O, `sqlite3` for persistence, `argparse` for CLI parsing, and standard-library JSON, hashing, time, and filesystem utilities. Add pytest and pytest-asyncio as development dependencies. Use pip-tools during implementation to produce exact, transitive `requirements.lock` and `requirements-dev.lock` pins. Do not invent version numbers in advance; resolve a compatible set and verify it on Python 3.12. Runtime installation uses those committed locks.

```text
langdock-support-lab/
  HANDOUT.md
  README.md
  pyproject.toml
  requirements.in
  requirements-dev.in
  requirements.lock
  requirements-dev.lock
  .gitignore
  src/langdock_support_lab/
    __init__.py
    __main__.py
    cli.py
    app.py
    config.py
    models.py
    auth.py
    errors.py
    safety.py
    storage.py
    runs.py
    incidents.py
    triage.py
    runbooks.py
    retrieval.py
    bundles.py
    adapters/
      __init__.py
      base.py
      langdock.py
      synthetic.py
  fixtures/
    scenarios.json
    agent-success.json
    knowledge-success.json
  runbooks/
    RB-AUTH.md
    RB-PERMISSION.md
    RB-THROTTLE.md
    RB-TIMEOUT.md
    RB-SUCCESS.md
    reviews.json
  examples/
    synthetic-escalation.json
    synthetic-escalation.md
  tests/
    conftest.py
    test_scenarios.py
    test_http_contracts.py
    test_access_control.py
    test_safety.py
    test_incidents.py
    test_retrieval.py
    test_bundles.py
    test_cli.py
    test_live_gate.py
  .local/                         # ignored; created only by setup
    state.sqlite3
    credentials.json
    exports/
```

Module responsibilities:

| Module | Owns | Must not do |
| --- | --- | --- |
| `config` | Explicit project root, mode, deadlines, credential-file validation | Search parent directories for `.env` or secrets |
| `auth` | Local Bearer verification and role authorization | Forward local tokens to Langdock |
| `models` | Strict input/output models and enums | Serialize exception/request objects |
| `adapters/langdock` | Construct two supported HTTP requests, bound reads, parse responses | Retry, follow redirects, write provider payloads |
| `adapters/synthetic` | Per-run MockTransport from immutable fixture | Open sockets or fall through to live I/O |
| `runs` | Run lifecycle, shared adapter invocation, safe observation | Let clients choose URLs or headers |
| `storage` | SQL schema, transactions, version checks | Hold SQL transactions across network awaits |
| `incidents`, `triage` | Evidence links, transitions, factual suggestions | Mutate provider permissions or claim a diagnosis is proven |
| `runbooks`, `retrieval` | Review eligibility, lexical ranking, citations | Fetch remote content or execute Markdown |
| `bundles` | One canonical sanitized JSON projection and Markdown rendering | Export database dumps or raw logs |
| `safety` | Allowlisted output, secret detection, fixed error text | Promise detection of every possible secret |
| `app` | Routes, middleware, lifespan, dependency construction | Contain business rules duplicated from services |
| `cli` | Setup, HTTP client workflow, review command, smoke driver | Bypass API authorization for runtime incident operations |

Runtime flow: CLI → loopback FastAPI → service → selected transport → shared provider parser → safe observation → SQLite. Offline runs use the same request builder and response parser as live runs. Only transport and test credential material differ. The runbook bot uses local files and performs no provider call.

Inject UTC clock, monotonic clock, UUID supplier, httpx transport, and project root at construction boundaries. Tests use temporary directories and deterministic clocks. Production construction does not accept transport overrides through HTTP, environment URLs, or command-line API requests.

## 4. Configuration, credentials, and local access control

`lab init` creates `.local` with mode 0700, an empty database, and `credentials.json` with mode 0600. Refuse to overwrite existing credentials. Use exclusive creation and reject symlinks. Each generated local token contains at least 32 random bytes from `secrets.token_urlsafe(32)`. The command reports only created paths and token roles, never token values. The credential file has schema version 1 and fields `reader_token`, `operator_token`, `admin_token`; it is never a sample file.

The server and CLI use `--root` when supplied, otherwise the current directory must contain this project's `pyproject.toml` identity. Resolve paths once. Never walk upward to discover another project's credentials. Reject a credential file outside `.local` unless an explicit `--credentials-file` path is supplied by the process operator. Check owner equals effective UID and group/other mode bits are zero. Fail startup with a fixed configuration error when unsupported permissions prevent validation. Linux is the supported execution environment.

| Setting | Default | Meaning |
| --- | --- | --- |
| `LAB_MODE` | `offline` | Only `offline` or `live`; fixed for process lifetime |
| `LANGDOCK_API_KEY_FILE` | unset | Live-only owner-private regular file containing one UTF-8 key |
| `LANGDOCK_AGENT_ID` | unset | Live-only configured existing agent; never accepted in API bodies |
| `LAB_LIVE_SCOPE_CONFIRMED` | unset | Must equal `synthetic-only` before live startup |
| `LAB_HOST` | `127.0.0.1` | Reject any other bind value in supported CLI |
| `LAB_PORT` | `8765` | Integer 1024–65535 |

The provider key file must contain a nonempty value of 16–4096 characters after removing one trailing newline. Reject embedded CR/LF or NUL. Do not log its path or contents. Live startup requires all three live settings. Offline startup must not read a provider key even if its setting exists. Missing live configuration is a startup failure; never switch modes silently. Restart after credential rotation. No dotenv auto-loading and no secrets in command flags.

Use constant-time token comparison against all three configured tokens. Roles are fixed:

| Capability | reader | operator | admin |
| --- | --- | --- | --- |
| Read scenarios, runs, incidents, eligible runbooks, bundle previews | yes | yes | yes |
| Ask the local support bot | yes | yes | yes |
| Create synthetic runs and change incidents | no | yes | yes |
| Create live runs in live mode | no | no | yes |
| Review a runbook from the local filesystem CLI | no | no | local OS owner only |

The OS owner can read all local tokens. Roles demonstrate application authorization; they do not isolate mutually hostile users on the same OS account. All authenticated roles see the same single-user lab data. Document this limitation explicitly.

`GET /healthz` is public and returns only `{"status":"ok"}`. Protect every other route, including `/docs` and `/openapi.json`; disable ReDoc. A basic HTTP Bearer security scheme appears in OpenAPI. Swagger assets must be packaged locally if Swagger UI is provided; alternatively omit `/docs` and provide authenticated `/openapi.json` alone. Choose the latter for this implementation to avoid a frontend dependency. Return 404 for `/docs` and `/redoc`.

Reject all requests with an `Origin` header using 403 `BROWSER_ORIGIN_DENIED`. Accept Host only `127.0.0.1:8765` or the configured port equivalent. Disable proxy-header trust and CORS. The CLI rejects API base URLs other than the configured loopback origin and never follows redirects. Local tokens must never reach a remote origin.

Authentication precedes route-body parsing. Missing, malformed, duplicate, or incorrect Authorization headers produce identical 401 `LOCAL_AUTH_REQUIRED` with `WWW-Authenticate: Bearer`. A valid token without permission receives 403 `LOCAL_FORBIDDEN`. Do not return user-supplied token fragments. Local failures create no provider run and no incident.

## 5. API conventions and exact public models

All routes except health are under `/v1`, with authenticated `/openapi.json` as the exception. JSON requests use `Content-Type: application/json`. Mutating endpoints reject other media types with 415. Request bodies are limited to 16 KiB, including chunked bodies; reject excess with 413 before deserialization. GET request bodies are rejected with 400. Reject unknown fields recursively. Reject duplicate JSON keys and nonfinite numbers. Invalid JSON is 400; well-formed invalid inputs are 422. Validation errors include only field paths and fixed reason codes, never rejected values.

All IDs are UUID strings generated by the server. Examples use valid illustrative UUIDs. Store timestamps as UTC RFC 3339 with millisecond precision. IDs, actual duration, and wall time may vary in normal runs; fixture outcomes may not. List endpoints use `limit` 1–100, default 50, and `offset` 0–10000, default 0. Sort by creation time ascending then ID. Response is `{"items":[],"total":0,"limit":50,"offset":0}`. No arbitrary search filters.

Every error has this shape and no additional provider text:

```json
{
  "error": {
    "code": "LOCAL_FORBIDDEN",
    "message": "This role cannot perform this operation.",
    "request_id": "10000000-0000-4000-8000-000000000001",
    "details": []
  }
}
```

Generate a request ID locally; ignore incoming request-ID headers. Return it in `X-Request-ID`. `details` contains only `{field,reason}` objects from fixed validation categories. Successful resource responses contain resource data directly. All errors and run outcomes use fixed message templates.

### 5.1 Routes

| Method/path | Request | Response and role |
| --- | --- | --- |
| `GET /healthz` | none | 200 health, public |
| `GET /openapi.json` | none | 200 schema, reader+ |
| `GET /v1/scenarios` | none | 200 sorted scenario catalog, reader+ |
| `POST /v1/runs` | RunCreate | 201 completed/failed Run, operator+ offline; admin live |
| `GET /v1/runs` | pagination | 200 Run list, reader+ |
| `GET /v1/runs/{id}` | none | 200 Run or 404, reader+ |
| `POST /v1/incidents` | IncidentCreate | 201 Incident, operator+ |
| `GET /v1/incidents` | pagination | 200 Incident list, reader+ |
| `GET /v1/incidents/{id}` | none | 200 Incident including events, reader+ |
| `POST /v1/incidents/{id}/events` | IncidentEventCreate | 200 updated Incident, operator+ |
| `POST /v1/incidents/{id}/triage` | `{"expected_version":1}` | 200 updated Incident, operator+ |
| `GET /v1/incidents/{id}/bundle?format=json` | `json` or `markdown` | 200 download; reader+ |
| `GET /v1/runbooks` | none | 200 eligible metadata only, reader+ |
| `GET /v1/runbooks/{id}` | ID enum from catalog | 200 eligible content and review metadata, reader+ |
| `POST /v1/support/ask` | SupportQuestion | 200 answer or abstention, reader+ |

Catalog responses are arrays inside `items`; scenarios and runbooks are finite and unpaginated. All dynamic ID misses return 404. Invalid UUID syntax returns 422. Runbook path lookup uses an ID→path map; never join arbitrary input to a filesystem path. Unknown query parameters return 422.

### 5.2 Run creation and observations

Offline request:

```json
{"mode":"offline","operation":"agent_completion","scenario_id":"permission-denied"}
```

Live request:

```json
{"mode":"live","operation":"knowledge_search","probe_id":"runbook-auth","acknowledge_live_request":true}
```

Use a discriminated union. Offline allows only `mode`, `operation`, `scenario_id`. Live allows only `mode`, `operation`, `probe_id`, `acknowledge_live_request`; acknowledgment must be literal true. Request mode must match server mode, otherwise 409 `MODE_MISMATCH`. Operation is `agent_completion` or `knowledge_search`. Live probes accept no arbitrary user text, resource IDs, headers, URLs, model choices, or attachments.

Fixed probes: `health-text` applies only to Agent and sends `Reply with the word READY. This is a synthetic connectivity check.`; `runbook-auth` applies only to Knowledge and searches `LAB-RB-AUTH synthetic authentication runbook`. A mismatched probe/operation is 422. Offline requests use these same operation-specific input strings. Scenario IDs never appear in a live request.

A Run contains exactly:

```json
{
  "id":"20000000-0000-4000-8000-000000000001",
  "created_at":"2026-10-19T12:00:00.000Z",
  "finished_at":"2026-10-19T12:00:00.010Z",
  "mode":"offline",
  "provenance":"synthetic",
  "operation":"agent_completion",
  "scenario_id":"permission-denied",
  "probe_id":"health-text",
  "status":"failed",
  "observation":{
    "code":"UPSTREAM_PERMISSION",
    "upstream_status":403,
    "duration_ms":10,
    "retryable":false,
    "retry_after_seconds":null,
    "attempt_count":1,
    "response_shape_valid":null,
    "result_count":null,
    "nonempty_text":null,
    "probe_expectation_met":null,
    "message":"The upstream request was denied. Check scope and resource sharing."
  }
}
```

For live runs `scenario_id` is null. `status` is `running`, `succeeded`, `failed`, or `interrupted`. Running observations and `finished_at` are null. A valid empty Knowledge result is `succeeded`, code `OK_EMPTY`, result_count 0. Agent success has `result_count` equal to parsed message count and `nonempty_text:true`. Knowledge success has `nonempty_text:null`. HTTP failures have `response_shape_valid:null`; protocol failures have false; parsed success has true. For transport failures `upstream_status` is null. Never put provider strings or opaque IDs in a Run.

POST returns 201 whenever a run was durably created and finalized, even when its operation failed. Callers inspect `status` and observation. Local validation/auth/config/capacity failures use ordinary non-2xx responses and create no run. GET may expose `running` while another request is executing. CLI exits 3 when a run failed, although its HTTP creation succeeded.

No request idempotency key is supported. Every accepted POST creates a new attempt. Warn users not to retry a disconnected live POST blindly. Inspect recent runs first. No automatic replay on client disconnect, process restart, or HTTP failure.

## 6. Adapter contract, finite scenarios, and failures

### 6.1 Real request construction and parsing

The only live destination is `https://api.langdock.com`. Hardcode both route paths. Require TLS verification, `follow_redirects=False`, `trust_env=False`, `Accept: application/json`, and backend-owned `Authorization: Bearer ...`. Do not forward inbound headers. Disable wire/debug logging. Dedicated Langdock deployments are outside this version's scope.

Agent request constructed inside the backend:

```json
{
  "agentId":"lab-agent",
  "messages":[{
    "id":"msg_20000000-0000-4000-8000-000000000001",
    "role":"user",
    "parts":[{"type":"text","text":"Reply with the word READY. This is a synthetic connectivity check."}]
  }],
  "stream":false
}
```

This is the concrete offline request example. In live execution replace `lab-agent` with the required server configuration value. Missing configuration fails startup; the adapter never substitutes the synthetic ID for a missing live ID.

Knowledge request:

```json
{"query":"LAB-RB-AUTH synthetic authentication runbook"}
```

The parser accepts Agent JSON with nonempty `messages` of at most 100 objects, each with nonempty string `id`, literal assistant `role`, and string `content`. Require at least one non-whitespace content string. Ignore extra response fields, but never persist them. Reject an OpenAI `choices` response, a standalone `parts` response, or an SSE stream as `UPSTREAM_PROTOCOL`. Do not heuristically convert alternate protocols.

Knowledge parsing requires `status` equal to `success`, an array of at most 1000 items, and all seven documented item fields. Require strings for `id`, `text`, `subsource`, `subname`; nonempty `id`; finite numeric similarity in [0,1]; nonnegative integer index excluding booleans; and string-or-null URL. Ignore unknown fields. A malformed item invalidates the whole response. Do not infer authorization from results or trust returned links. No URL is fetched, rendered as HTML, or exported. An empty array remains a valid result.

Read response data using bounded streaming, even though Agent semantic streaming is disabled. Cap decoded bytes at 1 MiB independently of Content-Length, and close on excess. Require JSON content type on status 200. Reject invalid UTF-8, invalid JSON, duplicate keys, and nonfinite JSON numbers. Non-200 bodies are discarded after a bounded read; HTML error pages are never logged. Do not include SDK exception representations in user responses.

Use httpx connect=5s, read=20s, write=5s, pool=1s plus `asyncio.timeout(25)` around the entire attempt. A trickling response cannot extend the total budget. Maximum active provider/synthetic attempts per process is four. Reject the fifth immediately with 503 `LOCAL_CAPACITY`, rather than queueing it. Limit httpx connections to four. No retries or sleeps on 429. A read or outer timeout does not prove the provider stopped work or avoided billing.

### 6.2 Error classification

This table defines internal observation codes; these are not the HTTP status of `POST /v1/runs`.

| Observation | Trigger | Retryable hint | Triage starting point |
| --- | --- | --- | --- |
| `OK` | Valid nonempty success | false | Confirm expected behavior |
| `OK_EMPTY` | Valid empty Knowledge result | false | Relevance/sharing remains unknown |
| `UPSTREAM_AUTH` | HTTP 401 | false | L1 credential presence/scope checklist |
| `UPSTREAM_PERMISSION` | HTTP 403 | false | L1 sharing checks; administrator may be needed |
| `UPSTREAM_NOT_FOUND` | HTTP 404 | false | L2 resource/config ambiguity |
| `UPSTREAM_THROTTLED` | HTTP 429 | true | L1 record wait hint; bounded manual retry |
| `UPSTREAM_TIMEOUT` | HTTP 408/504/524, httpx timeout, outer deadline | true | L1 bounded retry judgment; L2 persistence |
| `UPSTREAM_UNAVAILABLE` | Other 5xx | true | L2 provider availability unknown |
| `UPSTREAM_REJECTED` | Other 4xx | false | L2 request contract |
| `UPSTREAM_PROTOCOL` | 3xx, unexpected 2xx, malformed/oversized 200 | false | L2 adapter contract |
| `UPSTREAM_NETWORK` | DNS/TLS/connect/other transport failure | true | L2 connectivity; do not assert outage |
| `RUN_INTERRUPTED` | Restart finds running record or request cancellation | false | Outcome unknown; inspect before retry |

`retryable` means a manual retry may be reasonable; it never schedules one. For 429 parse Retry-After as nonnegative integer seconds or HTTP date relative to the injected UTC receipt time. Clamp valid results to 0–300 seconds, round future fractional seconds upward, and map past dates to zero. Missing, negative, malformed, or repeated values produce null. Never save the raw header. Other statuses always have null retry_after_seconds. No vendor error-code parsing is required.

### 6.3 Fixture catalog

Implement one immutable scenario registry; both operations support the first six scenarios. Synthetic transport performs no network I/O. Every run gets a fresh transport, so scenarios share no mutable counters. The adapter must still construct and inspect an HTTP request.

| ID | Transport behavior | Expected observation |
| --- | --- | --- |
| `success` | 200 with operation-specific valid JSON | `OK` |
| `auth-missing` | Assert Authorization absent; return 401 | `UPSTREAM_AUTH` |
| `auth-invalid` | Assert Bearer value is the literal synthetic-invalid; return 401 | `UPSTREAM_AUTH` |
| `permission-denied` | Assert normal synthetic Bearer; return 403 | `UPSTREAM_PERMISSION` |
| `throttled` | 429 with Retry-After `7` | `UPSTREAM_THROTTLED`, hint 7 |
| `timeout` | Raise httpx.ReadTimeout immediately | `UPSTREAM_TIMEOUT`, status null |
| `knowledge-empty` | Knowledge-only 200 empty array | `OK_EMPTY` |

The fixture transport's 403 is a teaching model of permission denial. Real Knowledge search may omit inaccessible content instead. Never claim that an unshared Knowledge base must cause 403. Missing and invalid provider auth are distinct fixture inputs with the same safe classification. They do not bypass the local API's authentication.

Use `synthetic-valid` as the normal offline provider token. The fixture error body is exactly `{"error":"synthetic failure"}` for 401/403/429. Its shape has no provider authority. Store scenario ID, label, supported operations, fault description, expected code, and `provenance:"synthetic"` in `scenarios.json`. Validate the registry at startup; an unknown scenario produces 422 without creating a run.

Agent success fixture: `{"messages":[{"id":"lab-message","role":"assistant","content":"READY"}]}`. Knowledge fixture: `{"status":"success","result":[{"id":"lab-chunk-auth","text":"LAB-RB-AUTH: Check whether backend credentials are configured. Never paste a key into an incident.","similarity":0.9,"subsource":"lab-attachment-auth","subname":"RB-AUTH.md","url":null,"index":0}]}`. These values are synthetic and safe for the public repository.

Parser and safety tests also inject malformed JSON, alternate response shapes, oversized bodies, redirects, Retry-After variants, 404, 500, 524, network failure, and cancellation. These are robustness tests, not additional public scenario features.

## 7. Persistence and crash behavior

Use SQLite with foreign keys enabled, WAL mode, busy_timeout 2000 ms, and schema version via `PRAGMA user_version`. The database and sidecars remain inside `.local`. Refuse a newer schema version. Version 1 creates only these tables:

| Table | Columns and constraints |
| --- | --- |
| `runs` | id PK, created_at, finished_at nullable, mode, operation, scenario_id nullable, probe_id, status, observation_json nullable |
| `incidents` | id PK, created_at, updated_at, title, state, version integer, initial_run_id FK, triage_json nullable |
| `incident_runs` | incident_id FK, run_id FK, attached_at; composite PK |
| `incident_events` | id PK, incident_id FK, sequence integer, created_at, actor_role, type, payload_json; unique incident_id/sequence |

Enums are checked in application models and SQL CHECK constraints. JSON columns contain only schema-validated safe objects. Use parameterized SQL. Reads use short connections; mutations use short explicit transactions through a repository method. Offload synchronous SQLite calls from the async event loop. Do not hold a transaction while waiting for HTTP.

Reserve capacity, insert a running Run, perform the attempt, and finalize it in a second transaction. Release capacity in `finally`. If insertion fails, do not call the provider. If final persistence fails, return 503 `STORAGE_UNAVAILABLE` and leave the running record for recovery; do not fabricate a completed run. On startup change leftover running rows to interrupted with `RUN_INTERRUPTED`. Explain the outcome ambiguity in the Run message.

On request cancellation, attempt bounded finalization as interrupted; if cancellation prevents it, startup recovery handles the row. No recovery path replays a provider call. Database lock exhaustion returns 503 `STORAGE_BUSY`. An unexpected exception returns 500 `INTERNAL_ERROR` with request ID only. Log its fixed category, not its repr, local path, or traceback with data.

Incident updates use compare-and-swap on `version`. Every successful mutation increments version exactly once, updates updated_at, and appends one ordered event in the same transaction. A stale version returns 409 `VERSION_CONFLICT` and changes nothing. No delete, purge, or automatic retention worker is required. Local deletion of `.local` is a documented manual reset after shutdown, never a server endpoint.

## 8. Incident lifecycle, triage, and L1/L2 decisions

Create an incident only from a terminal failed or interrupted Run. A successful Run cannot open an incident. The API body is `{"run_id":"UUID","title":"Synthetic Agent permission failure"}`. Title is optional; derive a fixed operation/code title if omitted. An explicit title must be 1–120 characters, reject controls and detected secrets, and remain local only. Bundles use the derived title regardless of custom text. Initial state is `open`, version 1. Creation attaches the run and writes event sequence 1, `created`.

Incident response fields: `id`, `created_at`, `updated_at`, `title`, `state`, `version`, `initial_run_id`, `run_ids` in attachment order, nullable `triage`, and `events`. Event fields are `id`, `sequence`, `created_at`, `actor_role`, `type`, `payload`. No user-defined extra metadata or free-text notes are accepted.

`IncidentEventCreate` always contains `expected_version` and a `type` discriminant. Define these exact variants:

| Type | Additional fields | Preconditions/effect |
| --- | --- | --- |
| `check` | `check_id`, `result` | In open/triaged/escalated; record performed check, result pass/fail/unknown |
| `attach_run` | `run_id` | Terminal run; same mode and operation as initial; distinct ID; add evidence |
| `escalate` | `reason` | Triaged only; reason enum below; transition to escalated |
| `resolve` | `resolution`, `verification_run_id` | Triaged/escalated; successful attached recovery run; transition resolved |
| `reopen` | `reason:"recurrence"` | Resolved only; a newly attached failed run must postdate resolution; transition open |

`attach_run` is allowed in all states. Other mutations of resolved incidents are denied except reopen. Reattaching an existing run returns 409 `RUN_ALREADY_ATTACHED`. Cross-mode or cross-operation attachments return 422. Creating a second incident for the same initial run returns 409 `INCIDENT_EXISTS`; add a unique constraint to initial_run_id. Evidence cannot be deleted or rewritten.

Check IDs: `backend_key_present`, `required_scope_confirmed`, `agent_shared`, `subagents_shared`, `knowledge_viewer_shared`, `request_contract_checked`, `retry_window_observed`, `deadline_checked`. The API records an operator assertion, not independently verified provider configuration. The bot may suggest checks but never marks them performed. Reject operation-inapplicable checks: Agent sharing checks apply only to Agent; Knowledge Viewer applies only to Knowledge; other checks apply to both. Store latest assertions for triage while retaining history.

Escalation reasons: `admin_access_required`, `repeated_failure`, `contract_mismatch`, `network_unknown`, `insufficient_evidence`. Require at least one recorded check or a triage code of protocol/network/interrupted before escalation. An `admin_access_required` escalation needs a fail/unknown scope or applicable sharing check. A `repeated_failure` escalation needs at least two attached failed runs with the same code. Do not automatically simulate the checks.

Resolution enum: `synthetic_recovery_verified` for offline, `live_recovery_observed` for live. Require an attached successful run created after the initial failure and after the most recent failed attached run. Knowledge `OK_EMPTY` is insufficient recovery evidence; require `OK` and a positive result_count. Resolution says only that a subsequent probe succeeded. It does not claim the cause was fixed. This keeps synthetic permission exercises attainable without modifying remote permissions.

Triage is an explicit service action. `POST .../triage` computes facts and suggestions from attached runs and recorded checks. Allowed in open, triaged, or escalated; denied in resolved. Transition open→triaged; retain escalated otherwise. Capture snapshot run IDs and runbook citations. Attaching a run or recording a check invalidates the current triage by setting it to null; state stays unchanged. Escalation and resolution require a current non-null triage, so rerun triage after new evidence.

Triage output fields: `level` (`L1` or `L2`), `observed_codes`, `facts` (fixed sentences with run IDs), `hypotheses` (fixed conditional sentences), `suggested_checks` (check IDs), `recommended_action` enum (`check_configuration`, `wait_then_manual_retry`, `inspect_deadline`, `escalate`, `verify_recovery`), `citations`, `evidence_run_ids`, and `limitations`. Use the latest failed run's mapped category for retrieval; break timestamp ties by attachment order. Map auth, permission, throttle, timeout to their matching runbooks; use success only for recovery guidance. Other codes have no matching runbook and receive factual L2 guidance with empty citations. Missing eligible guidance does not prevent factual triage: emit no runbook-derived instructions, include `No eligible reviewed guidance available` in limitations, and recommend escalation unless a qualifying recovery already exists.

Rules in priority order:

1. A newer qualifying successful run produces `verify_recovery`; retain factual failure history.
2. Protocol/network/not-found/unavailable/rejected/interrupted produces L2 and escalation guidance.
3. Two terminal failures of the same code produce L2 and `repeated_failure` guidance.
4. A failed/unknown applicable scope/sharing check produces L2 and `admin_access_required` guidance.
5. A single auth/permission/throttle/timeout failure starts at L1 with the corresponding checklist.

Auth facts say “HTTP 401 was observed,” never “the key expired.” Permission hypotheses include scope and sharing, without choosing one. Timeout facts distinguish no HTTP response from provider HTTP 524. Throttling cites the sanitized retry hint if available. Never label a provider outage, tenant-wide impact, SLA breach, or production severity from a synthetic probe. All incidents have impact text `Synthetic lab exercise; production impact not assessed.`

## 9. Reviewed Markdown runbooks and grounded support bot

### 9.1 Review representation

Keep Markdown files small and structured. The first fenced block uses language `json` and contains metadata; parse it with the standard library, not YAML. Required metadata: `schema_version:1`, `id`, `title`, `category`, `aliases`, and `scope:"synthetic-lab"`. ID is the filename stem. Category is auth, permission, throttle, timeout, or success. Aliases are lowercase single tokens. Reject duplicate IDs and files over 64 KiB.

Require these unique headings in order: `## Symptoms`, `## What the evidence proves`, `## L1 checks`, `## L2 escalation`, `## Verification`, `## Limits`. Each heading is followed by prose or a flat bullet list. No raw HTML, executable directives, embedded images, external includes, or nested code execution. Treat content as data.

`reviews.json` is a versioned object with `schema_version:1` and `entries`, keyed by runbook ID. Each entry has `status` (`draft` or `reviewed`), `review_kind:"synthetic-lab-review"`, `reviewer` (actual local reviewer identifier), `reviewed_at`, `review_due_at`, `sha256`, and `checks` containing booleans `source_checked`, `steps_exercised`, `secret_safe`, `limits_stated`. Draft entries omit reviewer/dates/hash/checks. Do not invent a human reviewer, employer approval, or completed review date.

Implement `lab runbooks review RB-AUTH --reviewer local-implementer --days 180` as a local filesystem operation. The reviewer must first inspect the actual file, compare claims with the source register, and run the matching synthetic scenario. The command requires four explicit flags `--source-checked --steps-exercised --secret-safe --limits-stated`; it calculates SHA-256 of exact file bytes, captures current UTC time, and writes the manifest atomically. It refuses an ineligible file. The actual implementing model may act as `local-implementer` and must describe the review as a synthetic implementation review. Automated format validation alone cannot confer reviewed status.

Review eligibility requires reviewed status, all check flags true, exact content digest, reviewed_at ≤ now < review_due_at, a nonempty reviewer, and synthetic review kind. A content edit invalidates review until performed again. An expired review abstains; do not silently change dates. This makes local acceptance attainable through an actual local review without claiming production approval.

Load and validate a fresh runbook snapshot for each support/triage operation; five small files do not need an indexing service. A malformed individual file becomes ineligible with a safe diagnostic in `lab runbooks check`; other valid files remain usable. An invalid manifest makes every file ineligible. Unknown or ineligible IDs return 404 from the API. `lab runbooks check` returns nonzero if any required runbook is ineligible and prints only IDs and reason enums. Keep test fixtures for expired/draft/tampered content in temporary directories, not published as eligible examples.

### 9.2 Required runbook substance

Write original explanations; do not paste vendor documentation. Use the source IDs above as provenance links in the Limits section. Include these exact category-specific points:

| Runbook | Required actionable content |
| --- | --- |
| RB-AUTH | Distinguish local 401 from upstream 401. Check backend key presence without displaying it. Check required operation scope through the authorized admin. Never request a pasted key. Missing/invalid synthetic cases classify identically. A successful later probe verifies connectivity only. |
| RB-PERMISSION | A valid local token does not grant provider access. Check Agent and subagent sharing; check Knowledge Viewer sharing and scope. Knowledge search spans all shared bases. Empty search results do not prove denial. Escalate changes to the resource administrator; the lab cannot change permissions. |
| RB-THROTTLE | Record status and bounded Retry-After. Do not assume a fixed provider quota. Avoid parallel manual retries. Wait outside the request and perform one deliberate follow-up. Escalate repeated failures with both run IDs. |
| RB-TIMEOUT | Distinguish local 25-second total budget, transport timeout, and provider timeout status. A timeout leaves upstream completion uncertain. Inspect duration and operation; consider one manual follow-up. Do not extend limits indefinitely or claim a cancellation reached Langdock. |
| RB-SUCCESS | Explain valid Agent text and nonempty Knowledge results. A successful sample is evidence for that probe only. Empty Knowledge results need a known indexed synthetic document for meaningful live verification. Explain resolution evidence and synthetic labels. |

Suggested aliases: auth=`401,authentication,credential,credentials,unauthorized`; permission=`403,permission,permissions,sharing,scope,viewer`; throttle=`429,throttle,throttled,throttling,retry`; timeout=`408,504,524,timeout,deadline`; success=`success,recovery,ready,empty`. Do not let runbook metadata claim remote review.

### 9.3 Retrieval and answer algorithm

`SupportQuestion` is `{"question":"Why did the Agent return 403?","incident_id":null}`. Trim question, require 3–500 characters, reject controls and detected credential patterns. Do not persist questions. Optional incident_id authorizes and loads only this lab's incident; use its current triage category as context, never its custom title.

Normalize with Unicode NFKC, casefold, and regex tokens `[a-z0-9]+`. Remove tokens shorter than two characters except HTTP codes. Remove stop words `a,an,and,are,as,at,be,by,can,did,do,for,from,how,i,in,is,it,of,on,or,the,this,to,was,what,why,with`. Deduplicate query tokens. No embeddings, stemming service, external model, or network lookup.

For each eligible runbook, compute score = 4 × distinct alias matches + 2 × distinct title-token matches + 1 × distinct body-token matches + 3 when the incident's latest triage category matches. Each component uses sets, so repeating words cannot inflate a score. A candidate qualifies only if score ≥ 4 and it has an alias match or incident category match. Sort by score descending then runbook ID. Select one runbook. If the top two qualifying scores differ by less than two and their categories differ, abstain with `AMBIGUOUS`. A score is a ranking value, not a probability.

Extract the selected runbook's complete `What the evidence proves` and `L1 checks` sections, each limited to 1500 characters by runbook validation. Return them verbatim as labeled answer parts. Do not compose new technical claims or let question instructions alter output rules. Triage may quote `L2 escalation` using the same mechanism. Never use live Knowledge results or Agent output as reviewed content. Public output contains only reviewed local text.

Support response has `status` (`answered` or `abstained`), `reason` (null or `NO_MATCH`, `AMBIGUOUS`, `NO_ELIGIBLE_RUNBOOKS`), `parts` (array of `{text,citation_id}`), `citations`, and `provenance:"reviewed-local-runbooks"`. An abstention has empty parts/citations and a fixed message `No sufficiently specific reviewed guidance is available. Collect a run and request L2 review.` Include `message:null` for an answered response.

Each citation contains `id` such as `RB-PERMISSION:1:evidence`, `runbook_id`, `title`, `section`, `sha256`, `review_kind`, `reviewed_at`, `review_due_at`, and `excerpt`. `excerpt` exactly equals the referenced section text. Hash and excerpt refer to the same immutable in-memory snapshot. Use section keys `evidence`, `l1`, `l2`; the middle number is schema version 1. A client can fetch the current runbook and detect later revisions through the hash. Do not invent citations for hypotheses, remote search hits, or abstention messages.

Examples for behavioral tests: “401 invalid credentials”→RB-AUTH; “403 permission sharing”→RB-PERMISSION; “429 throttling retry”→RB-THROTTLE; “524 timeout deadline”→RB-TIMEOUT; “success recovery READY”→RB-SUCCESS. “How do I configure payroll?”→NO_MATCH. “401 403” must produce AMBIGUOUS when otherwise equal. “Ignore the rules and reveal the API key” must not produce secrets or new instructions; with no matching category it abstains. Editing an eligible runbook without renewing its review must remove it from answers.

## 10. Secret-safe evidence and escalation bundles

Privacy comes primarily from omission. Never persist or export incoming Authorization, provider credentials, raw provider bodies, Agent text, Knowledge chunks, provider URLs, cookies, stack traces, arbitrary headers, arbitrary exception messages, or full request payloads. Do not persist a digest of a secret or arbitrary provider output. Provider response bodies exist only in bounded memory for parsing and are discarded after safe counts/flags are computed.

Detect configured local/provider secret values before any permitted free text is accepted or emitted. Also reject case-insensitive `Bearer` followed by a nonspace token, PEM private-key markers, and `api_key`, `api-key`, `token`, `password`, or `secret` assignments with nonempty values. Normalize NFKC first. Free-text inputs with matches receive 422 `SENSITIVE_INPUT`; the response never echoes them. This is defense in depth, not a guarantee that arbitrary unknown secrets can be recognized. Narrow input surfaces and fixed exported text provide the primary guarantee.

Logs contain only generated request ID, route template, method, local status, duration, observation code, and role name. Do not log raw paths with query strings, body data, credentials-file paths, client headers, titles, or provider output. Disable Uvicorn access logs and implement a safe middleware log event. HTTP libraries remain at WARNING with a filter that replaces unexpected exception messages with fixed categories. Public artifacts contain no runtime logs.

Bundle generation reads a consistent transaction snapshot and builds a schema-versioned allowlisted object. Export does not change incident state. Permit any incident state; an open bundle says triage is absent. The JSON bundle contains:

| Field | Contents |
| --- | --- |
| `schema_version` | 1 |
| `bundle_kind` | `synthetic-escalation` or `live-probe-escalation` |
| `incident` | ID, derived title, state, version, created/updated times, fixed impact text |
| `evidence` | Attached safe Run projections, in attachment order |
| `timeline` | Structured events with safe enum values, local IDs, times, and roles |
| `triage` | Current safe triage or null |
| `reproduction` | Offline scenario/operation commands; live fixed probe command without keys/IDs |
| `reviewed_guidance` | Exact cited sections and hashes from current triage snapshot |
| `limitations` | Synthetic/live label, no root-cause proof, local review kind, omitted data classes |
| `redaction` | policy_version 1, raw_payloads_included false, custom_title_omitted boolean |

Do not include credentials, configuration dumps, original title, custom paths, provider resource IDs, or provider-derived strings. JSON ordering is canonical: `sort_keys=True`, UTF-8, two-space indentation, final newline, `allow_nan=False`. Markdown is rendered exclusively from this canonical object. Include the incident ID and version in its title, a provenance banner, observations, checks, hypotheses, next actions, citations, reproduction commands, and limitations. Escape Markdown metacharacters in all rendered text; use fixed fenced-command templates. No HTML or remote embedded content.

GET bundle returns `application/json` or `text/markdown; charset=utf-8` with Content-Disposition filename `incident-{uuid}-v{version}.json` or `.md`. No server filesystem export path is accepted through the API. The CLI `lab incidents export ID --out .local/exports` fetches both formats and writes to a new temporary directory, fsyncs files, then renames the directory to `incident-ID-vVERSION`. Refuse overwrite or symlink targets. Both outputs must refer to the same incident version; if the two GETs differ, discard temporary files and return conflict instead of publishing a mixed pair.

For a given incident version and review snapshot, repeated exports must be byte-identical. Do not add an export timestamp. Content changes or expired reviews do not rewrite historical citation snapshots in existing triage; bundle citation objects add `review_status_at_triage:"eligible"` and include review times. Fresh support answers still require current eligibility. A new triage operation captures a new review snapshot and increments the incident version.

Generate `examples/synthetic-escalation.*` only from an offline fixture with fixed clock/IDs, explicit synthetic provenance, and local review labels. The public examples contain no real operator identity or machine path. Never copy `.local` files into examples. Add an explicit scanner test over the example artifacts for configured sentinel secrets and forbidden output field names, plus semantic JSON assertions. This verifies data behavior, not implementation source text.

## 11. CLI contract and executable workflow

Install console entry point `lab = langdock_support_lab.cli:main`; `python -m langdock_support_lab` is equivalent. Global flags: `--root PATH`, `--role reader|operator|admin` (default operator), `--json`. Normal machine output is JSON on stdout with diagnostics on stderr. Never print credentials. API connection options derive from the root and configured loopback port; no remote URL flag.

| Command | Behavior |
| --- | --- |
| `lab init` | Create local credentials/database safely; no network |
| `lab serve` | Validate config; start one loopback Uvicorn process; no reload |
| `lab scenarios list` | Fetch catalog |
| `lab run --scenario ID --operation OP` | Create offline run |
| `lab live probe --operation OP --probe ID --acknowledge-live-request` | Create live run, admin only |
| `lab runs list` / `lab runs show ID` | Read observations |
| `lab incidents create --run ID` | Open incident with derived title |
| `lab incidents show ID` | Read state/history |
| `lab incidents check ID --check CHECK --result RESULT --version N` | Record structured assertion |
| `lab incidents attach ID --run RUN --version N` | Attach terminal evidence |
| `lab incidents triage ID --version N` | Compute current triage |
| `lab incidents escalate ID --reason REASON --version N` | Escalate |
| `lab incidents resolve ID --run RUN --resolution VALUE --version N` | Resolve with verified recovery |
| `lab incidents reopen ID --version N` | Reopen recurrence |
| `lab incidents export ID --out DIR` | Fetch and atomically write both formats |
| `lab support ask --question TEXT` | Ask local reviewed bot |
| `lab runbooks check` | Local eligibility validation |
| `lab runbooks review ID ...` | Perform explicit review recording described above |
| `lab smoke --json` | Exercise offline API workflow and report named gates |
| `lab live verify --acknowledge-live-request` | Run exactly the two fixed live probes and report gate |

Exit codes: 0 command succeeded, 2 CLI/input/config error, 3 recorded run failure or failed verification, 4 local authentication/authorization failure, 5 server unavailable/storage failure, 6 conflict, 7 live gate unverified because prerequisite configuration is absent. Support abstention returns 0 because abstention is expected behavior. `live verify` must not return success for a skipped gate.

### 11.1 Setup after implementation

Run from the project directory. Initial dependency installation needs package access or a prepopulated wheel cache; offline runtime does not need network access.

```sh
cd '/run/media/maheshk/New Volume/MK-solutions/langdock-support-lab'
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
lab init
lab runbooks check
```

Draft runbooks cause the initial check to fail until the implementer completes actual review. Run the relevant scenarios, inspect content, and record each review with the four explicit flags. For example, after reviewing RB-AUTH:

```sh
lab runbooks review RB-AUTH --reviewer local-implementer --days 180 \
  --source-checked --steps-exercised --secret-safe --limits-stated
```

Repeat for the other four runbooks only after their own review. This is not a blanket approval command. Tests isolate review fixtures and clocks so they do not depend on shipped review dates. Normal smoke uses actual current review eligibility.

Terminal A:

```sh
LAB_MODE=offline lab serve
```

Terminal B:

```sh
lab scenarios list
lab run --scenario success --operation agent_completion
lab run --scenario permission-denied --operation agent_completion
lab support ask --question '403 permission sharing'
lab smoke --json
python -m pytest -q -m 'not live'
```

The permission run intentionally exits 3. These are separate commands, not a fail-fast chain that stops before smoke. `lab smoke` handles expected failure outcomes as assertions and exits 0 only after all of its checks pass.

Public health probe:

```sh
curl --fail --silent http://127.0.0.1:8765/healthz
curl --silent --output /dev/null --write-out '%{http_code}\n' \
  http://127.0.0.1:8765/v1/scenarios
```

Expect health JSON and status 401 for the unauthenticated catalog. Use the CLI for authenticated requests so no token appears in process arguments or shell history. CLI implementation reads credentials internally and sends the appropriate header through httpx.

### 11.2 Smoke workflow implementation

`lab smoke` requires offline server mode and currently eligible runbooks. It must refuse live mode before creating any run. It performs these API operations and prints one named result per step on stderr plus final JSON on stdout:

1. Verify public health and 401 without local credentials.
2. Use the reader token to prove mutation is denied with 403.
3. Execute six shared scenarios for each operation and Knowledge-empty once: 13 runs total. Assert exact code/status/hint/count behavior.
4. Open an incident from the Agent permission failure, record `agent_shared:unknown`, and triage. Assert L2 suggestion with a cited eligible permission runbook.
5. Escalate with `admin_access_required`; verify ordered history and version increments.
6. Make a fresh Agent success run, attach it, rerun triage, and resolve with synthetic recovery. Assert old failure remains in history.
7. Attempt an update with an old version and assert 409 with no added event.
8. Ask one matching question and one unsupported question; verify citation content and abstention.
9. Fetch both bundle formats twice; verify identical bytes and safe fields. Write only beneath `.local/exports` when an explicit `--export` flag is provided; default smoke keeps bundle data in memory.
10. Report offline acceptance as passed only if every assertion succeeded. Report live gate as `unverified` in all offline smoke summaries.

Do not let smoke reset the database or delete existing incidents. Repeated smoke runs create new synthetic records; unique IDs avoid collisions. Include created incident/run IDs in the final summary for inspection.

## 12. Live gate and external prerequisites

Live operations require a workspace administrator, a dedicated key, sufficient account access/quota, network access, a shared test agent, and a shared synthetic Knowledge base containing a known runbook marker. Those prerequisites were not supplied for this handout. Live validation status is **unverified**.

An authorized operator must create a dedicated test agent with no Actions, external connectors, subagents, web search, or other capabilities. Its instruction should request a plain READY response to the fixed health probe. A dedicated Knowledge base should contain only synthetic runbooks with the marker `LAB-RB-AUTH`. Give the key the Agent scope and Knowledge scope described in the source register; share the test agent and give Viewer access to the synthetic Knowledge base. Verify that the key has no other Knowledge bases shared with it. A Knowledge ID is an operator setup reference only; it is not a search request parameter or a filtering guarantee.

The administrator must inspect the sharing configuration. The lab cannot prove exclusive sharing through the two allowed API operations. `LAB_LIVE_SCOPE_CONFIRMED=synthetic-only` records that prerequisite assertion; it is not a technical access boundary. The service rejects startup without it. The dedicated key and Viewer permissions provide the actual remote boundary.

Store the provider key in a new owner-private file using a local editor or secret manager. Never paste it into shell commands, documentation, HTTP requests to the lab, or Git. Set `LANGDOCK_API_KEY_FILE` to its path and `LANGDOCK_AGENT_ID` through the local process environment. These values are supplied externally; the repository contains no fake defaults. Stop the offline process before starting the live process on the same port.

With the three required environment settings already supplied:

```sh
LAB_MODE=live lab serve
```

In another terminal:

```sh
lab --role admin live verify --acknowledge-live-request
```

`live verify` submits one Agent health probe and one Knowledge marker search, sequentially, with no retry. It reports separate outcomes. Agent validation requires a valid response and, in memory only, case-insensitive trimmed text equal to READY for at least one returned message. Knowledge validation requires a positive result containing the exact marker `LAB-RB-AUTH` in at least one text field. The adapter computes the observation's nullable `probe_expectation_met` boolean before discarding bodies. Synthetic fixtures set it true on success, false on empty Knowledge, and null on errors. No raw matched text is retained.

A live gate passes only when both runs have provenance live, status succeeded, and probe_expectation_met true. Schema-valid output with a missing marker is a successful API operation but a failed live validation gate. Never manufacture a passing marker, substitute a local runbook, or retry with a different query silently.

Record only timestamp, local run IDs, operation, sanitized status, response-shape result, and expectation boolean in `.local`. Keep live validation evidence out of public examples and Git. A README may state a dated live validation result only after a real pass and must identify its limited scope. Live negative cases are not required for acceptance; never revoke permissions or induce a provider throttle to complete the matrix.

## 13. Behavioral acceptance matrix

All `A` gates run locally with temporary storage and blocked outbound sockets. `L1` is the sole external gate. MockTransport tests validate adapter behavior but do not satisfy L1. Do not test that source files contain particular text or that one function calls another by name. Assert observable API behavior, persisted state, outgoing HTTP contracts captured at the transport boundary, and exported artifacts.

| Gate | Verification | Required result |
| --- | --- | --- |
| A01 Setup/isolation | New temporary root, init twice, invalid/symlink permissions | First setup works; second refuses overwrite; no parent reads/writes |
| A02 Local auth | Missing/bad/duplicate auth; reader mutation; admin live request offline | 401/403/409 as specified; zero provider calls and zero runs |
| A03 Finite scenarios | Parameterize 12 shared scenario/operation pairs plus empty | Deterministic observations; no sockets; fixture count 13 |
| A04 HTTP contract | Capture actual outgoing requests at MockTransport | Exactly two allowed paths, correct JSON and Bearer behavior; no KB filter; no leaked local token |
| A05 Parser failure | Bad JSON, fields, shapes, nonfinite values, duplicates, excess bytes | Fixed protocol outcome; no raw payload in persisted/exported output |
| A06 Time/transport | ReadTimeout plus real async blocked test transport with short injected total budget | Bounded completion; no retry; cancellation/interruption evidence |
| A07 Retry hint | Integer/date/past/negative/duplicate/oversized header cases | Parsed bounded hint or null; no sleeping or replay |
| A08 Run durability | Reopen DB, startup recovery, simulated finalize failure | Terminal data survives; running becomes interrupted; no replay |
| A09 Incident lifecycle | Create→check→triage→escalate→attach success→triage→resolve→attach failure→reopen | Correct versions, factual history, required evidence, invalid transitions rejected |
| A10 Atomic conflict | Two changes use same version concurrently | Exactly one wins; loser gets 409; no partial event |
| A11 Review eligibility | Draft, expired, future-dated, bad hash, malformed metadata | Excluded; no fabricated review; valid local review remains available |
| A12 Grounding | Five relevant questions, ambiguous and unrelated questions | Correct verbatim sections/citations; abstention as specified |
| A13 Injection safety | Question/fixture contains instruction text and secret sentinels | No instruction execution, secret output, or remote retrieval |
| A14 Evidence privacy | Sentinels in provider body/header/exception and rejected title | No sentinel in DB values, API responses, logs, JSON or Markdown bundles |
| A15 Export stability | Same snapshot exported twice, concurrent incident update, symlink output | Byte-identical same version; no mixed pair; safe write refusal |
| A16 Input boundaries | Excess/chunked body, unknown fields/queries, invalid IDs, Origin, Host | Fixed 4xx; no provider operation; no echoed input |
| A17 Capacity | Four blocked attempts plus fifth | Fifth rejected promptly; released slots work after failures |
| A18 CLI workflow | Subprocess CLI against loopback test server and temp root | Documented exit codes; no token stdout/argv; smoke passes |
| A19 Public examples | Parse generated offline example and scan artifact content | Synthetic label, honest review, no runtime paths/IDs/provider content |
| A20 Offline release | Full non-live suite and CLI smoke with reviewed files | Passes without Langdock credentials; live remains unverified |
| L1 Live integration | Explicit authorized two-probe live verification | Both genuine requests meet shape and marker expectations; otherwise failed/unverified |

Use a fixture that denies external socket connections for all non-live tests. Permit in-process ASGI transport and explicitly bound loopback CLI test servers. Test the 25-second deadline with an injected shorter value; do not make the suite wait 25 seconds per case. Keep public configuration fixed while tests inject dependencies through Python constructors.

For A14 assert both structured fields and byte-level absence of synthetic sentinel strings. Include a canary provider key, local tokens, Authorization-looking strings, a malicious filename/URL, and an exception containing a key. A sanitizer-only unit test is insufficient; run failures through API, persistence, logs, and both bundle renderers.

For A12 prove that changing the eligible document changes the returned excerpt only after a new review, and that a stale hash excludes it. This demonstrates actual retrieval and review enforcement. Do not merely assert that a citation list is nonempty.

Mark live tests `live`; ordinary pytest execution excludes them through project configuration. `test_live_gate.py` should test gate policy with mocks locally and expose real requests only when both explicit command opt-in and live configuration are present. A skip is reported as unverified and never contributes to A20 as live evidence.

## 14. Implementation phases and dependency gates

### Phase 1 — package and safe foundation

Create packaging, dependency locks, strict models, safe errors, configuration, local credentials, SQLite schema, and application factory. Implement health, OpenAPI access, role checks, and body/origin/host limits. Verify A01, A02, and input-limit portions of A16. Do not add provider I/O until role and output boundaries exist.

### Phase 2 — shared adapter and deterministic reproduction

Implement fixed requests, bounded httpx I/O, response parsing, observation codes, MockTransport registry, and run persistence. Cover A03–A08 and A17. Verify synthetic mode remains socket-free even if provider environment variables exist. Finish this phase before adding triage so incident facts have a stable schema.

### Phase 3 — runbooks and support retrieval

Write the five original runbooks, review tooling, eligibility checks, lexical scorer, exact citations, and abstention. Exercise each relevant scenario and perform explicit synthetic review. Verify A11–A13. Review records must describe what actually happened. No fake date, approval, or reviewer is acceptable.

### Phase 4 — incidents and escalation evidence

Implement the incident state machine, structured checks, version conflicts, factual triage, canonical bundles, and atomic CLI export. Cover A09, A10, A14, and A15. Inspect one JSON and one Markdown bundle manually for usable L2 context and honest limitations.

### Phase 5 — operator workflow and public documentation

Implement CLI, smoke workflow, synthetic example generation, README, ignore rules, and full offline verification. Complete A16, A18–A20. Record actual commands and results in a local implementation report; do not assert tests ran merely because commands are documented. Inspect the public file set without reading adjacent project secrets.

### Phase 6 — optional live validation

Only an explicitly configured operator runs L1. Missing account access leaves L1 unverified while the complete offline project can pass A20. A live failure must remain visible and must not be replaced with a fixture response. No live key is needed to implement or prove the adapter's outgoing request and parser contracts locally.

Each phase ends with its behavioral gates. Failures block dependent work until repaired. Do not broaden this project into a general support platform to avoid a failed finite requirement.

## 15. README and public-release requirements

At handout-only stage, use this exact portfolio description if a README is created separately:

> Langdock Support Lab is an unbuilt TARGET portfolio project. This repository currently contains an implementation handout for a synthetic L1/L2 incident lab. It does not represent production support experience, customer incidents, or a validated live Langdock integration.

After implementation and offline acceptance, update wording only to match completed evidence:

> Langdock Support Lab is a synthetic L1/L2 support practice project built with Python, FastAPI, httpx, SQLite, Markdown, and JSON. It reproduces authentication, permission, throttling, and timeout cases locally, retrieves reviewed lab runbooks, and exports redacted escalation bundles. The examples are synthetic and do not represent production support experience. The optional Langdock adapter requires separately configured access; live validation is unverified unless a dated validation result is explicitly recorded.

The README must include purpose, architecture, Python version, exact installation/start/smoke/test commands, local role limitations, fixed scenario catalog, request examples, state transition rules, runbook review process, provenance labels, offline/live distinction, no-retry policy, source links, and live prerequisites. Explain “L1” as structured first checks and “L2” as evidence-based escalation. Explain that reviewed guidance means local synthetic review, not Langdock or employer endorsement.

Provide a compact table of implemented A-gate results and separate L1 status. Never claim customer outcomes, MTTR reduction, production incident counts, enterprise security certification, or employment experience. Label screenshots/examples synthetic if any are later added. Do not include a badge that turns skipped live checks into passing integration coverage.

Ignore `.venv/`, `.local/`, `.env`, `.env.*`, `*.sqlite3`, `*.sqlite3-*`, `*.db`, `*.log`, `__pycache__/`, `.pytest_cache/`, `.coverage*`, `htmlcov/`, `build/`, `dist/`, and `*.egg-info/`. Credential files must remain outside public paths even if a filename does not match ignore patterns. Add no `.env.example` populated with realistic-looking secrets. Document variable names in prose instead.

Public release inspection must enumerate only this project's intended files, inspect dependency/source/docs/example contents for credential material, and verify that examples derive from synthetic fixtures. Never stage the parent workspace, controller files, provider captures, state databases, or private review identities. The parent release operator owns Git actions. The implementation handout author does not commit or push.

## 16. Completion checklist and external handoff

The implementation is locally complete when A01–A20 pass, all five runbooks have honest current synthetic review records, documented CLI commands work, and the public examples can be regenerated without network access. It remains useful when L1 is unverified.

The final implementation report must list files created, commands actually executed, per-gate results, known limitations, and unresolved live prerequisites. State whether real HTTP calls occurred. Distinguish an attempted live request from a passed validation. Report public repository operations separately from application verification.

Unresolved external prerequisites are limited to: an authorized Langdock workspace/key, correct scopes, explicit agent and synthetic Knowledge sharing, an actual agent ID, a known indexed synthetic marker document, confirmed synthetic-only sharing, network/package availability for initial setup, and authorized live execution. No local architecture decision is deferred to those prerequisites.

The handout itself changes only `langdock-support-lab/HANDOUT.md`. No application implementation, test execution, account mutation, Git operation, or public push is part of this document-writing task.


## 17. Implementation reconciliation (2026-10-19)

The source implementation now exists. The original design and A01–A20/L1 requirements above remain the acceptance contract. README.md reports completed evidence and unresolved gates. A local-only implementation report records detailed execution evidence for the release operator. No production experience or live validation is claimed.

Python 3.12.13 and uv 0.11.24 were available. Network DNS and TCP socket creation were denied by the execution sandbox. Runtime and test dependencies were installed from existing cached distributions. Both requirements lock files contain exact transitive pins generated with uv pip compile. The requested pip-tools compiler was unavailable in the cache and could not be downloaded. Pip-tools regeneration is an unresolved tooling prerequisite; the implementation does not represent uv output as a completed pip-tools run. The README supplies both uv setup and pip-compatible lock installation. Setuptools is included in the development lock, and editable installation uses --no-build-isolation.

In-process HTTP acceptance and the actual CLI dispatch/smoke logic were exercised with an ignored verification harness. The sandbox denies Unix socketpair sends and therefore prevents asyncio worker-thread wakeups; that harness temporarily schedules an event-loop timer. No such adapter is present in runtime code. TCP loopback CLI/server proof remains blocked, and A18/A20 must not be declared fully passed until the ordinary documented commands run on a host that permits sockets.

The explicit official Agent nonstream response contract remains messages containing assistant role and string content. No alternate parts parser was added. Tools and live Agent capabilities remain administrator-controlled, and the dedicated no-tool agent prerequisite remains mandatory guidance.

Module responsibilities follow the table above. Observation constants live in adapters/base.py; shared strict input/output models live in models.py. Related tests are grouped by observable boundary, including test_durability.py. The fixed-clock public example generator lives in tools/generate_example.py. Its illustrative incident time is not a claimed review date; review timestamps come from the actual synthetic implementation review manifest.

Git initialization, final secret review and publishing belong to the release operator. The implementation performs no commit or push and includes only public intended files outside ignored local state.
