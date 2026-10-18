# Throttling and retry checks

```json
{
  "schema_version": 1,
  "id": "RB-THROTTLE",
  "title": "Throttling and retry checks",
  "category": "throttle",
  "aliases": [
    "429",
    "throttle",
    "throttled",
    "throttling",
    "retry"
  ],
  "scope": "synthetic-lab"
}
```

## Symptoms
Upstream 429 records a throttled attempt. The synthetic fixture uses a seven-second hint as a teaching value.

## What the evidence proves
HTTP 429 and the bounded Retry-After hint describe this attempt. They do not establish a fixed provider quota or safe concurrency level.

## L1 checks
- Record status and the sanitized Retry-After hint, which is capped at 300 seconds.
- Wait outside the request. Avoid parallel manual retries.
- Perform at most one deliberate follow-up after judging whether it is appropriate. The lab does not retry automatically.

## L2 escalation
Escalate repeated failures with both run IDs and recorded checks. Preserve uncertainty about quota and provider availability.

## Verification
Compare one later successful probe with the original failure. Do not infer a global recovery from one sample.

## Limits
The hint and quota assumptions are synthetic. Missing or malformed hints remain unknown. Source: [S1](https://docs.langdock.com/en/developer/agents-api/agent).
