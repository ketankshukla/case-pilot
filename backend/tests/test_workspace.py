import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from casepilot.app import create_app
from casepilot.database import reset_fixture_database
from casepilot.preview import app as hosted_preview_app
from casepilot.reads import ReadError


TEST_TOKEN = "fixture-test-token"


class WorkspacePreviewTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "demo.sqlite3"
        reset_fixture_database(self.path)
        self.enterContext(patch.dict("os.environ", {"CASEPILOT_DEMO_TOKEN": TEST_TOKEN}))
        self.client = self.enterContext(TestClient(create_app(self.path), base_url="http://127.0.0.1"))
        self.headers = {"Authorization": f"Bearer {TEST_TOKEN}"}

    def case(self, case_id):
        response = self.client.get(f"/demo/cases/{case_id}/investigation", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_sc01_preview_loads_full_refund_without_ledger_write(self):
        case = self.case("CP-0100")
        self.assertEqual(case["mode"], "replay")
        self.assertEqual(case["state"], "awaiting_review")
        self.assertEqual(case["order"]["order_id"], "O100")
        self.assertEqual(case["order"]["version"], 3)
        self.assertEqual(case["proposal"]["amount_cents"], 8000)
        self.assertEqual(case["proposal"]["currency"], "USD")
        self.assertEqual([(item["source_id"], item["version"]) for item in case["evidence"]], [("KB01", 1), ("KB04", 1)])
        self.assertEqual([event["operation"] for event in case["history"]], [
            "order.lookup", "policies.search", "refunds.lookup", "replay.decision",
        ])
        self.assertEqual(self.case("CP-0100")["proposal"], case["proposal"])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM refund_ledger").fetchone()[0], 0)

    def test_sc05_preview_pauses_with_no_order_or_proposal(self):
        case = self.case("CP-0105")
        self.assertEqual(case["state"], "awaiting_information")
        self.assertTrue(case["missing_information"])
        self.assertIsNone(case["order"])
        self.assertIsNone(case["proposal"])
        self.assertEqual(case["evidence_status"], "not_checked")
        self.assertEqual([event["operation"] for event in case["history"]], ["replay.decision"])

    def test_sc02_return_date_boundaries_and_invalid_dates(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            order = json.loads(db.execute("SELECT record FROM orders WHERE order_id = 'O100'").fetchone()[0])
            order["order_id"] = "O130"
            db.execute("INSERT INTO orders VALUES (?, ?, ?)", ("O130", "C100", json.dumps(order)))
            case = {
                "case_id": "CP-0102", "scenario_id": "SC02", "customer_id": "C100",
                "intent": "return", "request": "Please refund my unused return.", "title": "Return date boundary",
                "order_id": "O130",
            }
            db.execute("INSERT INTO cases VALUES (?, ?, ?, ?)", ("CP-0102", "C100", "O130", json.dumps(case)))
        for delivered_on, eligible in (
            ("2026-10-19", True), ("2026-10-18", False), ("2026-11-18", True),
            ("2026-11-19", False), ("invalid-date", False),
        ):
            with self.subTest(delivered_on=delivered_on):
                order["delivered_on"] = delivered_on
                with closing(sqlite3.connect(self.path)) as db, db:
                    db.execute("UPDATE orders SET record = ? WHERE order_id = 'O130'", (json.dumps(order),))
                result = self.case("CP-0102")
                self.assertEqual(result["state"], "awaiting_review" if eligible else "escalated")
                self.assertEqual(result["proposal"] is not None, eligible)

    def test_sc06_preview_requires_token_and_uses_server_customer_scope(self):
        self.assertEqual(self.client.get("/demo/workspace").status_code, 401)
        response = self.client.get("/demo/workspace", headers={"Authorization": "Bearer wrong-test-token"})
        self.assertEqual(response.status_code, 401)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO cases VALUES (?, ?, ?, ?)", ("CP-0900", "C200", "O900", "{}"))
        response = self.client.get("/demo/workspace", params={"customer_id": "C200"}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["persona"]["customer_id"], "C100")
        self.assertNotIn("O900", response.text)
        self.assertNotIn("CP-0900", response.text)
        for suffix in ("", "/lines/A", "/refunds", "/shipment"):
            with self.subTest(suffix=suffix):
                response = self.client.get(f"/demo/orders/O900{suffix}", params={"customer_id": "C200"}, headers=self.headers)
                missing = self.client.get(f"/demo/orders/O999{suffix}", headers=self.headers)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), missing.json())
        for suffix in ("investigation", "policies"):
            response = self.client.get(f"/demo/cases/CP-0900/{suffix}", headers=self.headers)
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.post("/demo/orders/O900/refunds", headers=self.headers).status_code, 405)

    def test_sc06_mismatched_case_identity_cannot_change_scope(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            record = json.loads(db.execute("SELECT record FROM cases WHERE case_id = 'CP-0100'").fetchone()[0])
            record.update(customer_id="C200", order_id="O900")
            db.execute("UPDATE cases SET record = ? WHERE case_id = 'CP-0100'", (json.dumps(record),))
        response = self.client.get("/demo/cases/CP-0100/investigation", headers=self.headers)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("O900", response.text)

    def test_sc07_evidence_gaps_and_conflicts_escalate(self):
        for case_id, status in (("CP-0107", "missing"), ("CP-0107-B", "conflicting"), ("CP-0107-C", "missing")):
            with self.subTest(case_id=case_id):
                case = self.case(case_id)
                self.assertEqual(case["state"], "escalated")
                self.assertEqual(case["evidence_status"], status)
                self.assertIsNotNone(case["order"])
                self.assertIsNone(case["proposal"])
                self.assertNotIn("refunds.lookup", [event["operation"] for event in case["history"]])
                matching = [p for p in case["evidence"] if p["topic"] == "return"]
                self.assertEqual(len(matching), 2 if status == "conflicting" else 0)
                self.assertTrue(all(p["approval_status"] == "approved" for p in case["evidence"]))
                result = self.client.get(f"/demo/cases/{case_id}/policies", headers=self.headers)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["status"], status)
                self.assertEqual(result.json()["passages"], case["evidence"])

    def test_sc09_line_price_and_remaining_balance_are_scoped(self):
        line = self.client.get("/demo/orders/O200/lines/A", headers=self.headers)
        self.assertEqual(line.status_code, 200)
        self.assertEqual(line.json()["paid_cents"], 4000)
        balance = self.client.get("/demo/orders/O209/refunds", params={"line_id": "A"}, headers=self.headers)
        self.assertEqual(balance.status_code, 200)
        self.assertEqual(balance.json()["remaining_cents"], 2000)
        self.assertEqual(balance.json()["prior_refunded_cents"], 1500)
        self.assertEqual(balance.json()["pending_cents"], 500)
        case = self.case("CP-0109-B")
        self.assertEqual(case["state"], "awaiting_review")
        self.assertEqual(case["proposal"]["remedy"], "partial_refund")
        self.assertEqual(case["proposal"]["line_id"], "A")
        self.assertEqual(case["proposal"]["amount_cents"], 2000)
        self.assertIn("line.lookup", [event["operation"] for event in case["history"]])

    def test_sc10_timeout_retries_once_and_returns_no_proposal(self):
        with patch("casepilot.investigation.DemoReads.order", side_effect=ReadError("timeout", "The read timed out.")) as order:
            case = self.case("CP-0100")
        self.assertEqual(order.call_count, 2)
        self.assertEqual(case["state"], "escalated")
        self.assertIsNone(case["proposal"])
        events = [event for event in case["history"] if event["operation"] == "order.lookup"]
        self.assertEqual([event["attempt"] for event in events], [1, 2])
        self.assertEqual([event["status"] for event in events], ["error", "error"])

    def test_sc11_malformed_replay_refund_and_bad_id_are_rejected(self):
        with patch("casepilot.investigation.replay_refund", return_value={"remedy": "full_refund", "amount_cents": "8000"}):
            case = self.case("CP-0100")
        self.assertEqual(case["state"], "escalated")
        self.assertIsNone(case["proposal"])
        result = self.client.get("/demo/orders/invalid-id", headers=self.headers)
        self.assertEqual(result.status_code, 422)

    def test_sc18_preview_shows_unknown_shipment_and_no_eta_or_proposal(self):
        case = self.case("CP-0118")
        facts = {fact["label"]: fact["value"] for fact in case["order"]["facts"]}
        self.assertEqual(facts["Shipment status"], "Unknown")
        self.assertEqual(facts["Promised for"], "2026-11-10 (8 days ago)")
        self.assertNotIn("Estimated delivery", facts)
        self.assertIsNone(case["proposal"])
        self.assertEqual(case["state"], "awaiting_information")
        self.assertIn("unknown status", case["draft"])
        shipment = self.client.get("/demo/orders/O300/shipment", headers=self.headers)
        self.assertEqual(shipment.status_code, 200)
        self.assertEqual(shipment.json()["shipment_status"], "unknown")
        self.assertTrue(any(event["operation"] == "shipment.lookup" for event in case["history"]))

    def test_sc01_hosted_preview_uses_packaged_fixtures_and_rejects_writes(self):
        workspace_path = "/demo/workspace"
        binding_host = "https://binding.example.test"
        self.assertEqual(self.client.get(f"{binding_host}{workspace_path}", headers=self.headers).status_code, 400)
        with TestClient(hosted_preview_app, base_url=binding_host) as client:
            self.assertEqual(client.get(workspace_path).status_code, 401)
            workspace = client.get(workspace_path, headers=self.headers)
            self.assertEqual(workspace.status_code, 200)
            self.assertEqual(workspace.json()["fixture_version"], "stage1-v2")
            self.assertNotIn("proposal", workspace.json()["cases"][0])
            investigation = client.get("/demo/cases/CP-0100/investigation", headers=self.headers)
            self.assertEqual(investigation.status_code, 200)
            self.assertEqual(investigation.json()["proposal"]["amount_cents"], 8000)
            self.assertEqual(client.post(workspace_path, headers=self.headers).status_code, 405)


if __name__ == "__main__":
    unittest.main()
