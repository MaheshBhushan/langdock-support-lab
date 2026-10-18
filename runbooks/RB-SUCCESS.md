# Success and recovery checks

```json
{
  "schema_version": 1,
  "id": "RB-SUCCESS",
  "title": "Success and recovery checks",
  "category": "success",
  "aliases": [
    "success",
    "recovery",
    "ready",
    "empty"
  ],
  "scope": "synthetic-lab"
}
```

## Symptoms
Agent success contains valid assistant text. Knowledge success may contain nonempty results or a valid empty array.

## What the evidence proves
A successful sample is evidence for that fixed probe only. Empty Knowledge results do not establish denial or meaningful marker retrieval.

## L1 checks
- Inspect response-shape and expectation flags without collecting raw text.
- For live verification require READY from Agent and the known indexed LAB-RB-AUTH synthetic marker from Knowledge.
- Confirm positive Knowledge result count for recovery evidence.

## L2 escalation
Escalate missing expected markers or uncertain indexing. Never substitute local guidance for an unsuccessful live marker search.

## Verification
Resolution needs a newer attached successful run after the most recent failure, then fresh triage. Offline resolution is synthetic_recovery_verified; live resolution is live_recovery_observed. Neither proves the cause was fixed.

## Limits
Synthetic examples represent practice only. Local synthetic review is not provider approval or production experience. Sources: [S1](https://docs.langdock.com/en/developer/agents-api/agent), [S4](https://docs.langdock.com/en/developer/knowledge-folder-api/search-knowledge-folder).
