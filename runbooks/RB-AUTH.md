# Authentication checks

```json
{
  "schema_version": 1,
  "id": "RB-AUTH",
  "title": "Authentication checks",
  "category": "auth",
  "aliases": [
    "401",
    "authentication",
    "credential",
    "credentials",
    "unauthorized"
  ],
  "scope": "synthetic-lab"
}
```

## Symptoms
Local 401 means local API authentication failed before a provider run. Upstream 401 is a recorded provider observation. Synthetic auth-missing and auth-invalid deliberately have the same safe classification.

## What the evidence proves
HTTP 401 identifies a rejected authentication attempt. It does not establish that a key expired or identify a missing scope.

## L1 checks
- Check backend key presence without displaying the key.
- Ask an authorized administrator to confirm the operation scope.
- Never request a pasted key. Keep local API credentials separate from provider credentials.

## L2 escalation
Escalate uncertain scope or credential configuration to the authorized administrator with the run ID. Do not attach credentials.

## Verification
A later successful probe verifies connectivity for that probe only. Preserve the original failure. Use a newer attached successful run for resolution.

## Limits
Synthetic implementation review covers fixture behavior only. No employer or Langdock endorsement applies. Sources: [S1](https://docs.langdock.com/en/developer/agents-api/agent), [S2](https://docs.langdock.com/en/developer/agents-api/agent-api-guide).
