import os
import secrets
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .database import DEMO_DB_PATH, load_workspace


class Fact(BaseModel):
    label: str
    value: str


class OrderPreview(BaseModel):
    order_id: str
    version: int
    paid_cents: int
    currency: Literal["USD"]
    facts: list[Fact]


class EvidencePreview(BaseModel):
    source_id: str
    title: str
    version: int
    effective_date: str
    excerpt: str


class ProposalPreview(BaseModel):
    revision: int
    remedy: Literal["full_refund"]
    amount_cents: int
    currency: Literal["USD"]
    order_version: int
    policy_ids: list[str]
    validation_summary: str


class HistoryPreview(BaseModel):
    at_utc: str
    title: str
    detail: str


class CasePreview(BaseModel):
    case_id: str
    scenario_id: str
    title: str
    state: Literal["investigating", "awaiting_information", "awaiting_review"]
    request: str
    order: OrderPreview | None
    missing_information: list[str]
    evidence: list[EvidencePreview]
    proposal: ProposalPreview | None
    history: list[HistoryPreview]


class DemoPersona(BaseModel):
    display_name: str
    customer_id: str


class WorkspacePreview(BaseModel):
    fixture_version: str
    clock_utc: str
    persona: DemoPersona
    cases: list[CasePreview]


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

    @app.get("/demo/workspace", response_model=WorkspacePreview)
    def workspace(persona: Annotated[DemoPersona, Depends(demo_persona)]) -> dict:
        try:
            snapshot = load_workspace(path, persona.customer_id)
        except sqlite3.DatabaseError as exc:
            raise HTTPException(503, "Local fixtures are unavailable. Reset the demo data and try again.") from exc
        return {**snapshot, "persona": persona}

    return app


app = create_app()
