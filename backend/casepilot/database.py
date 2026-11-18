import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = BACKEND_ROOT / "fixtures" / "stage1.json"
DEMO_DB_PATH = BACKEND_ROOT / "data" / "demo.sqlite3"
FIXTURE_VERSION = "stage1-v3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS fixture_metadata (
    fixture_version TEXT NOT NULL,
    clock_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    record TEXT NOT NULL,
    UNIQUE (order_id, customer_id)
);
CREATE TABLE IF NOT EXISTS policies (
    source_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    record TEXT NOT NULL,
    PRIMARY KEY (source_id, version)
);
CREATE VIRTUAL TABLE IF NOT EXISTS policy_passages USING fts5(
    source_id UNINDEXED,
    version UNINDEXED,
    title,
    excerpt
);
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    order_id TEXT,
    record TEXT NOT NULL,
    FOREIGN KEY (order_id, customer_id) REFERENCES orders (order_id, customer_id)
);
CREATE TABLE IF NOT EXISTS refund_ledger (
    execution_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders (order_id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    line_id TEXT
);
CREATE TABLE IF NOT EXISTS sandbox_proposals (
    case_id TEXT NOT NULL REFERENCES cases (case_id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    payload TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'awaiting_review', 'approved', 'denied', 'executing', 'completed', 'failed', 'uncertain', 'invalidated'
    )),
    idempotency_key TEXT NOT NULL UNIQUE,
    PRIMARY KEY (case_id, revision)
);
CREATE TABLE IF NOT EXISTS sandbox_reviews (
    case_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'denied')),
    reviewer_id TEXT NOT NULL,
    reason TEXT,
    at_utc TEXT NOT NULL,
    PRIMARY KEY (case_id, revision),
    FOREIGN KEY (case_id, revision) REFERENCES sandbox_proposals (case_id, revision)
);
CREATE TABLE IF NOT EXISTS sandbox_executions (
    execution_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    simulation TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('executing', 'completed', 'failed', 'uncertain')),
    message TEXT NOT NULL,
    started_at TEXT NOT NULL,
    verified_at TEXT,
    UNIQUE (case_id, revision),
    FOREIGN KEY (case_id, revision) REFERENCES sandbox_proposals (case_id, revision)
);
CREATE TABLE IF NOT EXISTS replacement_requests (
    execution_id TEXT PRIMARY KEY REFERENCES sandbox_executions (execution_id),
    order_id TEXT NOT NULL REFERENCES orders (order_id),
    line_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0)
);
CREATE TABLE IF NOT EXISTS sandbox_outbox (
    execution_id TEXT PRIMARY KEY REFERENCES sandbox_executions (execution_id),
    order_id TEXT NOT NULL REFERENCES orders (order_id),
    draft TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sandbox_events (
    event_id INTEGER PRIMARY KEY,
    case_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    actor TEXT NOT NULL,
    operation TEXT NOT NULL,
    detail TEXT NOT NULL,
    at_utc TEXT NOT NULL,
    before_state TEXT,
    after_state TEXT NOT NULL,
    execution_id TEXT REFERENCES sandbox_executions (execution_id),
    FOREIGN KEY (case_id, revision) REFERENCES sandbox_proposals (case_id, revision)
);
"""


def reset_fixture_database(path: Path = DEMO_DB_PATH) -> dict:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)

    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(SCHEMA)
        db.execute("BEGIN IMMEDIATE")
        with db:
            ledger_columns = {column[1] for column in db.execute("PRAGMA table_info(refund_ledger)")}
            if "line_id" not in ledger_columns:
                db.execute("ALTER TABLE refund_ledger ADD COLUMN line_id TEXT")
            db.execute("DELETE FROM sandbox_events")
            db.execute("DELETE FROM replacement_requests")
            db.execute("DELETE FROM sandbox_outbox")
            db.execute("DELETE FROM refund_ledger")
            db.execute("DELETE FROM sandbox_executions")
            db.execute("DELETE FROM sandbox_reviews")
            db.execute("DELETE FROM sandbox_proposals")
            db.execute("DELETE FROM cases")
            db.execute("DELETE FROM orders")
            db.execute("DELETE FROM policy_passages")
            db.execute("DELETE FROM policies")
            db.execute("DELETE FROM fixture_metadata")
            db.execute(
                "INSERT INTO fixture_metadata VALUES (?, ?)",
                (fixture["fixture_version"], fixture["clock_utc"]),
            )
            db.executemany(
                "INSERT INTO orders VALUES (?, ?, ?)",
                [(order["order_id"], order["customer_id"], json.dumps(order)) for order in fixture["orders"]],
            )
            db.executemany(
                "INSERT INTO policies VALUES (?, ?, ?)",
                [(policy["source_id"], policy["version"], json.dumps(policy)) for policy in fixture["policies"]],
            )
            db.executemany(
                "INSERT INTO policy_passages (source_id, version, title, excerpt) VALUES (?, ?, ?, ?)",
                [(policy["source_id"], policy["version"], policy["title"], policy["excerpt"]) for policy in fixture["policies"]],
            )
            db.executemany(
                "INSERT INTO cases VALUES (?, ?, ?, ?)",
                [(case["case_id"], case["customer_id"], case["order_id"], json.dumps(case)) for case in fixture["cases"]],
            )

    return {"fixture_version": fixture["fixture_version"], "clock_utc": fixture["clock_utc"]}


def order_preview(order: dict, clock_utc: str) -> dict:
    today = date.fromisoformat(clock_utc[:10])
    facts = [("Payment", "Settled" if order["settled"] else "Unsettled")]
    if order["delivered_on"]:
        delivered = date.fromisoformat(order["delivered_on"])
        elapsed_days = (today - delivered).days
        detail = f"{elapsed_days} days ago" if elapsed_days >= 0 else "future date"
        facts.append(("Delivered", f"{delivered} ({detail})"))
        if order["used"] is not None:
            facts.append(("Item condition", "Used" if order["used"] else "Unused"))
        facts.append(("Return received", "Yes" if order["return_received"] else "No"))
    if order["promised_on"]:
        promised = date.fromisoformat(order["promised_on"])
        facts.append(("Promised for", f"{promised} ({(today - promised).days} days ago)"))
        facts.append(("Shipment status", order["shipment_status"].capitalize()))

    return {
        "order_id": order["order_id"],
        "version": order["version"],
        "paid_cents": order["paid_cents"],
        "currency": order["currency"],
        "facts": [{"label": label, "value": value} for label, value in facts],
    }


@contextmanager
def open_read_database(path: Path) -> Iterator[sqlite3.Connection]:
    """Use one scoped, read-only snapshot for all reads in a request."""
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        yield db


@contextmanager
def open_write_database(path: Path) -> Iterator[sqlite3.Connection]:
    """Lock the write snapshot before loading facts and checking the approval."""
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("BEGIN IMMEDIATE")
        with db:
            yield db


def load_metadata(db: sqlite3.Connection) -> dict:
    metadata = db.execute("SELECT fixture_version, clock_utc FROM fixture_metadata").fetchone()
    if metadata is None or metadata["fixture_version"] != FIXTURE_VERSION:
        raise sqlite3.DatabaseError("The local demo data needs a fixture reset")
    return dict(metadata)


def list_cases(db: sqlite3.Connection, customer_id: str) -> list[dict]:
    rows = db.execute(
        """
        SELECT case_id, json_extract(record, '$.scenario_id') AS scenario_id,
            json_extract(record, '$.title') AS title
        FROM cases
        WHERE customer_id = ?
        ORDER BY case_id
        """,
        (customer_id,),
    )
    return [dict(row) for row in rows]


def load_case(db: sqlite3.Connection, customer_id: str, case_id: str) -> dict | None:
    row = db.execute(
        "SELECT case_id, order_id, record FROM cases WHERE customer_id = ? AND case_id = ?",
        (customer_id, case_id),
    ).fetchone()
    if row is None:
        return None
    case = json.loads(row["record"])
    expected = {"case_id": row["case_id"], "customer_id": customer_id, "order_id": row["order_id"]}
    if not isinstance(case, dict) or any(key not in case or case[key] != value for key, value in expected.items()):
        raise ValueError("Case record does not match its stored association")
    return case
