import sqlite3

from .investigation import CaseInput, PolicyVersion, ProposalPreview, investigate


REFUNDS = {"full_refund", "partial_refund"}
EDITABLE_FIELDS = {"revision", "remedy", "amount_cents", "validation_status", "validation_summary"}


def _current_proposal(
    db: sqlite3.Connection, case: CaseInput, clock_utc: str,
) -> tuple[ProposalPreview | None, str]:
    result = investigate(db, case, clock_utc)
    if result.proposal is not None:
        return result.proposal, result.decision_summary
    if case.intent == "delay" and result.order is not None and result.draft is not None:
        # The replay only produces a draft after reading a seven-day delay and the recorded shipment status.
        proofs = [PolicyVersion(source_id=passage.source_id, version=passage.version) for passage in result.evidence]
        return ProposalPreview(
            case_id=case.case_id, customer_id=case.customer_id, order_id=result.order.order_id,
            line_id=None, remedy="delay_update", draft=result.draft, order_version=result.order.version,
            policy_ids=[proof.source_id for proof in proofs], policy_versions=proofs,
            validation_summary="The draft uses the recorded shipment facts and is saved to the local outbox.",
        ), result.decision_summary
    return None, result.decision_summary


def initial_proposal(db: sqlite3.Connection, case: CaseInput, clock_utc: str) -> ProposalPreview | None:
    current, _ = _current_proposal(db, case, clock_utc)
    if (
        current is not None and current.amount_cents is not None and case.initial_refund_cents is not None
        and case.initial_refund_cents > current.amount_cents
    ):
        return current.model_copy(update={
            "amount_cents": case.initial_refund_cents, "validation_status": "invalid",
            "validation_summary": (
                "The seeded draft exceeds the current refundable balance. Edit the amount before approval."
            ),
        })
    return current


def _same_basis(current: ProposalPreview, payload: ProposalPreview) -> bool:
    return current.model_dump(exclude=EDITABLE_FIELDS) == payload.model_dump(exclude=EDITABLE_FIELDS)


def validate_proposal(
    db: sqlite3.Connection, case: CaseInput, clock_utc: str, payload: ProposalPreview,
) -> str | None:
    if payload.validation_status != "valid":
        return payload.validation_summary
    current, explanation = _current_proposal(db, case, clock_utc)
    if current is None:
        return explanation or "The case no longer qualifies for this action."
    if not _same_basis(current, payload):
        return "The scope, order facts, or policy evidence changed. Prepare a fresh proposal."
    if current.remedy in REFUNDS and current.amount_cents is not None:
        if payload.amount_cents is None or not 0 < payload.amount_cents <= current.amount_cents:
            return "The proposal exceeds the current refundable balance or has an invalid amount."
        expected = current.remedy if payload.amount_cents == current.amount_cents else "partial_refund"
        if payload.remedy != expected:
            return "The selected refund type does not match the amount."
    elif (payload.remedy, payload.amount_cents) != (current.remedy, current.amount_cents):
        return "The selected action no longer matches the verified case facts."
    return None


def edit_proposal(
    db: sqlite3.Connection, case: CaseInput, clock_utc: str, payload: ProposalPreview, amount_cents: int,
) -> ProposalPreview | None:
    if payload.remedy not in REFUNDS or type(amount_cents) is not int or amount_cents <= 0:
        return None
    current, _ = _current_proposal(db, case, clock_utc)
    if (
        current is None or current.remedy not in REFUNDS or not _same_basis(current, payload)
        or current.amount_cents is None or amount_cents > current.amount_cents
    ):
        return None
    remedy = current.remedy if amount_cents == current.amount_cents else "partial_refund"
    return current.model_copy(update={
        "revision": payload.revision + 1, "amount_cents": amount_cents, "remedy": remedy,
        "validation_summary": f"Edited refund is within the verified {current.amount_cents}-cent balance.",
    })
