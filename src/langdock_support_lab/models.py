from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator, field_validator

Operation = Literal["agent_completion", "knowledge_search"]
CheckID = Literal["backend_key_present", "required_scope_confirmed", "agent_shared", "subagents_shared", "knowledge_viewer_shared", "request_contract_checked", "retry_window_observed", "deadline_checked"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Offline(Strict):
    mode: Literal["offline"]
    operation: Operation
    scenario_id: str


class Live(Strict):
    mode: Literal["live"]
    operation: Operation
    probe_id: Literal["health-text", "runbook-auth"]
    acknowledge_live_request: Literal[True]

    @field_validator("acknowledge_live_request", mode="before")
    @classmethod
    def acknowledgment(cls, value):
        if value is not True:
            raise ValueError("acknowledgment")
        return value

    @model_validator(mode="after")
    def probe(self):
        if (self.operation == "agent_completion") != (self.probe_id == "health-text"):
            raise ValueError("probe")
        return self


RunCreate = Annotated[Offline | Live, Field(discriminator="mode")]
ID = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")]


class IncidentCreate(Strict):
    run_id: ID
    title: Annotated[str, StringConstraints(min_length=1, max_length=120)] | None = None


class Version(Strict):
    expected_version: int = Field(ge=1)


class Check(Version):
    type: Literal["check"]
    check_id: CheckID
    result: Literal["pass", "fail", "unknown"]


class Attach(Version):
    type: Literal["attach_run"]
    run_id: ID


class Escalate(Version):
    type: Literal["escalate"]
    reason: Literal["admin_access_required", "repeated_failure", "contract_mismatch", "network_unknown", "insufficient_evidence"]


class Resolve(Version):
    type: Literal["resolve"]
    resolution: Literal["synthetic_recovery_verified", "live_recovery_observed"]
    verification_run_id: ID


class Reopen(Version):
    type: Literal["reopen"]
    reason: Literal["recurrence"]


EventCreate = Annotated[Check | Attach | Escalate | Resolve | Reopen, Field(discriminator="type")]


class Question(Strict):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
    incident_id: ID | None = None


class Observation(Strict):
    code: Literal['OK', 'OK_EMPTY', 'UPSTREAM_AUTH', 'UPSTREAM_PERMISSION', 'UPSTREAM_NOT_FOUND', 'UPSTREAM_THROTTLED', 'UPSTREAM_TIMEOUT', 'UPSTREAM_UNAVAILABLE', 'UPSTREAM_REJECTED', 'UPSTREAM_PROTOCOL', 'UPSTREAM_NETWORK', 'RUN_INTERRUPTED']
    upstream_status: int | None
    duration_ms: int = Field(ge=0)
    retryable: bool
    retry_after_seconds: int | None = Field(ge=0, le=300)
    attempt_count: Literal[1]
    response_shape_valid: bool | None
    result_count: int | None = Field(ge=0, le=1000)
    nonempty_text: bool | None
    probe_expectation_met: bool | None
    message: str

    @model_validator(mode='after')
    def fixed_message(self):
        from .adapters.base import MESSAGES
        if self.message != MESSAGES[self.code]:
            raise ValueError('observation message')
        return self


class RunRecord(Strict):
    id: ID
    created_at: str
    finished_at: str | None
    mode: Literal['offline', 'live']
    provenance: Literal['synthetic', 'live']
    operation: Operation
    scenario_id: str | None
    probe_id: Literal['health-text', 'runbook-auth']
    status: Literal['running', 'succeeded', 'failed', 'interrupted']
    observation: Observation | None

    @model_validator(mode='after')
    def lifecycle(self):
        if self.provenance != ('synthetic' if self.mode == 'offline' else 'live'):
            raise ValueError('provenance')
        if self.status == 'running':
            if self.finished_at is not None or self.observation is not None:
                raise ValueError('running evidence')
        elif self.finished_at is None or self.observation is None:
            raise ValueError('terminal evidence')
        return self


class Citation(Strict):
    id: str
    runbook_id: Literal['RB-AUTH', 'RB-PERMISSION', 'RB-THROTTLE', 'RB-TIMEOUT', 'RB-SUCCESS']
    title: str
    section: Literal['evidence', 'l1', 'l2']
    sha256: Annotated[str, StringConstraints(pattern=r'^[a-f0-9]{64}$')]
    review_kind: Literal['synthetic-lab-review']
    reviewed_at: str
    review_due_at: str
    excerpt: str


class TriageRecord(Strict):
    level: Literal['L1', 'L2']
    observed_codes: list[str]
    facts: list[str]
    hypotheses: list[str]
    suggested_checks: list[CheckID]
    recommended_action: Literal['check_configuration', 'wait_then_manual_retry', 'inspect_deadline', 'escalate', 'verify_recovery']
    citations: list[Citation]
    evidence_run_ids: list[ID]
    limitations: list[str]


class EventRecord(Strict):
    id: ID
    sequence: int = Field(ge=1)
    created_at: str
    actor_role: Literal['reader', 'operator', 'admin']
    type: Literal['created', 'check', 'attach_run', 'triage', 'escalate', 'resolve', 'reopen']
    payload: dict

    @model_validator(mode='after')
    def structured_payload(self):
        from pydantic import TypeAdapter
        if "expected_version" in self.payload or "type" in self.payload:
            raise ValueError("event payload")
        if self.type == 'created':
            if set(self.payload) != {'run_id'}:
                raise ValueError('creation payload')
            IncidentCreate.model_validate(self.payload)
        elif self.type == 'triage':
            if set(self.payload) != {'triage'}:
                raise ValueError('triage payload')
            TriageRecord.model_validate(self.payload['triage'])
        else:
            TypeAdapter(EventCreate).validate_python({'expected_version': 1, 'type': self.type, **self.payload})
        return self


class IncidentRecord(Strict):
    id: ID
    created_at: str
    updated_at: str
    title: str
    state: Literal['open', 'triaged', 'escalated', 'resolved']
    version: int = Field(ge=1)
    initial_run_id: ID
    run_ids: list[ID]
    triage: TriageRecord | None
    events: list[EventRecord]


class AnswerPart(Strict):
    text: str
    citation_id: str


class SupportAnswer(Strict):
    status: Literal['answered', 'abstained']
    reason: Literal['NO_MATCH', 'AMBIGUOUS', 'NO_ELIGIBLE_RUNBOOKS'] | None
    parts: list[AnswerPart]
    citations: list[Citation]
    provenance: Literal['reviewed-local-runbooks']
    message: str | None
