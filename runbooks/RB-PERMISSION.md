# Permission and sharing checks

```json
{
  "schema_version": 1,
  "id": "RB-PERMISSION",
  "title": "Permission and sharing checks",
  "category": "permission",
  "aliases": [
    "403",
    "permission",
    "permissions",
    "sharing",
    "scope",
    "viewer"
  ],
  "scope": "synthetic-lab"
}
```

## Symptoms
Upstream 403 is a denial observation. A valid local role does not grant provider access. Synthetic denial models one possible failure; real Knowledge search can omit inaccessible content.

## What the evidence proves
HTTP 403 identifies a denied request. Scope and resource sharing remain hypotheses. Empty Knowledge results do not prove denial.

## L1 checks
- Ask the resource administrator to confirm required scope.
- Check Agent sharing and any subagent sharing with the workspace key.
- Check Knowledge Viewer sharing. Search spans all bases shared with the key; there is no per-request base filter.

## L2 escalation
Escalate permission changes to the resource administrator. Record a fail or unknown applicable scope or sharing check before an admin_access_required escalation. The lab cannot change permissions.

## Verification
Attach a newer successful same-operation probe and rerun triage before resolving. A nonempty Knowledge result verifies only that search sample.

## Limits
Synthetic fixture review is local and grants no remote access. A dedicated key must have only synthetic Knowledge shared. Sources: [S2](https://docs.langdock.com/en/developer/agents-api/agent-api-guide), [S3](https://docs.langdock.com/en/developer/knowledge-folder-api/sharing), [S4](https://docs.langdock.com/en/developer/knowledge-folder-api/search-knowledge-folder).
