import json
import os
import re
import sqlite3
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import uuid4

from .database import load_case, load_metadata, open_read_database, open_write_database
from .investigation import CaseInput, Investigation, ProposalPreview, investigate
from .reads import ReadError
from .sandbox_candidates import edit_proposal, initial_proposal, validate_proposal


REFUNDS = {"full_refund", "partial_refund"}
STARTABLE = {"denied", "failed", "invalidated"}
CREDENTIAL_PATTERN = re.compile(
    r"(?i)\bbearer +[^\s]+|\b(?:gh[pousr]_|github_pat_|sk-(?:proj-)?)[A-Za-z0-9_-]{16,}"
)


class SandboxError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def _load_scoped_case(db, case_id, customer_id):
    try:
        record = load_case(db, customer_id, case_id)
        if record is not None:
            return CaseInput.model_validate(record)
    except ValueError as error:
        raise SandboxError(502, "invalid_case", "Verify or reset the local case fixture.") from error
    raise SandboxError(404, "not_found", "The case is unavailable for this account.")


def _proposal(db, case_id, revision=None):
    if revision is None:
        return db.execute(
            "SELECT * FROM sandbox_proposals WHERE case_id = ? ORDER BY revision DESC LIMIT 1", (case_id,),
        ).fetchone()
    return db.execute(
        "SELECT * FROM sandbox_proposals WHERE case_id = ? AND revision = ?", (case_id, revision),
    ).fetchone()


def _require_current(db, case_id, revision):
    current = _proposal(db, case_id)
    if current is None or current["revision"] != revision:
        raise SandboxError(409, "stale_revision", "Refresh the case to see the current proposal revision.")
    return current


def _review(db, proposal):
    return db.execute(
        "SELECT decision, reviewer_id, reason, at_utc FROM sandbox_reviews WHERE case_id = ? AND revision = ?",
        (proposal["case_id"], proposal["revision"]),
    ).fetchone()


def _event(db, actor, clock, proposal, operation, detail, after_state, execution_id=None):
    db.execute(
        """
        INSERT INTO sandbox_events (case_id, revision, actor, operation, detail, at_utc, before_state, after_state, execution_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (proposal["case_id"], proposal["revision"], actor, operation, detail, clock,
         proposal["state"], after_state, execution_id),
    )


def _transition(db, actor, clock, proposal, state, operation, detail, execution_id=None):
    db.execute(
        "UPDATE sandbox_proposals SET state = ? WHERE case_id = ? AND revision = ?",
        (state, proposal["case_id"], proposal["revision"]),
    )
    _event(db, actor, clock, proposal, operation, detail, state, execution_id)


def redact_credentials(text: str) -> str:
    for name in ("CASEPILOT_DEMO_TOKEN", "CASEPILOT_REVIEWER_TOKEN"):
        token = os.environ.get(name)
        if token:
            text = text.replace(token, "[redacted]")
    return CREDENTIAL_PATTERN.sub("[redacted]", text)


def _timed_investigation(db, case, clock) -> tuple[Investigation, int]:
    started_at = monotonic()
    result = investigate(db, case, clock)
    return result, round((monotonic() - started_at) * 1000)


def _save_run(db, case, actor, metadata, result, latency_ms, revision=None):
    run_id = uuid4().hex
    # Persist only the structured audit projection. Request text, drafts and policy excerpts remain out of it.
    snapshot = {
        "run_id": run_id,
        "case_id": case.case_id,
        "scenario_id": case.scenario_id,
        "actor": actor,
        "at_utc": metadata["clock_utc"],
        "fixture_version": metadata["fixture_version"],
        "mode": "replay",
        "order_version": result.order.version if result.order else None,
        "evidence": [
            {"source_id": redact_credentials(passage.source_id), "version": passage.version}
            for passage in result.evidence
        ],
        "evidence_status": result.evidence_status,
        "decision_summary": redact_credentials(result.decision_summary),
        "state": result.state,
        "tools": [
            {**event.model_dump(), "title": redact_credentials(event.title), "detail": redact_credentials(event.detail)}
            for event in result.history
        ],
        "latency_ms": latency_ms,
        "provider_calls": 0,
        "proposal_revision": revision,
    }
    db.execute(
        "INSERT INTO sandbox_runs (run_id, case_id, snapshot) VALUES (?, ?, ?)",
        (run_id, case.case_id, json.dumps(snapshot)),
    )


def _save_proposal(db, actor, clock, candidate, revision, operation):
    payload = candidate.model_copy(update={"revision": revision})
    db.execute(
        "INSERT INTO sandbox_proposals VALUES (?, ?, ?, ?, ?)",
        (payload.case_id, revision, payload.model_dump_json(), "awaiting_review", uuid4().hex),
    )
    detail = f"Revision {revision}, order v{payload.order_version}. {payload.validation_summary}"
    _event(db, actor, clock, {"case_id": payload.case_id, "revision": revision, "state": None},
           operation, detail, "awaiting_review")
    return revision


def _matches_result(db, execution_id, payload):
    if payload.remedy in REFUNDS:
        query = "SELECT order_id, line_id, amount_cents FROM refund_ledger WHERE execution_id = ?"
        expected = (payload.order_id, payload.line_id, payload.amount_cents)
    elif payload.remedy == "replacement":
        query = "SELECT order_id, line_id, quantity FROM replacement_requests WHERE execution_id = ?"
        expected = (payload.order_id, payload.line_id, payload.quantity)
    elif payload.remedy == "delay_update":
        query = "SELECT order_id, draft FROM sandbox_outbox WHERE execution_id = ?"
        expected = (payload.order_id, payload.draft)
    else:
        return False
    record = db.execute(query, (execution_id,)).fetchone()
    return record is not None and tuple(record) == expected


def _execution_snapshot(db, operation, payload):
    if operation is None:
        return None
    execution_id = operation["execution_id"]
    status = operation["status"]
    message = operation["message"]
    receipt = None
    if status == "completed":
        verified_at = operation["verified_at"]
        if verified_at and _matches_result(db, execution_id, payload):
            receipt = {
                "execution_id": execution_id, "record_id": execution_id, "remedy": payload.remedy,
                "order_id": payload.order_id, "line_id": payload.line_id, "amount_cents": payload.amount_cents,
                "quantity": payload.quantity, "currency": payload.currency, "verified_at": verified_at,
            }
        else:
            status = "uncertain"
            message = "The saved result could not be verified. Reconcile this operation."
    return {"execution_id": execution_id, "status": status, "message": message, "receipt": receipt}


def _snapshot(db, case, revision=None):
    case_id = case.case_id
    current = _proposal(db, case_id, revision)
    saved = None
    if current is not None:
        payload = ProposalPreview.model_validate_json(current["payload"])
        review = _review(db, current)
        operation = db.execute(
            "SELECT * FROM sandbox_executions WHERE case_id = ? AND revision = ?", (case_id, current["revision"]),
        ).fetchone()
        execution = _execution_snapshot(db, operation, payload)
        saved = {
            "revision": current["revision"], "state": execution["status"] if execution else current["state"],
            "payload": payload.model_dump(mode="json"), "review": dict(review) if review else None,
            "execution": execution, "idempotency_key": current["idempotency_key"],
        }
    events = db.execute(
        """
        SELECT e.event_id, e.at_utc, e.actor, e.operation, e.detail, e.revision, e.before_state,
            e.after_state, e.execution_id, x.idempotency_key
        FROM sandbox_events e
        LEFT JOIN sandbox_executions x ON x.execution_id = e.execution_id
        WHERE e.case_id = ?
        ORDER BY e.event_id
        """, (case_id,),
    )
    safe_events = []
    for event in events:
        details = dict(event)
        key = details.pop("idempotency_key")
        details["idempotency_identity"] = sha256(key.encode()).hexdigest()[:12] if key else None
        safe_events.append(details)
    runs = db.execute(
        "SELECT snapshot FROM sandbox_runs WHERE case_id = ? ORDER BY run_number", (case_id,),
    )
    return {
        "case_id": case_id, "scenario_id": case.scenario_id, "proposal": saved,
        "events": safe_events, "runs": [json.loads(row["snapshot"]) for row in runs],
    }


def _unavailable(error):
    if isinstance(error, ReadError) and error.code == "not_found":
        return SandboxError(409, "facts_unavailable", "The order facts could not be verified.")
    return SandboxError(503, "sandbox_unavailable", "The local sandbox is unavailable. Check the fixture setup or upgrade.")


def read_review(path: Path, case_id: str, customer_id: str) -> dict:
    try:
        with open_read_database(path) as db:
            load_metadata(db)
            case = _load_scoped_case(db, case_id, customer_id)
            return _snapshot(db, case)
    except (sqlite3.DatabaseError, ValueError) as error:
        raise _unavailable(error) from error


def _prepare(db, case, actor, metadata):
    current = _proposal(db, case.case_id)
    if current is not None and current["state"] not in STARTABLE:
        return current["revision"]
    clock = metadata["clock_utc"]
    result, latency_ms = _timed_investigation(db, case, clock)
    candidate = initial_proposal(case, result)
    if candidate is None:
        raise SandboxError(409, "no_proposal", "This case has no action ready for review.")
    revision = current["revision"] + 1 if current else 1
    _save_proposal(db, actor, clock, candidate, revision, "proposal.prepared")
    _save_run(db, case, actor, metadata, result, latency_ms, revision)
    return revision


def _edit(db, case, actor, clock, current, payload, amount_cents):
    if current["state"] not in {"awaiting_review", "approved"}:
        raise SandboxError(409, "invalid_state", "Editing requires a proposal awaiting review or approved for execution.")
    candidate = edit_proposal(db, case, clock, payload, amount_cents)
    if candidate is None or candidate.validation_status != "valid":
        raise SandboxError(409, "invalid_edit", "Choose a refund amount within the current eligible balance.")
    revision = current["revision"] + 1
    detail = f"Revision {current['revision']} was replaced by revision {revision}. A fresh approval is required."
    _transition(db, actor, clock, current, "invalidated", "proposal.superseded", detail)
    return _save_proposal(db, actor, clock, candidate, revision, "proposal.edited")


def _record_review(db, case, actor, clock, current, payload, command):
    if current["state"] != "awaiting_review":
        raise SandboxError(409, "invalid_state", "This proposal is no longer awaiting review.")
    decision = "approved" if command["action"] == "approve" else "denied"
    if decision == "approved":
        if payload.validation_status != "valid":
            raise SandboxError(409, "invalid_proposal", "Edit the invalid draft before approving it.")
        problem = validate_proposal(db, case, clock, payload)
        if problem:
            _transition(db, actor, clock, current, "invalidated", "proposal.invalidated", problem)
            return
    reason = command.get("reason")
    db.execute(
        "INSERT INTO sandbox_reviews VALUES (?, ?, ?, ?, ?, ?)",
        (case.case_id, current["revision"], decision, actor, reason, clock),
    )
    detail = f"Reviewer {decision} revision {current['revision']}."
    _transition(db, actor, clock, current, decision, f"review.{decision}", detail)


def _persist_result(db, execution_id, payload):
    if payload.remedy in REFUNDS:
        db.execute(
            "INSERT INTO refund_ledger (execution_id, order_id, line_id, amount_cents) VALUES (?, ?, ?, ?)",
            (execution_id, payload.order_id, payload.line_id, payload.amount_cents),
        )
    elif payload.remedy == "replacement":
        db.execute(
            "INSERT INTO replacement_requests VALUES (?, ?, ?, ?)",
            (execution_id, payload.order_id, payload.line_id, payload.quantity),
        )
    elif payload.remedy == "delay_update":
        db.execute("INSERT INTO sandbox_outbox VALUES (?, ?, ?)", (execution_id, payload.order_id, payload.draft))
        return
    else:
        raise SandboxError(409, "unsupported_remedy", "The proposed action has no local executor.")
    changed = db.execute(
        """
        UPDATE orders SET record = json_set(record, '$.version', ?)
        WHERE order_id = ? AND customer_id = ? AND json_extract(record, '$.version') = ?
        """,
        (payload.order_version + 1, payload.order_id, payload.customer_id, payload.order_version),
    )
    if changed.rowcount != 1:
        raise SandboxError(409, "stale_order", "The order changed before the action committed.")


def _finish_execution(db, actor, clock, proposal, execution_id, status, message):
    db.execute(
        "UPDATE sandbox_executions SET status = ?, message = ?, verified_at = ? WHERE execution_id = ?",
        (status, message, clock if status == "completed" else None, execution_id),
    )
    operation = "execution.verified" if status == "completed" else f"execution.{status}"
    _transition(db, actor, clock, proposal, status, operation, f"{execution_id}: {message}", execution_id)


def _execute(db, case, actor, clock, command):
    case_id, revision = case.case_id, command["revision"]
    key, simulation = command["idempotency_key"], command["simulation"]
    existing = db.execute("SELECT * FROM sandbox_executions WHERE idempotency_key = ?", (key,)).fetchone()
    if existing is not None:
        if (existing["case_id"], existing["revision"], existing["simulation"]) != (case_id, revision, simulation):
            raise SandboxError(409, "idempotency_conflict", "The key is already bound to a different action request.")
        verify_id = existing["execution_id"] if existing["status"] == "executing" and simulation == "normal" else None
        return revision, verify_id

    current = _require_current(db, case_id, revision)
    review = _review(db, current)
    if current["state"] != "approved" or review is None or review["decision"] != "approved":
        raise SandboxError(409, "approval_required", "Execution requires approval of this exact proposal revision.")
    payload = ProposalPreview.model_validate_json(current["payload"])
    problem = validate_proposal(db, case, clock, payload)
    if problem:
        _transition(db, actor, clock, current, "invalidated", "approval.invalidated", problem)
        return revision, None

    execution_id = uuid4().hex
    db.execute(
        "INSERT INTO sandbox_executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (execution_id, case_id, revision, key, simulation, "executing", "Awaiting verified readback.", clock, None),
    )
    key_fingerprint = sha256(key.encode()).hexdigest()[:12]
    _transition(db, actor, clock, current, "executing", "execution.started",
                f"Started {execution_id} with idempotency fingerprint {key_fingerprint}.", execution_id)
    running = {**dict(current), "state": "executing"}
    if simulation == "reject_before_commit":
        _finish_execution(db, actor, clock, running, execution_id, "failed", "The sandbox rejected the write before creating a result.")
        return revision, None
    if simulation != "unresolved":
        _persist_result(db, execution_id, payload)
    if simulation != "normal":
        _finish_execution(db, actor, clock, running, execution_id, "uncertain", "Write outcome is uncertain. Reconcile the original operation.")
        return revision, None
    return revision, execution_id


def _reconcile(db, case_id, actor, clock, execution_id):
    operation = db.execute(
        "SELECT * FROM sandbox_executions WHERE case_id = ? AND execution_id = ?", (case_id, execution_id),
    ).fetchone()
    if operation is None:
        raise SandboxError(404, "not_found", "The execution is unavailable for this case.")
    revision = operation["revision"]
    if operation["status"] == "failed":
        return revision
    current = _proposal(db, case_id, revision)
    payload = ProposalPreview.model_validate_json(current["payload"])
    if _matches_result(db, execution_id, payload):
        if operation["status"] != "completed":
            _finish_execution(db, actor, clock, current, execution_id, "completed", "Verified the saved local sandbox record.")
    else:
        _finish_execution(db, actor, clock, current, execution_id, "uncertain", "A matching result is unverified. Keep the reservation and reconcile this operation.")
    return revision


def mutate_review(path: Path, case_id: str, customer_id: str, reviewer_id: str, command: dict) -> dict:
    action = command["action"]
    verify_id = None
    try:
        with open_write_database(path) as db:
            metadata = load_metadata(db)
            clock = metadata["clock_utc"]
            case = _load_scoped_case(db, case_id, customer_id)
            if action == "prepare":
                revision = _prepare(db, case, reviewer_id, metadata)
            elif action == "record_run":
                replay, latency_ms = _timed_investigation(db, case, clock)
                _save_run(db, case, reviewer_id, metadata, replay, latency_ms)
                revision = None
            elif action == "execute":
                revision, verify_id = _execute(db, case, reviewer_id, clock, command)
            elif action == "reconcile":
                revision = _reconcile(db, case_id, reviewer_id, clock, command["execution_id"])
            else:
                revision = command["revision"]
                current = _require_current(db, case_id, revision)
                payload = ProposalPreview.model_validate_json(current["payload"])
                if action == "edit":
                    revision = _edit(db, case, reviewer_id, clock, current, payload, command["amount_cents"])
                else:
                    _record_review(db, case, reviewer_id, clock, current, payload, command)
            result = _snapshot(db, case, revision)
    except (sqlite3.DatabaseError, ReadError, ValueError) as error:
        raise _unavailable(error) from error

    if verify_id is None:
        return result
    # The record has committed. Check it in a separate transaction before reporting completion.
    try:
        with open_write_database(path) as db:
            case = _load_scoped_case(db, case_id, customer_id)
            _reconcile(db, case_id, reviewer_id, clock, verify_id)
            return _snapshot(db, case, revision)
    except (sqlite3.DatabaseError, ValueError):
        # Retain the original operation and never treat a failed readback as a failed write.
        return result
