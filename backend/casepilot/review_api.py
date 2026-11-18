import sqlite3
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import Body, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .investigation import CaseId, CaseState, EvidenceStatus, HistoryEvent, PolicyVersion, ProposalPreview
from .sandbox import SandboxError, redact_credentials


Revision = Annotated[int, Field(ge=1, le=2_147_483_647)]
OperationId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,80}$")]
Simulation = Literal["normal", "reject_before_commit", "timeout_after_commit", "unresolved"]
ReviewState = Literal["awaiting_review", "approved", "denied", "executing", "completed", "failed", "uncertain", "invalidated"]


class ReviewCommandBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Prepare(ReviewCommandBody):
    action: Literal["prepare"]


class RecordRun(ReviewCommandBody):
    action: Literal["record_run"]


class Approve(ReviewCommandBody):
    action: Literal["approve"]
    revision: Revision


class Deny(ReviewCommandBody):
    action: Literal["deny"]
    revision: Revision
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=280)]


class Edit(ReviewCommandBody):
    action: Literal["edit"]
    revision: Revision
    amount_cents: Annotated[int, Field(gt=0, le=1_000_000_000)]


class Execute(ReviewCommandBody):
    action: Literal["execute"]
    revision: Revision
    idempotency_key: OperationId
    simulation: Simulation = "normal"


class Reconcile(ReviewCommandBody):
    action: Literal["reconcile"]
    execution_id: OperationId


ReviewCommand = Annotated[Prepare | RecordRun | Approve | Deny | Edit | Execute | Reconcile, Body(discriminator="action")]


class ReviewDecision(BaseModel):
    decision: Literal["approved", "denied"]
    reviewer_id: str
    reason: str | None = None
    at_utc: str


class SandboxReceipt(BaseModel):
    execution_id: str
    record_id: str
    remedy: str
    order_id: str
    line_id: str | None = None
    amount_cents: int | None = None
    quantity: int | None = None
    currency: Literal["USD"] | None = None
    verified_at: str


class SandboxExecution(BaseModel):
    execution_id: str
    status: Literal["executing", "completed", "failed", "uncertain"]
    message: str
    receipt: SandboxReceipt | None


class SavedProposal(BaseModel):
    revision: Revision
    state: ReviewState
    payload: ProposalPreview
    review: ReviewDecision | None
    execution: SandboxExecution | None
    idempotency_key: str


class ReviewEvent(BaseModel):
    event_id: int
    at_utc: str
    actor: str
    operation: str
    detail: str
    revision: Revision
    before_state: ReviewState | None
    after_state: ReviewState
    execution_id: str | None
    idempotency_identity: str | None


class SavedRun(BaseModel):
    run_id: str
    case_id: CaseId
    scenario_id: str
    actor: str
    at_utc: str
    fixture_version: str
    mode: Literal["replay"]
    order_version: int | None
    evidence: list[PolicyVersion]
    evidence_status: EvidenceStatus
    decision_summary: str
    state: CaseState
    tools: list[HistoryEvent]
    latency_ms: Annotated[int, Field(ge=0)]
    provider_calls: Literal[0]
    proposal_revision: Revision | None


class ReviewSnapshot(BaseModel):
    case_id: CaseId
    scenario_id: str
    proposal: SavedProposal | None
    events: list[ReviewEvent]
    runs: list[SavedRun]


def review_payload(command: ReviewCommandBody) -> dict:
    payload = command.model_dump()
    if isinstance(command, Deny):
        payload["reason"] = redact_credentials(command.reason)[:280]
    return payload


def review_response(operation: Callable[[], dict]) -> dict:
    try:
        return operation()
    except SandboxError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
    except (sqlite3.DatabaseError, ValueError) as exc:
        raise HTTPException(503, {
            "code": "sandbox_unavailable",
            "message": "The local sandbox could not confirm this request. Refresh to check its saved state before retrying.",
        }) from exc
