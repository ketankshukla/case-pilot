import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = BACKEND_ROOT / "fixtures" / "stage1.json"
DEMO_DB_PATH = BACKEND_ROOT / "data" / "demo.sqlite3"

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
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0)
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
            db.execute("DELETE FROM refund_ledger")
            db.execute("DELETE FROM cases")
            db.execute("DELETE FROM orders")
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
                "INSERT INTO cases VALUES (?, ?, ?, ?)",
                [(case["case_id"], case["customer_id"], case["order_id"], json.dumps(case)) for case in fixture["cases"]],
            )

    return {"fixture_version": fixture["fixture_version"], "clock_utc": fixture["clock_utc"]}


def order_preview(order: dict, clock_utc: str) -> dict:
    today = date.fromisoformat(clock_utc[:10])
    facts = [("Payment", "Settled" if order["settled"] else "Unsettled")]
    if order["delivered_on"]:
        delivered = date.fromisoformat(order["delivered_on"])
        facts.append(("Delivered", f"{delivered} ({(today - delivered).days} days ago)"))
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


def load_workspace(path: Path, customer_id: str) -> dict:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        metadata = db.execute("SELECT fixture_version, clock_utc FROM fixture_metadata").fetchone()
        if metadata is None:
            raise sqlite3.DatabaseError("Fixture metadata is missing")

        policies = {
            (row["source_id"], row["version"]): json.loads(row["record"])
            for row in db.execute("SELECT source_id, version, record FROM policies")
        }
        # Scope the case and its linked order before reading any order facts.
        rows = db.execute(
            """
            SELECT cases.record AS case_record, orders.record AS order_record
            FROM cases
            LEFT JOIN orders ON orders.order_id = cases.order_id
                AND orders.customer_id = cases.customer_id
            WHERE cases.customer_id = ? AND (cases.order_id IS NULL OR orders.order_id IS NOT NULL)
            ORDER BY cases.case_id
            """,
            (customer_id,),
        )

        cases = []
        for row in rows:
            case = json.loads(row["case_record"])
            order = json.loads(row["order_record"]) if row["order_record"] else None
            case["order"] = order_preview(order, metadata["clock_utc"]) if order else None
            case["evidence"] = [policies[tuple(reference)] for reference in case["evidence"]]
            cases.append(case)

        return {**dict(metadata), "cases": cases}
