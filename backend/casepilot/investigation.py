import sqlite3
from collections.abc import Callable
from datetime import date
from time import monotonic
from typing import Annotated, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from .database import order_preview
from .reads import CustomerId, DemoReads, Intent, LineId, OrderFacts, OrderId, PolicyPassage, ReadError


READ_TIMEOUT_SECONDS = 2
RUN_TIMEOUT_SECONDS = 20
MAX_READ_ATTEMPTS = 6
CaseId = Annotated[str, StringConstraints(pattern=r"^CP-[0-9]{4}(-[A-Z])?$")]
EvidenceStatus = Literal["available", "missing", "conflicting", "not_checked"]
RefundRemedy = Literal["full_refund", "partial_refund"]
Remedy = Literal["full_refund", "partial_refund", "replacement", "delay_update"]
CaseState = Literal["investigating", "awaiting_information", "awaiting_review", "escalated"]
T = TypeVar("T")


class CaseSummary(BaseModel):
    case_id: CaseId
    scenario_id: str
    title: str


class CaseInput(CaseSummary):
    model_config = ConfigDict(strict=True)

    customer_id: CustomerId
    request: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    order_id: OrderId | None
    line_id: LineId | None = None
    intent: Intent
    initial_refund_cents: Annotated[int, Field(gt=0)] | None = None


class Fact(BaseModel):
    label: str
    value: str


class OrderPreview(BaseModel):
    order_id: OrderId
    version: int
    paid_cents: int
    currency: Literal["USD"]
    facts: list[Fact]


class PolicyVersion(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    source_id: str
    version: int


class ReplayCandidate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    remedy: RefundRemedy
    amount_cents: int = Field(gt=0)
    currency: Literal["USD"]
    citations: list[PolicyVersion] = Field(min_length=1, max_length=4)


class ProposalPreview(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    case_id: CaseId
    customer_id: CustomerId
    order_id: OrderId
    line_id: LineId | None
    revision: Annotated[int, Field(gt=0)] = 1
    remedy: Remedy
    amount_cents: Annotated[int, Field(gt=0)] | None = None
    currency: Literal["USD"] | None = None
    quantity: Annotated[int, Field(gt=0)] | None = None
    draft: Annotated[str, StringConstraints(min_length=1, max_length=4000)] | None = None
    order_version: Annotated[int, Field(gt=0)]
    policy_ids: list[str]
    policy_versions: list[PolicyVersion]
    validation_summary: str
    validation_status: Literal["valid", "invalid"] = "valid"


class HistoryEvent(BaseModel):
    at_utc: str
    title: str
    detail: str
    operation: str
    status: Literal["ok", "paused", "error"]
    attempt: int
    latency_ms: int | None


class Investigation(CaseSummary):
    mode: Literal["replay"] = "replay"
    state: CaseState = "investigating"
    request: str
    order: OrderPreview | None = None
    missing_information: list[str] = Field(default_factory=list)
    evidence: list[PolicyPassage] = Field(default_factory=list)
    evidence_status: EvidenceStatus = "not_checked"
    proposal: ProposalPreview | None = None
    draft: str | None = None
    decision_summary: str = ""
    history: list[HistoryEvent] = Field(default_factory=list)


def bounded_read(db: sqlite3.Connection, run_deadline: float, operation: Callable[[], T]) -> T:
    deadline = min(run_deadline, monotonic() + READ_TIMEOUT_SECONDS)
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ReadError("timeout", "The read budget was exhausted.")
    # SQLite checks the deadline while scanning and bounds its wait for a lock.
    db.execute(f"PRAGMA busy_timeout = {int(remaining * 1000)}")
    db.set_progress_handler(lambda: int(monotonic() >= deadline), 100)
    try:
        result = operation()
        if monotonic() >= deadline:
            raise ReadError("timeout", "The read timed out.")
        return result
    except sqlite3.OperationalError as exc:
        error_code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
        if error_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_INTERRUPT}:
            raise ReadError("timeout", "The read timed out.") from exc
        raise ReadError("unavailable", "The read service was unavailable.") from exc
    except sqlite3.DatabaseError as exc:
        raise ReadError("unavailable", "The read service was unavailable.") from exc
    finally:
        db.set_progress_handler(None, 0)


TOOL_NAMES = {
    "order.lookup": "Order lookup",
    "line.lookup": "Line-item lookup",
    "refunds.lookup": "Refund balance lookup",
    "replacement.lookup": "Replacement availability",
    "shipment.lookup": "Shipment status lookup",
    "policies.search": "Policy retrieval",
}


class InvestigationRun:
    def __init__(self, db: sqlite3.Connection, case: CaseInput, clock_utc: str):
        self.db = db
        self.case = case
        self.clock_utc = clock_utc
        self.today = date.fromisoformat(clock_utc[:10])
        self.deadline = monotonic() + RUN_TIMEOUT_SECONDS
        self.attempts = 0
        self.result = Investigation(
            case_id=case.case_id, scenario_id=case.scenario_id, title=case.title, request=case.request,
        )

    def read(self, operation: str, call: Callable[[], T], describe: Callable[[T], str]) -> T:
        for attempt in (1, 2):
            if self.attempts >= MAX_READ_ATTEMPTS or monotonic() >= self.deadline:
                raise ReadError("timeout", "The investigation reached its read limit.")
            self.attempts += 1
            start = monotonic()
            try:
                value = bounded_read(self.db, self.deadline, call)
            except ReadError as exc:
                self.event(operation, TOOL_NAMES[operation], exc.message, "error", attempt, start)
                if exc.code != "timeout" or attempt == 2:
                    raise
            else:
                self.event(operation, TOOL_NAMES[operation], describe(value), "ok", attempt, start)
                return value
        raise AssertionError("A read attempt must produce a result or raise an error.")

    def event(self, operation, title, detail, status, attempt=1, start=None):
        self.result.history.append(HistoryEvent(
            at_utc=self.clock_utc, operation=operation, title=title, detail=detail,
            status=status, attempt=attempt, latency_ms=None if start is None else round((monotonic() - start) * 1000),
        ))

    def finish(self, state: CaseState, summary: str, *missing_information: str) -> Investigation:
        self.result.state = state
        self.result.decision_summary = summary
        self.result.missing_information = list(missing_information)
        self.event("replay.decision", "Replay decision", summary, "ok" if state == "awaiting_review" else "paused")
        return self.result


def replay_refund(remedy: RefundRemedy, amount: int, proofs: list[PolicyVersion]) -> dict:
    """Generate a repeatable candidate from validated fixture reads without a model provider."""
    return {"remedy": remedy, "amount_cents": amount, "currency": "USD", "citations": proofs}


def propose_refund(run: InvestigationRun, order: OrderFacts, amount: int, eligibility: str) -> Investigation:
    line_id = run.case.line_id if run.case.intent == "damage_refund" else None
    remedy = "full_refund" if line_id is None and amount == order.paid_cents else "partial_refund"
    proofs = [PolicyVersion(source_id=passage.source_id, version=passage.version) for passage in run.result.evidence]
    try:
        candidate = ReplayCandidate.model_validate(replay_refund(remedy, amount, proofs))
    except ValidationError:
        return run.finish("escalated", "The replay returned an invalid proposal. Escalate for review.")
    if (candidate.remedy, candidate.amount_cents, candidate.citations) != (remedy, amount, proofs):
        return run.finish("escalated", "The replay proposal disagreed with the verified facts or evidence. Escalate for review.")

    scope = f"line {line_id}" if line_id else "the order"
    summary = f"{eligibility} The available balance for {scope} is ${amount // 100:,}.{amount % 100:02d} USD."
    run.result.proposal = ProposalPreview(
        case_id=run.case.case_id, customer_id=run.case.customer_id, order_id=order.order_id,
        line_id=line_id, remedy=candidate.remedy, amount_cents=candidate.amount_cents,
        currency=candidate.currency, order_version=order.version,
        policy_ids=[proof.source_id for proof in proofs], policy_versions=proofs, validation_summary=summary,
    )
    return run.finish("awaiting_review", summary)


def propose_replacement(
    run: InvestigationRun, reads: DemoReads, order: OrderFacts, line_id: str, eligibility: str,
) -> Investigation:
    available = run.read(
        "replacement.lookup", lambda: reads.replacement_quantity(order.order_id, line_id),
        lambda quantity: f"Eligible units with stock and compatible remedy history: {quantity}.",
    )
    if not available:
        return run.finish("escalated", "Replacement is unavailable because of stock or an existing remedy.")

    proofs = [PolicyVersion(source_id=passage.source_id, version=passage.version) for passage in run.result.evidence]
    run.result.proposal = ProposalPreview(
        case_id=run.case.case_id, customer_id=run.case.customer_id, order_id=order.order_id,
        line_id=line_id, remedy="replacement", quantity=1, order_version=order.version,
        policy_ids=[proof.source_id for proof in proofs], policy_versions=proofs, validation_summary=eligibility,
    )
    return run.finish("awaiting_review", eligibility)


def investigate_delay(run: InvestigationRun, reads: DemoReads, order: OrderFacts) -> Investigation:
    shipment = run.read(
        "shipment.lookup", lambda: reads.shipment(order.order_id),
        lambda result: f"Shipment status: {result.shipment_status}. Promised date: {result.promised_on or 'unavailable'}.",
    )
    if not shipment.promised_on:
        return run.finish("awaiting_information", "The promised date is missing.", "Confirm the promised shipment date.")
    days_late = (run.today - date.fromisoformat(shipment.promised_on)).days
    if days_late < 7:
        return run.finish("investigating", "The seven-day delay threshold has not been reached.")
    if shipment.shipment_status == "unknown":
        run.result.draft = "The latest shipment record has an unknown status. We have no verified delivery date."
        return run.finish(
            "awaiting_information", "The shipment needs a status check before a replacement can be considered.",
            "Confirm the original shipment status. The available record has no verified delivery estimate.",
        )
    if run.case.intent == "delay_replace":
        if shipment.shipment_status != "lost" or shipment.delivered_on is not None:
            return run.finish("escalated", "The original shipment facts do not support a replacement request.")
        if run.case.line_id is None:
            return run.finish("awaiting_information", "The replacement item has not been identified.", "Confirm the affected line item.")
        return propose_replacement(
            run, reads, order, run.case.line_id,
            f"The checked shipment is recorded as lost, {days_late} calendar days past the promised date.",
        )
    run.result.draft = f"The latest shipment record shows {shipment.shipment_status.replace('_', ' ')}."
    return run.finish("investigating", "Prepared a draft using the recorded shipment status.")


def investigate_received_order(run: InvestigationRun, reads: DemoReads, order: OrderFacts) -> Investigation:
    case = run.case
    if not order.delivered_on:
        return run.finish("awaiting_information", "Delivery is unverified.", "Confirm the delivery date.")
    age = (run.today - date.fromisoformat(order.delivered_on)).days
    if age < 0:
        return run.finish("escalated", "The recorded delivery date is in the future. Escalate for review.")
    if not order.settled:
        return run.finish("escalated", "The order payment is unsettled. Escalate for review.")

    line_id = None
    if case.intent in ("damage_refund", "damage_replace"):
        if age > 14:
            return run.finish("escalated", "The damaged item is outside the 14-day policy window.")
        if not case.line_id:
            return run.finish("awaiting_information", "The damaged item has not been identified.", "Confirm the affected line item.")
        line_id = case.line_id
        line = run.read(
            "line.lookup", lambda: reads.line(order.order_id, line_id),
            lambda result: f"Line {result.line_id} has {result.paid_cents} paid cents. Damage declaration {'complete' if result.damage_declaration_complete else 'missing'}.",
        )
        if not line.damage_declaration_complete:
            return run.finish("awaiting_information", "The damage declaration is missing.", "Request the completed damage declaration.")
        eligibility = f"The damage declaration is complete and delivery was {age} calendar days ago."
        if case.intent == "damage_replace":
            return propose_replacement(run, reads, order, line_id, eligibility)
    else:
        if age > 30 or order.used is True:
            return run.finish("escalated", "The return falls outside the unused-item or 30-day policy rule.")
        if order.used is None or not order.return_received:
            return run.finish("awaiting_information", "The return prerequisites need confirmation.", "Verify that the item is unused and the return was received.")
        eligibility = f"The unused return was received and delivery was {age} calendar days ago."

    balance = run.read(
        "refunds.lookup", lambda: reads.refunds(order.order_id, line_id),
        lambda result: f"Verified prior refunds: {result.prior_refunded_cents} cents. Pending: {result.pending_cents} cents. Available: {result.remaining_cents} cents.",
    )
    if balance.replacement_blocks_refund:
        return run.finish("escalated", "An overlapping replacement was requested or reserved. Escalate for review.")
    if balance.remaining_cents <= 0:
        return run.finish("escalated", "No refundable balance remains. Escalate for review.")
    return propose_refund(run, order, balance.remaining_cents, eligibility)


def investigate(db: sqlite3.Connection, case: CaseInput, clock_utc: str) -> Investigation:
    run = InvestigationRun(db, case, clock_utc)
    if not case.order_id:
        return run.finish("awaiting_information", "An order ID is needed to check the facts.", "Ask for the order ID.")

    reads = DemoReads(db, case.customer_id, clock_utc)
    try:
        order = run.read("order.lookup", lambda: reads.order(case.order_id), lambda result: f"Authorized order {result.order_id} v{result.version}.")
        run.result.order = OrderPreview.model_validate(order_preview(order.model_dump(mode="json"), clock_utc))
        evidence = run.read(
            "policies.search", lambda: reads.policies(case.intent, order.product, order.region),
            lambda result: f"Evidence status: {result.status}. Current approved passages: {len(result.passages)}.",
        )
        run.result.evidence = evidence.passages
        run.result.evidence_status = evidence.status
        if evidence.status == "missing":
            return run.finish("escalated", "Current approved policy evidence is missing for this order. Escalate for review.")
        if evidence.status == "conflicting":
            return run.finish("escalated", "Current approved policies conflict. Escalate for review.")
        if case.intent in ("delay", "delay_replace"):
            return investigate_delay(run, reads, order)
        return investigate_received_order(run, reads, order)
    except ReadError as exc:
        if exc.code == "not_found" and run.result.order is None:
            return run.finish("awaiting_information", exc.message, "Check the order ID and confirm it belongs to this account.")
        return run.finish("escalated", f"{exc.message} Escalate for review.")
    except (ValidationError, ValueError):
        return run.finish("escalated", "The case facts could not be validated. Escalate for review.")
