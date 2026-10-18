# Langdock Support Lab

Langdock Support Lab is a synthetic L1/L2 support practice project built with Python, FastAPI, httpx, SQLite, Markdown, and JSON. It reproduces authentication, permission, throttling, and timeout cases locally, retrieves reviewed lab runbooks, and exports redacted escalation bundles. The examples are synthetic and do not represent production support experience. The optional Langdock adapter requires separately configured access; live validation is unverified unless a dated validation result is explicitly recorded.

This is a TARGET portfolio project. L1 means structured first checks. L2 means escalation with evidence and explicit uncertainty. The service performs two fixed provider probes. It never changes remote agents, permissions, or Knowledge content.

## Setup and use

Use Linux and Python 3.12. Initial installation requires package access or a populated wheel cache. Offline runtime needs no network beyond the local CLI connection.

```sh
uv venv --python 3.12 --seed .venv
. .venv/bin/activate
uv pip install -r requirements-dev.lock
uv pip install --no-deps --no-build-isolation -e .
lab init
lab runbooks check
lab serve
```

`python3.12 -m venv .venv`, `python -m pip install -r requirements-dev.lock`, and `python -m pip install --no-deps --no-build-isolation -e .` are equivalent installation steps. Both lock files contain exact transitive pins, regenerated and verified with pip-tools under Python 3.12. To regenerate, install pip-tools as separate maintenance tooling, then run `pip-compile --strip-extras --no-header --no-emit-index-url --output-file requirements.lock requirements.in` and `pip-compile --allow-unsafe --strip-extras --no-header --no-emit-index-url --output-file requirements-dev.lock requirements-dev.in`. The development lock includes setuptools for the documented editable installation.

`lab init` refuses existing credentials. It creates owner-private `.local` state and three random role tokens. It never prints them. Run commands from this directory or pass `lab --root /absolute/project/path ...`. Root discovery never searches parents. An explicit `--credentials-file` permits another owner-private credential file. No command loads `.env`.

In another terminal:

```sh
lab scenarios list
lab run --scenario success --operation agent_completion
lab run --scenario permission-denied --operation agent_completion
lab support ask --question '403 permission sharing'
lab smoke --json
python -m pytest -q -m 'not live'
```

The permission exercise intentionally exits 3. Run these as separate commands. Smoke asserts expected failures and returns 0 only when every workflow assertion succeeds. It creates fresh records and never resets existing data. `lab smoke --json --export` also writes bundles beneath `.local/exports`; the default keeps them in memory.

```sh
curl --fail --silent http://127.0.0.1:8765/healthz
curl --silent --output /dev/null --write-out '%{http_code}\n' http://127.0.0.1:8765/v1/scenarios
```

Health returns only `{"status":"ok"}`. The unauthenticated catalog returns 401. Use the CLI for authenticated requests so tokens stay out of command arguments and shell history. Authenticated `/openapi.json` describes the HTTP API and Bearer scheme. `/docs` and `/redoc` return 404. There is no frontend.

## Offline exercises and HTTP requests

| Scenario | Operations | Observation |
| --- | --- | --- |
| success | Agent, Knowledge | OK, positive count |
| auth-missing | Both | UPSTREAM_AUTH, HTTP 401 |
| auth-invalid | Both | UPSTREAM_AUTH, HTTP 401 |
| permission-denied | Both | UPSTREAM_PERMISSION, HTTP 403 |
| throttled | Both | UPSTREAM_THROTTLED, HTTP 429, hint 7 seconds |
| timeout | Both | UPSTREAM_TIMEOUT, no HTTP status |
| knowledge-empty | Knowledge | OK_EMPTY, successful operation, expectation false |

These 13 combinations use immutable fixtures and a fresh MockTransport. They build the same HTTP requests and use the same parser as the live adapter. A synthetic Knowledge 403 models denial; actual Knowledge search may simply omit inaccessible content. Empty results never establish denial.

`POST /v1/runs` accepts this offline body:

```json
{"mode":"offline","operation":"agent_completion","scenario_id":"permission-denied"}
```

A live request accepts only a fixed probe and explicit acknowledgment:

```json
{"mode":"live","operation":"knowledge_search","probe_id":"runbook-auth","acknowledge_live_request":true}
```

No request accepts provider keys, agent IDs, URLs, arbitrary prompts, headers, or Knowledge filters. `health-text` applies only to `agent_completion`; `runbook-auth` applies only to `knowledge_search`. Request mode must match server mode.

An accepted run returns HTTP 201 even if the recorded attempt failed. Inspect `status`, `observation.code`, `upstream_status`, and the shape/count/expectation flags. Raw provider output never appears. Run provenance is `synthetic` or `live`. A gate without qualifying evidence is `unverified`.

## Incident workflow

Start with the failed run ID from `lab run`:

```sh
lab incidents create --run RUN_UUID
lab incidents check INCIDENT_UUID --check agent_shared --result unknown --version 1
lab incidents triage INCIDENT_UUID --version 2
lab incidents escalate INCIDENT_UUID --reason admin_access_required --version 3
lab incidents show INCIDENT_UUID
lab runs list
lab runs show RUN_UUID
lab incidents export INCIDENT_UUID --out .local/exports
```

Substitute actual UUIDs and current versions. Checks record operator assertions; the bot never marks checks performed. Allowed results are `pass`, `fail`, and `unknown`. Runbook guidance explains applicable scope, sharing, deadline, and retry checks.

The state path is `open → triaged → escalated → resolved`. Triage can remain escalated. Every mutation increments the version once and appends one event atomically. A stale version returns 409 without adding evidence. Attaching a run or adding a check clears current triage; rerun triage before escalation or resolution. Evidence remains in history.

Escalation requires triage plus performed checks, except protocol/network/interrupted cases. `admin_access_required` needs an unknown or failed applicable scope/sharing assertion. `repeated_failure` needs two failed runs with the same code. Other reasons are `contract_mismatch`, `network_unknown`, and `insufficient_evidence`.

To resolve, create a fresh success with the same mode and operation, attach it using `lab incidents attach INCIDENT_UUID --run RUN_UUID --version N`, rerun triage, then run `lab incidents resolve INCIDENT_UUID --run RUN_UUID --resolution synthetic_recovery_verified --version N`. Live resolution uses `live_recovery_observed`. Recovery must postdate the most recent failure and have `OK` with a positive count; Knowledge `OK_EMPTY` is insufficient. Resolution verifies a later probe and does not prove a cause was fixed.

Attach a failed run created after resolution, then use `lab incidents reopen INCIDENT_UUID --version N` to record recurrence. Cross-operation or cross-mode attachments are rejected. Resolved incidents accept only new evidence and qualifying reopen.

JSON and Markdown exports come from a consistent database snapshot. Custom titles stay local; exports use derived titles. Repeated exports of the same version are byte-identical. CLI export rejects symlinks, existing targets, and a pair fetched across different incident versions. It writes and fsyncs both files before publishing a new directory with Linux atomic no-replace rename.

## Reviewed guidance

The bot ranks local Markdown lexically and quotes complete evidence and L1 sections verbatim. Citations include exact excerpts, SHA-256, section IDs and review times. Questions are not saved. Ambiguous, unsupported, or ineligible guidance produces abstention. Provider search results and Agent answers never become reviewed guidance.

All five shipped review records represent a synthetic implementation review by `local-implementer`. The implementer inspected each document against the source register and exercised matching synthetic scenarios. The records claim no human employer, production, or Langdock approval. Reviews expire after 180 days. Editing a file immediately invalidates its hash.

After inspecting changed text, checking its official-source claims, and exercising its matching scenario, record an actual new review:

```sh
lab runbooks review RB-AUTH --reviewer YOUR_LOCAL_REVIEWER_ID --days 180 \
  --source-checked --steps-exercised --secret-safe --limits-stated
lab runbooks check
```

Review each runbook separately. Format validation cannot confer review. Historical triage preserves its eligible-at-triage citation snapshot even after expiry; new support answers and triage use current eligibility. Public [synthetic examples](examples/synthetic-escalation.json) use fixed illustrative IDs/time. Regenerate them with `python tools/generate_example.py` while the shipped review is eligible at the fixture date. No runtime evidence is copied into examples.

## Security and live prerequisites

Local roles are `reader`, `operator`, and `admin`. Readers inspect data and ask the bot. Operators create synthetic runs and mutate incidents. Only admins create live runs in live mode. `lab --role reader ...` selects a local role. The OS owner can read every token; these roles demonstrate application authorization and do not isolate hostile users under one OS account. All roles see the same lab data.

The server binds only `127.0.0.1`. `LAB_PORT` defaults to 8765 and permits 1024–65535. `LAB_HOST` must remain `127.0.0.1`. Requests with Origin are denied. Host must match the configured loopback port. The CLI has no remote-origin option, does not follow redirects, and does not trust environment proxies. Authentication precedes parsing. Unknown fields/queries, duplicate JSON keys, nonfinite numbers, GET bodies and JSON bodies above 16 KiB are rejected with fixed errors.

Provider responses are bounded to 1 MiB decoded bytes. Attempts have connect/read/write/pool limits of 5/20/5/1 seconds and a 25-second total deadline. Four attempts may run concurrently; a fifth is rejected immediately. There are no automatic retries, sleeps, replay after restart, or idempotency keys. A timeout or disconnect leaves remote completion and billing uncertain. Inspect recent runs before deliberately repeating a live POST.

Persistence and exports omit provider bodies, Agent text, Knowledge chunks, links, credentials, arbitrary headers, exception messages, configuration and custom titles. Free-text checks reject configured secrets and common credential patterns. Omission and narrow inputs provide the primary privacy boundary; pattern detection cannot recognize every unknown secret. Logs contain fixed categories and local request metadata. Runtime state is private and ignored. Stop the server before manually deleting `.local` to reset the lab.

For a live experiment, an authorized administrator must provide:

- A dedicated workspace API key with Assistant API and `KNOWLEDGE_FOLDER_API` scopes.
- Explicit sharing of a dedicated test agent. Real agents can execute configured tools. Use an agent with no Actions, connectors, subagents, web search or other capabilities. Instruct it to return plain READY to the fixed health probe.
- Viewer sharing of a dedicated synthetic Knowledge base with an indexed `LAB-RB-AUTH` marker. Verify that no other Knowledge bases are shared with this key. Search spans **all** bases shared with the key and accepts no base filter.
- A new owner-private regular file holding the provider key, plus the actual agent ID and network/quota access.

Set backend process variables `LANGDOCK_API_KEY_FILE` and `LANGDOCK_AGENT_ID`. Set `LAB_LIVE_SCOPE_CONFIRMED=synthetic-only` after inspecting sharing. That assertion is not a technical isolation boundary; the dedicated key and remote sharing provide the boundary. Do not place secrets in flags, API bodies, browser code or Git. Offline mode does not read the provider key file even when its variable exists.

After stopping the offline server and supplying these variables through a secret manager or protected process environment:

```sh
LAB_MODE=live lab serve
lab --role admin live verify --acknowledge-live-request
```

Live startup fails closed if prerequisites are absent. Verification makes exactly two sequential fixed probes without retries. Both must have `live` provenance, valid success shapes and matching READY/marker expectations. Valid output without the marker fails the live gate. Skips and missing configuration return `unverified` with exit 7. No live provider request was made during implementation.

CLI exits: 0 success or expected abstention; 2 input/config; 3 recorded run failure or failed verification; 4 local authorization; 5 server/storage; 6 conflict; 7 live prerequisites missing.

## Architecture and verification status

The path is CLI → loopback FastAPI → service → fixed adapter → sanitized observation → SQLite. SQLite connections and transactions run in worker threads. No transaction spans provider I/O. Startup changes abandoned running attempts to interrupted and never replays them. The bot reads five small review snapshots directly. There is no model dependency, queue, vector store or frontend.

[HANDOUT.md](HANDOUT.md) retains the full detailed contracts. [CHANGELOG.md](CHANGELOG.md) records implementation changes. The local implementation report records detailed execution evidence and blockers; it is excluded from public distribution.

| Gates | Current evidence |
| --- | --- |
| A01–A17, A19 | Passed; parser, auth, state, review, privacy, capacity and export checks in the 107-test offline suite |
| A18 | Passed; real loopback subprocess CLI/server test and standalone TCP CLI smoke |
| A20 | Passed; 107 tests, no skips, standard CLI smoke, and verified pip-tools locks |
| L1 | Unverified; no configured or attempted live provider access |

Independent release verification ran `python -m pytest -q -m 'not live'` (107 passed), `lab smoke --json` against the actual loopback server (all six workflow groups passed), and `python -m pip check` (no broken requirements). No sandbox adapters or temporary verification plugins were required. Live Langdock access was not exercised.

## Official source register

| ID | Source | Supported contract |
| --- | --- | --- |
| S1 | [Agent completions](https://docs.langdock.com/en/developer/agents-api/agent) | Fixed endpoint, UIMessage request parts, explicit nonstream `messages[].content`, timeout |
| S2 | [Sharing Agents](https://docs.langdock.com/en/developer/agents-api/agent-api-guide) | Assistant API scope, explicit sharing, backend key use |
| S3 | [Sharing Knowledge](https://docs.langdock.com/en/developer/knowledge-folder-api/sharing) | Viewer search access and sharing |
| S4 | [Knowledge search](https://docs.langdock.com/en/developer/knowledge-folder-api/search-knowledge-folder) | Query-only request, all shared bases, result schema and legitimate empty results |
| S5 | [Documentation index](https://docs.langdock.com/llms.txt) | Official reference discovery |

The adapter follows S1's explicit nonstream string-content contract. It rejects alternate parts/choices responses as protocol errors. Synthetic error payloads and timings describe this lab alone.
