import json
import sqlite3
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator


Intent = Literal["return", "damage_refund", "damage_replace", "delay", "delay_replace"]
ShipmentStatus = Literal["unknown", "not_shipped", "in_transit", "delivered", "lost", "returned"]
OrderId = Annotated[str, Field(pattern=r"^O[0-9]{3,10}$")]
CustomerId = Annotated[str, Field(pattern=r"^C[0-9]{3,10}$")]
LineId = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9]{0,11}$")]
Product = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
Region = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
Cents = Annotated[int, Field(ge=0)]
ReadErrorCode = Literal["not_found", "missing_information", "invalid_data", "timeout", "unavailable"]


class ReadError(Exception):
    def __init__(self, code: ReadErrorCode, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def validate_day(value: str | None) -> str | None:
    if value is not None and date.fromisoformat(value).isoformat() != value:
        raise ValueError("Use an ISO calendar date")
    return value


class ReadModel(BaseModel):
    model_config = ConfigDict(strict=True)


class OrderFacts(ReadModel):
    order_id: OrderId
    customer_id: CustomerId
    version: Annotated[int, Field(gt=0)]
    paid_cents: Cents
    currency: Literal["USD"]
    settled: bool
    delivered_on: str | None
    used: bool | None
    return_received: bool
    promised_on: str | None
    shipment_status: ShipmentStatus
    product: Product
    region: Region

    _check_days = field_validator("delivered_on", "promised_on")(validate_day)


class LineFacts(ReadModel):
    line_id: LineId
    paid_cents: Cents
    quantity: Annotated[int, Field(gt=0)]
    damage_declaration_complete: bool
    replacement_stock: Annotated[int, Field(ge=0)]


class RefundFacts(ReadModel):
    prior_refunded_cents: Cents
    pending_cents: Cents
    remaining_cents: Cents
    replacement_blocks_refund: bool = False


class ShipmentFacts(ReadModel):
    shipment_status: ShipmentStatus
    promised_on: str | None
    delivered_on: str | None

    _check_days = field_validator("promised_on", "delivered_on")(validate_day)


class PolicyPassage(ReadModel):
    source_id: str
    title: str
    version: Annotated[int, Field(gt=0)]
    effective_date: str
    expires_on: str | None = None
    approval_status: Literal["approved"]
    excerpt: str
    topic: Literal["return", "damage", "delay", "accounting", "evidence"]
    rule_key: str
    product: Product
    region: Region

    _check_days = field_validator("effective_date", "expires_on")(validate_day)


class EvidenceResult(ReadModel):
    status: Literal["available", "missing", "conflicting"]
    passages: list[PolicyPassage]


class RefundEntry(ReadModel):
    line_id: LineId | None
    amount_cents: Annotated[int, Field(gt=0)]
    status: Literal["verified", "pending", "uncertain"]


class ReplacementEntry(ReadModel):
    line_id: LineId
    quantity: Annotated[int, Field(gt=0)]


LINES = TypeAdapter(list[LineFacts])
REFUND_ENTRIES = TypeAdapter(list[RefundEntry])
REPLACEMENT_ENTRIES = TypeAdapter(list[ReplacementEntry])
SEARCH_QUERIES: dict[Intent, str] = {
    "return": "return OR refund",
    "damage_refund": "damage OR damaged OR refund",
    "damage_replace": "damage OR damaged OR replacement",
    "delay": "delay OR shipment OR promised",
    "delay_replace": "delay OR shipment OR promised",
}
REQUIRED_RULES: dict[Intent, dict[str, str]] = {
    "return": {"return": "unused_received_30", "accounting": "settled_less_refunds"},
    "damage_refund": {"damage": "damage_declaration_14", "accounting": "settled_less_refunds"},
    "damage_replace": {"damage": "damage_declaration_14"},
    "delay": {"delay": "shipment_checked_7"},
    "delay_replace": {"delay": "shipment_checked_7"},
}


class DemoReads:
    """Read operations shared by the replay and the direct endpoints."""

    def __init__(self, db: sqlite3.Connection, customer_id: str, clock_utc: str):
        self.db = db
        self.customer_id = customer_id
        self.clock_utc = clock_utc

    def _load_order(self, order_id: str) -> tuple[OrderFacts, dict]:
        row = self.db.execute(
            "SELECT record FROM orders WHERE order_id = ? AND customer_id = ?",
            (order_id, self.customer_id),
        ).fetchone()
        if row is None:
            raise ReadError("not_found", "Order or line is unavailable to this demo session.")
        try:
            record = json.loads(row["record"])
            order = OrderFacts.model_validate(record)
        except (ValueError, TypeError) as exc:
            raise ReadError("invalid_data", "The order facts could not be verified.") from exc
        if order.order_id != order_id or order.customer_id != self.customer_id:
            raise ReadError("invalid_data", "The order facts could not be verified.")
        return order, record

    @staticmethod
    def _load_lines(record: dict) -> list[LineFacts]:
        try:
            lines = LINES.validate_python(record.get("lines"), strict=True)
        except ValidationError as exc:
            raise ReadError("invalid_data", "The line-item facts could not be verified.") from exc
        if len(lines) != len({line.line_id for line in lines}):
            raise ReadError("invalid_data", "The line-item facts could not be verified.")
        return lines

    @staticmethod
    def _find_line(lines: list[LineFacts], line_id: str) -> LineFacts:
        for line in lines:
            if line.line_id == line_id:
                return line
        raise ReadError("not_found", "Order or line is unavailable to this demo session.")

    def order(self, order_id: str) -> OrderFacts:
        order, _ = self._load_order(order_id)
        return order

    def line(self, order_id: str, line_id: str) -> LineFacts:
        _, record = self._load_order(order_id)
        return self._find_line(self._load_lines(record), line_id)

    def _refund_entries(self, order_id: str, record: dict, lines: list[LineFacts]) -> list[RefundEntry]:
        rows = self.db.execute(
            """
            SELECT ledger.line_id, ledger.amount_cents,
                CASE WHEN execution.status IN ('executing', 'uncertain') THEN 'uncertain' ELSE 'verified' END AS status
            FROM refund_ledger AS ledger
            LEFT JOIN sandbox_executions AS execution USING (execution_id)
            WHERE ledger.order_id = ?
            UNION ALL
            SELECT json_extract(proposal.payload, '$.line_id'),
                json_extract(proposal.payload, '$.amount_cents'), 'uncertain'
            FROM sandbox_executions AS execution
            JOIN sandbox_proposals AS proposal USING (case_id, revision)
            WHERE execution.status IN ('executing', 'uncertain', 'completed')
                AND json_extract(proposal.payload, '$.order_id') = ?
                AND json_extract(proposal.payload, '$.remedy') IN ('full_refund', 'partial_refund')
                AND NOT EXISTS (
                    SELECT 1 FROM refund_ledger
                    WHERE execution_id = execution.execution_id
                        AND order_id = json_extract(proposal.payload, '$.order_id')
                        AND line_id IS json_extract(proposal.payload, '$.line_id')
                        AND amount_cents = json_extract(proposal.payload, '$.amount_cents')
                )
            """,
            (order_id, order_id),
        )
        try:
            entries = REFUND_ENTRIES.validate_python(record.get("refund_entries", []), strict=True)
            entries.extend(REFUND_ENTRIES.validate_python([dict(row) for row in rows], strict=True))
        except ValidationError as exc:
            raise ReadError("invalid_data", "The refund balance could not be verified.") from exc
        known_lines = {item.line_id for item in lines}
        if any(entry.line_id is not None and entry.line_id not in known_lines for entry in entries):
            raise ReadError("invalid_data", "The refund balance could not be verified.")
        return entries

    def _replacement_entries(self, order_id: str, lines: list[LineFacts]) -> list[ReplacementEntry]:
        rows = self.db.execute(
            """
            SELECT line_id, quantity FROM replacement_requests WHERE order_id = ?
            UNION ALL
            SELECT json_extract(proposal.payload, '$.line_id'), json_extract(proposal.payload, '$.quantity')
            FROM sandbox_executions AS execution
            JOIN sandbox_proposals AS proposal USING (case_id, revision)
            WHERE execution.status IN ('executing', 'uncertain', 'completed')
                AND json_extract(proposal.payload, '$.order_id') = ?
                AND json_extract(proposal.payload, '$.remedy') = 'replacement'
                AND NOT EXISTS (
                    SELECT 1 FROM replacement_requests
                    WHERE execution_id = execution.execution_id
                        AND order_id = json_extract(proposal.payload, '$.order_id')
                        AND line_id = json_extract(proposal.payload, '$.line_id')
                        AND quantity = json_extract(proposal.payload, '$.quantity')
                )
            """,
            (order_id, order_id),
        )
        try:
            entries = REPLACEMENT_ENTRIES.validate_python([dict(row) for row in rows], strict=True)
        except ValidationError as exc:
            raise ReadError("invalid_data", "Replacement availability could not be verified.") from exc
        known_lines = {line.line_id for line in lines}
        if any(entry.line_id not in known_lines for entry in entries):
            raise ReadError("invalid_data", "Replacement availability could not be verified.")
        return entries

    def refunds(self, order_id: str, line_id: str | None = None) -> RefundFacts:
        order, record = self._load_order(order_id)
        lines = self._load_lines(record)
        line = self._find_line(lines, line_id) if line_id is not None else None
        entries = self._refund_entries(order_id, record, lines)
        replacements = self._replacement_entries(order_id, lines)
        paid_cents = order.paid_cents if order.settled else 0
        order_prior, order_pending = self._refund_totals(entries)
        order_remaining = max(0, paid_cents - order_prior - order_pending)
        if line is None:
            return RefundFacts(
                prior_refunded_cents=order_prior,
                pending_cents=order_pending,
                remaining_cents=order_remaining,
                replacement_blocks_refund=bool(replacements),
            )

        # A refund without a line allocation can reduce any line's available balance.
        line_entries = [entry for entry in entries if entry.line_id in (None, line.line_id)]
        line_prior, line_pending = self._refund_totals(line_entries)
        line_paid = line.paid_cents if order.settled else 0
        return RefundFacts(
            prior_refunded_cents=line_prior,
            pending_cents=line_pending,
            remaining_cents=min(order_remaining, max(0, line_paid - line_prior - line_pending)),
            replacement_blocks_refund=any(entry.line_id == line.line_id for entry in replacements),
        )

    def replacement_quantity(self, order_id: str, line_id: str) -> int:
        order, record = self._load_order(order_id)
        lines = self._load_lines(record)
        line = self._find_line(lines, line_id)
        entries = self._refund_entries(order_id, record, lines)
        # Refunds have amount allocations but no unit allocations. Refuse an overlapping remedy
        # when the prior refund could include this line.
        if not order.settled or any(entry.line_id in (None, line_id) for entry in entries):
            return 0
        replacements = self._replacement_entries(order_id, lines)
        committed = sum(entry.quantity for entry in replacements if entry.line_id == line_id)
        return max(0, min(line.quantity, line.replacement_stock) - committed)

    @staticmethod
    def _refund_totals(entries: list[RefundEntry]) -> tuple[int, int]:
        verified = sum(entry.amount_cents for entry in entries if entry.status == "verified")
        reserved = sum(entry.amount_cents for entry in entries if entry.status != "verified")
        return verified, reserved

    def shipment(self, order_id: str) -> ShipmentFacts:
        order = self.order(order_id)
        return ShipmentFacts(
            shipment_status=order.shipment_status,
            promised_on=order.promised_on,
            delivered_on=order.delivered_on,
        )

    def policies(self, intent: Intent, product: str, region: str) -> EvidenceResult:
        required = REQUIRED_RULES[intent]
        today = self.clock_utc[:10]
        rows = self.db.execute(
            """
            SELECT policies.record
            FROM policy_passages
            JOIN policies ON policies.source_id = policy_passages.source_id
                AND policies.version = policy_passages.version
                AND json_extract(policies.record, '$.title') = policy_passages.title
                AND json_extract(policies.record, '$.excerpt') = policy_passages.excerpt
            WHERE policy_passages MATCH ?
                AND json_extract(policies.record, '$.approval_status') = 'approved'
                AND json_extract(policies.record, '$.product') = ?
                AND json_extract(policies.record, '$.region') = ?
                AND json_extract(policies.record, '$.effective_date') <= ?
                AND (json_extract(policies.record, '$.expires_on') IS NULL
                    OR json_extract(policies.record, '$.expires_on') > ?)
                AND json_extract(policies.record, '$.topic') IN (SELECT value FROM json_each(?))
            ORDER BY policies.source_id, policies.version DESC
            """,
            (SEARCH_QUERIES[intent], product, region, today, today, json.dumps(list(required))),
        )
        try:
            passages = [PolicyPassage.model_validate_json(row["record"]) for row in rows]
        except ValidationError as exc:
            raise ReadError("invalid_data", "The policy passages could not be verified.") from exc
        rules = {
            topic: {passage.rule_key for passage in passages if passage.topic == topic}
            for topic in required
        }
        if any(len(values) > 1 for values in rules.values()):
            return EvidenceResult(status="conflicting", passages=passages)
        if any(rule_key not in rules[topic] for topic, rule_key in required.items()):
            return EvidenceResult(status="missing", passages=passages)
        return EvidenceResult(status="available", passages=passages)
