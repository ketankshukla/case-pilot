import os
import secrets
import sqlite3
from pathlib import Path
from time import monotonic
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .database import DEMO_DB_PATH, list_cases, load_case, load_metadata, open_read_database
from .investigation import READ_TIMEOUT_SECONDS, CaseId, CaseInput, CaseSummary, Investigation, bounded_read, investigate
from .reads import DemoReads, EvidenceResult, LineFacts, LineId, OrderFacts, OrderId, ReadError, ReadErrorCode, RefundFacts, ShipmentFacts


class DemoPersona(BaseModel):
    display_name: str
    customer_id: str


class WorkspacePreview(BaseModel):
    fixture_version: str
    clock_utc: str
    persona: DemoPersona
    cases: list[CaseSummary]


class ReadErrorDetail(BaseModel):
    code: ReadErrorCode
    message: str


READ_ERROR_STATUS = {"not_found": 404, "missing_information": 409, "invalid_data": 502, "timeout": 504, "unavailable": 503}


def read_error(code: ReadErrorCode, message: str) -> HTTPException:
    return HTTPException(READ_ERROR_STATUS[code], ReadErrorDetail(code=code, message=message).model_dump())


def create_app(path: Path = DEMO_DB_PATH, *, allow_binding_hosts: bool = False) -> FastAPI:
    app = FastAPI(title="CasePilot demo", openapi_url=None)
    if not allow_binding_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    bearer = HTTPBearer(auto_error=False)

    def demo_persona(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> DemoPersona:
        expected = os.environ.get("CASEPILOT_DEMO_TOKEN", "")
        if not expected:
            raise HTTPException(503, "Configure the demo token before opening the workspace.")
        if credentials is None or not secrets.compare_digest(credentials.credentials.encode(), expected.encode()):
            raise HTTPException(401, "Demo session required.", headers={"WWW-Authenticate": "Bearer"})
        return DemoPersona(display_name="Demo support rep", customer_id="C100")

    Persona = Annotated[DemoPersona, Depends(demo_persona)]

    def with_fixtures(action):
        try:
            with open_read_database(path) as db:
                return action(db, bounded_read(db, monotonic() + READ_TIMEOUT_SECONDS, lambda: load_metadata(db)))
        except ReadError as exc:
            raise read_error(exc.code, exc.message) from exc
        except ValueError as exc:
            raise read_error("invalid_data", "The fixture record is invalid. Verify or reset the demo data and try again.") from exc
        except sqlite3.DatabaseError as exc:
            raise read_error("unavailable", "Local fixtures are unavailable. Reset the demo data and try again.") from exc

    def scoped_read(persona, operation):
        return with_fixtures(lambda db, meta: bounded_read(
            db, monotonic() + READ_TIMEOUT_SECONDS, lambda: operation(DemoReads(db, persona.customer_id, meta["clock_utc"])),
        ))

    def scoped_case(db, persona, case_id) -> CaseInput:
        case = bounded_read(db, monotonic() + READ_TIMEOUT_SECONDS, lambda: load_case(db, persona.customer_id, case_id))
        if case is None:
            raise ReadError("not_found", "The case is unavailable for this account.")
        return CaseInput.model_validate(case)

    @app.get("/demo/workspace", response_model=WorkspacePreview)
    def workspace(persona: Persona) -> dict:
        return with_fixtures(lambda db, meta: {
            **meta, "persona": persona,
            "cases": bounded_read(db, monotonic() + READ_TIMEOUT_SECONDS, lambda: list_cases(db, persona.customer_id)),
        })

    @app.get("/demo/cases/{case_id}/investigation", response_model=Investigation)
    def investigation(case_id: CaseId, persona: Persona) -> Investigation:
        return with_fixtures(lambda db, meta: investigate(db, scoped_case(db, persona, case_id), meta["clock_utc"]))

    @app.get("/demo/orders/{order_id}", response_model=OrderFacts)
    def order_lookup(order_id: OrderId, persona: Persona) -> OrderFacts:
        return scoped_read(persona, lambda tool: tool.order(order_id))

    @app.get("/demo/orders/{order_id}/lines/{line_id}", response_model=LineFacts)
    def line_lookup(order_id: OrderId, line_id: LineId, persona: Persona) -> LineFacts:
        return scoped_read(persona, lambda tool: tool.line(order_id, line_id))

    @app.get("/demo/orders/{order_id}/refunds", response_model=RefundFacts)
    def refund_lookup(order_id: OrderId, persona: Persona, line_id: LineId | None = None) -> RefundFacts:
        return scoped_read(persona, lambda tool: tool.refunds(order_id, line_id))

    @app.get("/demo/orders/{order_id}/shipment", response_model=ShipmentFacts)
    def shipment_lookup(order_id: OrderId, persona: Persona) -> ShipmentFacts:
        return scoped_read(persona, lambda tool: tool.shipment(order_id))

    @app.get("/demo/cases/{case_id}/policies", response_model=EvidenceResult)
    def policy_lookup(case_id: CaseId, persona: Persona) -> EvidenceResult:
        def read_policies(db, meta):
            case = scoped_case(db, persona, case_id)
            if not case.order_id:
                raise ReadError("missing_information", "An order ID is needed to check policy applicability.")
            reads = DemoReads(db, persona.customer_id, meta["clock_utc"])
            order = bounded_read(db, monotonic() + READ_TIMEOUT_SECONDS, lambda: reads.order(case.order_id))
            return bounded_read(db, monotonic() + READ_TIMEOUT_SECONDS, lambda: reads.policies(case.intent, order.product, order.region))

        return with_fixtures(read_policies)

    return app


app = create_app()
