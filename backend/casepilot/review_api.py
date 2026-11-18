import os
import re
import sqlite3
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import Body, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .investigation import CaseId, ProposalPreview
from .sandbox import SandboxError


Revision = Annotated[int, Field(ge=1, le=2_147_483_647)]
OperationId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,80}$")]
Simulation = Literal["normal", "reject_before_commit", "timeout_after_commit", "unresolved"]
ReviewState = Literal["awaiting_review", "approved", "denied", "executing", "completed", "failed", "uncertain", "invalidated"]


class ReviewCommandBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Prepare(ReviewCommandBody):
    action: Literal["prepare"]


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


ReviewCommand = Annotated[Prepare | Approve | Deny | Edit | Execute | Reconcile, Body(discriminator="action")]


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
    at_utc: str
    actor: str
    operation: str
    detail: str


class ReviewSnapshot(BaseModel):
    case_id: CaseId
    proposal: SavedProposal | None
    events: list[ReviewEvent]


CREDENTIAL_PATTERN = re.compile(r"(?i)\bbearer +[^\s]+|\b(?:gh[pousr]_|github_pat_|sk-(?:proj-)?)[A-Za-z0-9_-]{16,}")


def review_payload(command: ReviewCommandBody) -> dict:
    payload = command.model_dump()
    if isinstance(command, Deny):
        reason = command.reason
        for name in ("CASEPILOT_DEMO_TOKEN", "CASEPILOT_REVIEWER_TOKEN"):
            token = os.environ.get(name)
            if token:
                reason = reason.replace(token, "[redacted]")
        payload["reason"] = CREDENTIAL_PATTERN.sub("[redacted]", reason)[:280]
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
