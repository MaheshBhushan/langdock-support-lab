# Timeout and deadline checks

```json
{
  "schema_version": 1,
  "id": "RB-TIMEOUT",
  "title": "Timeout and deadline checks",
  "category": "timeout",
  "aliases": [
    "408",
    "504",
    "524",
    "timeout",
    "deadline"
  ],
  "scope": "synthetic-lab"
}
```

## Symptoms
A timeout may be a local 25-second total deadline, a transport timeout, or a provider HTTP 408, 504 or 524 observation.

## What the evidence proves
A timeout leaves upstream completion uncertain. No HTTP response differs from provider HTTP 524. Local cancellation does not prove that Langdock stopped work or avoided billing.

## L1 checks
- Inspect duration, operation and whether an HTTP status was received.
- Record deadline_checked after inspection.
- Consider one deliberate manual follow-up. Inspect recent runs before retrying a disconnected live POST. Do not extend limits indefinitely.

## L2 escalation
Escalate repeated failures with attempt IDs, observed durations and local budget. Do not claim a provider outage or that cancellation reached Langdock.

## Verification
Attach a newer successful probe and retain the timed-out attempt. Resolution verifies a later sample only.

## Limits
The local budget is 25 seconds; transport limits are 5 seconds connect, 20 read, 5 write and 1 pool. S1 describes a 100-second nonstream provider limit with HTTP 524. Source: [S1](https://docs.langdock.com/en/developer/agents-api/agent).
