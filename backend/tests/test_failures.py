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
from casepilot.reads import DemoReads, ReadError


SUPPORT_TOKEN = "fixture-failure-support"
REVIEWER_TOKEN = "fixture-failure-reviewer-placeholder"


class FailureScenarioTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "demo.sqlite3"
        reset_fixture_database(self.path)
        self.enterContext(patch.dict("os.environ", {
            "CASEPILOT_DEMO_TOKEN": SUPPORT_TOKEN, "CASEPILOT_REVIEWER_TOKEN": REVIEWER_TOKEN,
        }))
        self.client = self.enterContext(TestClient(create_app(self.path), base_url="http://127.0.0.1"))
        self.support = {"Authorization": f"Bearer {SUPPORT_TOKEN}"}
        self.reviewer = {"Authorization": f"Bearer {REVIEWER_TOKEN}"}

    def investigation(self, case_id):
        response = self.client.get(f"/demo/cases/{case_id}/investigation", headers=self.support)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def review(self, case_id, action, expected=200, **fields):
        response = self.client.post(f"/demo/cases/{case_id}/review", headers=self.reviewer,
                                    json={"action": action, **fields})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def update_order(self, order_id, order):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE orders SET record = ? WHERE order_id = ?", (json.dumps(order), order_id))

    def stored_order(self, order_id):
        with closing(sqlite3.connect(self.path)) as db:
            return json.loads(db.execute("SELECT record FROM orders WHERE order_id = ?", (order_id,)).fetchone()[0])

    def assert_no_sandbox_actions(self):
        with closing(sqlite3.connect(self.path)) as db:
            for table in ("sandbox_executions", "refund_ledger", "replacement_requests", "sandbox_outbox"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)

    def test_sc05_two_matches_and_no_match_stay_unresolved_within_scope(self):
        for case_id, expected in (("CP-0105-B", ["O505", "O506"]), ("CP-0105-C", [])):
            with self.subTest(case_id=case_id):
                result = self.investigation(case_id)
                self.assertEqual(result["state"], "awaiting_information")
                self.assertEqual(result["candidate_order_ids"], expected)
                self.assertTrue(result["missing_information"])
                self.assertIsNone(result["order"])
                self.assertIsNone(result["proposal"])
                self.assertEqual([event["operation"] for event in result["history"]], [
                    "orders.find_candidates", "replay.decision",
                ])
                serialized = json.dumps(result)
                for hidden in ("O900", "O905", "O906", "C200"):
                    self.assertNotIn(hidden, serialized)
                self.review(case_id, "prepare", expected=409)
        self.assert_no_sandbox_actions()

    def test_sc10_direct_read_timeout_has_a_typed_error(self):
        with patch.object(DemoReads, "order", side_effect=ReadError("timeout", "The read timed out.")) as read:
            response = self.client.get("/demo/orders/O100", headers=self.support)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["detail"]["code"], "timeout")
        self.assert_no_sandbox_actions()

    def test_sc10_retries_share_the_six_read_budget(self):
        def delay_once(method):
            attempted = False

            def read(*args, **kwargs):
                nonlocal attempted
                if not attempted:
                    attempted = True
                    raise ReadError("timeout", "The read timed out.")
                return method(*args, **kwargs)

            return read

        with (
            patch.object(DemoReads, "order", delay_once(DemoReads.order)),
            patch.object(DemoReads, "policies", delay_once(DemoReads.policies)),
            patch.object(DemoReads, "line", delay_once(DemoReads.line)),
            patch.object(DemoReads, "refunds", side_effect=AssertionError("A read beyond the budget was attempted.")) as refunds,
        ):
            result = self.investigation("CP-0104")
        self.assertEqual(result["state"], "escalated")
        self.assertIsNone(result["proposal"])
        reads = [event for event in result["history"] if event["operation"] != "replay.decision"]
        self.assertEqual(len(reads), 6)
        self.assertEqual([event["attempt"] for event in reads], [1, 2, 1, 2, 1, 2])
        self.assertEqual([event["status"] for event in reads], ["error", "ok"] * 3)
        refunds.assert_not_called()
        self.assert_no_sandbox_actions()

    def test_sc11_malformed_money_or_customer_in_read_result_fails_closed(self):
        original = self.stored_order("O100")
        no_currency = {key: value for key, value in original.items() if key != "currency"}
        malformed = {
            "missing currency": no_currency,
            "unsupported currency": {**original, "currency": "EUR"},
            "string amount": {**original, "paid_cents": "8000"},
            "floating point amount": {**original, "paid_cents": 8000.25},
            "negative amount": {**original, "paid_cents": -1},
            "wrong customer": {**original, "customer_id": "C200"},
        }
        for defect, order in malformed.items():
            with self.subTest(defect=defect):
                self.update_order("O100", order)
                response = self.client.get("/demo/orders/O100", headers=self.support)
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json()["detail"]["code"], "invalid_data")
                self.assertNotIn("C200", response.text)
                result = self.investigation("CP-0100")
                self.assertEqual(result["state"], "escalated")
                self.assertIsNone(result["order"])
                self.assertIsNone(result["proposal"])
                self.review("CP-0100", "prepare", expected=409)
        self.assert_no_sandbox_actions()

    def test_sc14_customer_message_does_not_change_scope_or_authorize_action(self):
        with patch("socket.create_connection", side_effect=AssertionError("Unexpected outbound connection.")) as outbound:
            result = self.investigation("CP-0114")
            response = self.client.post("/demo/cases/CP-0114/review", headers=self.support, json={"action": "prepare"})
            self.assertEqual(response.status_code, 401)
            self.review("CP-0114", "execute", expected=409, revision=1, idempotency_key="fixture-request-14")
        outbound.assert_not_called()
        self.assertIn("O900", result["request"])
        safe_result = json.dumps({key: value for key, value in result.items() if key != "request"})
        self.assertNotIn("O900", safe_result)
        self.assertNotIn("C200", safe_result)
        self.assertNotIn(SUPPORT_TOKEN, json.dumps(result))
        self.assertNotIn(REVIEWER_TOKEN, json.dumps(result))
        self.assertEqual(result["state"], "awaiting_review")
        self.assertEqual(result["proposal"]["order_id"], "O514")
        self.assert_no_sandbox_actions()

    def test_sc15_adversarial_passages_are_retrieved_but_cannot_support_action(self):
        with patch("socket.create_connection", side_effect=AssertionError("Unexpected outbound connection.")) as outbound:
            response = self.client.get("/demo/cases/CP-0115/policies", headers=self.support)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "missing")
            result = self.investigation("CP-0115")
            self.review("CP-0115", "prepare", expected=409)
        outbound.assert_not_called()
        self.assertEqual(result["evidence"], response.json()["passages"])
        self.assertEqual({item["source_id"] for item in result["evidence"]}, {"KB90", "KB91"})
        self.assertTrue(all(item["source_kind"] == "adversarial_fixture" for item in result["evidence"]))
        self.assertTrue(any("fixture-sink.invalid" in item["excerpt"] for item in result["evidence"]))
        self.assertEqual(result["state"], "escalated")
        self.assertIsNone(result["proposal"])
        self.assert_no_sandbox_actions()

    def test_sc17_an_existing_refund_blocks_an_overlapping_replacement(self):
        prepared = self.review("CP-0117", "prepare")["proposal"]
        approved = self.review("CP-0117", "approve", revision=prepared["revision"])["proposal"]
        self.assertEqual(approved["state"], "approved")
        order = self.stored_order("O117")
        order["refund_entries"] = [{"line_id": "A", "amount_cents": 500, "status": "verified"}]
        self.update_order("O117", order)
        result = self.investigation("CP-0117")
        self.assertEqual(result["state"], "escalated")
        self.assertIsNone(result["proposal"])
        self.assertEqual(self.review("CP-0117", "execute", revision=approved["revision"],
                                     idempotency_key=approved["idempotency_key"])["proposal"]["state"], "invalidated")
        self.assert_no_sandbox_actions()

    def test_sc18_replacement_waits_for_shipment_check(self):
        result = self.investigation("CP-0118-C")
        self.assertTrue(any(event["operation"] == "shipment.lookup" for event in result["history"]))
        self.assertEqual(result["state"], "awaiting_information")
        self.assertIsNone(result["proposal"])
        self.review("CP-0118-C", "prepare", expected=409)
        self.assert_no_sandbox_actions()


if __name__ == "__main__":
    unittest.main()
