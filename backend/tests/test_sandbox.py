import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from casepilot.app import create_app
from casepilot.database import reset_fixture_database
from casepilot.preview import app as hosted_preview_app


DEMO_TOKEN = "fixture-support-token"
REVIEWER_TOKEN = "fixture-reviewer-placeholder-at-least-32"


class SandboxTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "demo.sqlite3"
        reset_fixture_database(self.path)
        self.enterContext(patch.dict("os.environ", {
            "CASEPILOT_DEMO_TOKEN": DEMO_TOKEN, "CASEPILOT_REVIEWER_TOKEN": REVIEWER_TOKEN,
        }))
        self.client = self.enterContext(TestClient(create_app(self.path), base_url="http://127.0.0.1"))
        self.support = {"Authorization": f"Bearer {DEMO_TOKEN}"}
        self.reviewer = {"Authorization": f"Bearer {REVIEWER_TOKEN}"}

    @staticmethod
    def route(case_id):
        return f"/demo/cases/{case_id}/review"

    def post(self, case_id, action, status=200, **fields):
        response = self.client.post(self.route(case_id), headers=self.reviewer, json={"action": action, **fields})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def saved(self, case_id):
        response = self.client.get(self.route(case_id), headers=self.support)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def prepare_and_approve(self, case_id):
        draft = self.post(case_id, "prepare")["proposal"]
        return self.post(case_id, "approve", revision=draft["revision"])["proposal"]

    def execute(self, case_id, proposal, simulation="normal", status=200):
        return self.post(case_id, "execute", status, revision=proposal["revision"],
                         idempotency_key=proposal["idempotency_key"], simulation=simulation)

    def rows(self, table):
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(f"SELECT * FROM {table}")]

    def update_order(self, order_id, modify):
        with closing(sqlite3.connect(self.path)) as db, db:
            order = json.loads(db.execute("SELECT record FROM orders WHERE order_id = ?", (order_id,)).fetchone()[0])
            modify(order)
            db.execute("UPDATE orders SET record = ? WHERE order_id = ?", (json.dumps(order), order_id))

    def test_sc01_exact_approval_then_verified_8000_cent_receipt(self):
        self.assertIsNone(self.saved("CP-0100")["proposal"])
        draft = self.post("CP-0100", "prepare")["proposal"]
        self.assertEqual(draft["state"], "awaiting_review")
        self.assertEqual(draft["payload"]["amount_cents"], 8000)
        self.execute("CP-0100", draft, status=409)
        approved = self.post("CP-0100", "approve", revision=draft["revision"])["proposal"]
        self.assertEqual(approved["state"], "approved")
        self.assertEqual(approved["review"]["reviewer_id"], "demo-reviewer-c100")
        self.assertEqual(approved["payload"], draft["payload"])
        self.assertIsNone(approved["execution"])
        self.assertEqual(self.rows("refund_ledger"), [])

        result = self.execute("CP-0100", approved)
        proposal = result["proposal"]
        self.assertEqual(proposal["state"], "completed")
        receipt = proposal["execution"]["receipt"]
        self.assertEqual((receipt["order_id"], receipt["amount_cents"], receipt["currency"]), ("O100", 8000, "USD"))
        self.assertEqual(receipt["execution_id"], self.rows("refund_ledger")[0]["execution_id"])
        self.assertTrue(receipt["verified_at"])
        self.assertEqual(self.saved("CP-0100")["proposal"]["execution"]["receipt"], receipt)
        self.assertTrue(any(event["actor"] == "demo-reviewer-c100" for event in result["events"]))

    def test_sc03_denial_records_reason_without_a_sandbox_action(self):
        draft = self.post("CP-0103", "prepare")["proposal"]
        denied = self.post("CP-0103", "deny", revision=draft["revision"], reason="Confirm the requested resolution first.")["proposal"]
        self.assertEqual(denied["state"], "denied")
        self.assertEqual(denied["review"]["reason"], "Confirm the requested resolution first.")
        self.assertEqual(denied["payload"], draft["payload"])
        self.execute("CP-0103", draft, status=409)
        self.assertIsNone(denied["execution"])
        self.assertEqual(self.rows("refund_ledger"), [])

    def test_sc04_edit_creates_a_fresh_exact_revision(self):
        draft = self.post("CP-0104", "prepare")["proposal"]
        self.assertEqual((draft["payload"]["amount_cents"], draft["payload"]["validation_status"]), (10000, "invalid"))
        self.post("CP-0104", "approve", 409, revision=draft["revision"])
        corrected = self.post("CP-0104", "edit", revision=draft["revision"], amount_cents=4000)["proposal"]
        self.assertEqual(corrected["revision"], draft["revision"] + 1)
        self.assertEqual((corrected["payload"]["amount_cents"], corrected["payload"]["line_id"]), (4000, "A"))
        self.assertIsNone(corrected["review"])
        self.post("CP-0104", "approve", 409, revision=draft["revision"])
        self.execute("CP-0104", corrected, status=409)
        approved = self.post("CP-0104", "approve", revision=corrected["revision"])["proposal"]
        result = self.execute("CP-0104", approved)["proposal"]
        self.assertEqual(result["execution"]["receipt"]["amount_cents"], 4000)
        original = min(self.rows("sandbox_proposals"), key=lambda row: row["revision"])
        self.assertEqual(json.loads(original["payload"])["amount_cents"], 10000)

    def test_sc06_reviewer_authority_and_scope_are_enforced_by_backend(self):
        for headers in ({}, self.support):
            with self.subTest(headers=bool(headers)):
                response = self.client.post(self.route("CP-0100"), headers=headers,
                                            json={"action": "prepare", "role": "reviewer"})
                self.assertEqual(response.status_code, 401)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO cases VALUES (?, ?, ?, ?)", ("CP-0900", "C200", "O900", "{}"))
        self.assertEqual(self.client.get(self.route("CP-0900"), headers=self.support).status_code, 404)
        self.assertNotIn("O900", json.dumps(self.post("CP-0900", "prepare", 404)))
        self.assertIsNone(self.saved("CP-0100")["proposal"])
        with patch.dict("os.environ", {"CASEPILOT_REVIEWER_TOKEN": DEMO_TOKEN}):
            response = self.client.post(self.route("CP-0100"), headers=self.support, json={"action": "prepare"})
            self.assertEqual(response.status_code, 503)

    def test_sc06_hosted_binding_cannot_access_review_or_execute(self):
        with TestClient(hosted_preview_app, base_url="https://binding.example.test") as hosted:
            self.assertEqual(hosted.get(self.route("CP-0100"), headers=self.support).status_code, 404)
            self.assertEqual(hosted.post(self.route("CP-0100"), headers=self.reviewer, json={"action": "prepare"}).status_code, 405)

    def test_sc06_reviewer_notes_redact_local_credentials(self):
        draft = self.post("CP-0103", "prepare")["proposal"]
        result = self.post("CP-0103", "deny", revision=draft["revision"], reason=f"Remove pasted key {REVIEWER_TOKEN}")
        self.assertEqual(result["proposal"]["review"]["reason"], "Remove pasted key [redacted]")
        self.assertNotIn(REVIEWER_TOKEN, json.dumps(self.rows("sandbox_reviews")))
        self.assertNotIn(REVIEWER_TOKEN, json.dumps(result["events"]))

    def test_sc08_changed_balance_invalidates_an_approved_proposal(self):
        approved = self.prepare_and_approve("CP-0100")

        def add_prior_refund(order):
            order.update(version=4, refund_entries=[{"amount_cents": 2000, "line_id": None, "status": "verified"}])

        self.update_order("O100", add_prior_refund)
        self.assertEqual(self.execute("CP-0100", approved)["proposal"]["state"], "invalidated")
        self.assertEqual(self.rows("refund_ledger"), [])
        revised = self.post("CP-0100", "prepare")["proposal"]
        self.assertEqual(revised["payload"]["amount_cents"], 6000)
        self.assertIsNone(revised["review"])

    def test_sc08_two_approved_cases_cannot_overspend_an_order(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            clone = json.loads(db.execute("SELECT record FROM cases WHERE case_id = 'CP-0100'").fetchone()[0])
            clone["case_id"] = "CP-0100-B"
            db.execute("INSERT INTO cases VALUES (?, ?, ?, ?)", ("CP-0100-B", "C100", "O100", json.dumps(clone)))
        cases = ("CP-0100", "CP-0100-B")
        approved = [self.prepare_and_approve(case_id) for case_id in cases]
        with ThreadPoolExecutor(max_workers=2) as pool:
            states = [result["proposal"]["state"] for result in pool.map(self.execute, cases, approved)]
        self.assertCountEqual(states, ["completed", "invalidated"])
        self.assertEqual(sum(row["amount_cents"] for row in self.rows("refund_ledger")), 8000)

    def test_sc09_invalid_edits_cannot_change_the_saved_amount(self):
        draft = self.post("CP-0109-B", "prepare")["proposal"]
        self.assertEqual(draft["payload"]["amount_cents"], 2000)
        for amount, status in ((-1, 422), (0, 422), (2000.5, 422), ("2000", 422), (2001, 409)):
            with self.subTest(status=status):
                self.post("CP-0109-B", "edit", status, revision=draft["revision"], amount_cents=amount)
        self.assertEqual(self.saved("CP-0109-B")["proposal"]["payload"]["amount_cents"], 2000)

    def test_sc12_retries_share_one_operation_and_changed_payload_is_rejected(self):
        approved = self.prepare_and_approve("CP-0100")
        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(self.execute, "CP-0100", approved) for _ in range(2)]
        execution_ids = {request.result()["proposal"]["execution"]["execution_id"] for request in requests}
        self.assertEqual(len(execution_ids), 1)
        original = self.saved("CP-0100")["proposal"]["execution"]["receipt"]
        retry = self.execute("CP-0100", approved)["proposal"]["execution"]["receipt"]
        self.assertEqual(retry, original)
        self.execute("CP-0100", approved, "reject_before_commit", 409)
        self.assertEqual(len(self.rows("refund_ledger")), 1)

    def test_sc11_mismatched_readback_cannot_verify_an_uncertain_refund(self):
        approved = self.prepare_and_approve("CP-0113")
        result = self.execute("CP-0113", approved, "timeout_after_commit")["proposal"]
        operation_id = result["execution"]["execution_id"]
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE refund_ledger SET amount_cents = amount_cents - 1 WHERE execution_id = ?", (operation_id,))
        checked = self.post("CP-0113", "reconcile", execution_id=operation_id)["proposal"]
        self.assertEqual(checked["state"], "uncertain")
        self.assertIsNone(checked["execution"]["receipt"])

    def test_sc13_reject_before_commit_is_failed_without_a_receipt(self):
        approved = self.prepare_and_approve("CP-0113")
        failed = self.execute("CP-0113", approved, "reject_before_commit")["proposal"]
        self.assertEqual(failed["state"], "failed")
        self.assertIsNone(failed["execution"]["receipt"])
        self.assertEqual(self.rows("refund_ledger"), [])

    def test_sc13_timeout_after_commit_reconciles_one_original_operation(self):
        approved = self.prepare_and_approve("CP-0113")
        uncertain = self.execute("CP-0113", approved, "timeout_after_commit")["proposal"]
        self.assertEqual(uncertain["state"], "uncertain")
        self.assertIsNone(uncertain["execution"]["receipt"])
        operation_id = uncertain["execution"]["execution_id"]
        self.assertEqual(self.rows("refund_ledger")[0]["execution_id"], operation_id)
        pending = self.client.get("/demo/orders/O113/refunds", headers=self.support).json()
        self.assertEqual(pending["pending_cents"], approved["payload"]["amount_cents"])
        self.assertEqual(pending["prior_refunded_cents"], 0)
        self.assertEqual(self.execute("CP-0113", approved, "timeout_after_commit")["proposal"]["state"], "uncertain")
        settled = self.post("CP-0113", "reconcile", execution_id=operation_id)["proposal"]
        self.assertEqual(settled["state"], "completed")
        receipt = settled["execution"]["receipt"]
        self.assertEqual(receipt["execution_id"], operation_id)
        retry = self.post("CP-0113", "reconcile", execution_id=operation_id)["proposal"]["execution"]["receipt"]
        self.assertEqual(receipt, retry)
        self.assertEqual(len(self.rows("refund_ledger")), 1)
        verified = self.client.get("/demo/orders/O113/refunds", headers=self.support).json()
        self.assertEqual(verified["prior_refunded_cents"], approved["payload"]["amount_cents"])
        self.assertEqual(verified["pending_cents"], 0)

    def test_sc13_unresolved_operation_reserves_the_balance(self):
        approved = self.prepare_and_approve("CP-0113")
        proposal = self.execute("CP-0113", approved, "unresolved")["proposal"]
        self.assertEqual(proposal["state"], "uncertain")
        operation_id = proposal["execution"]["execution_id"]
        outcome = self.post("CP-0113", "reconcile", execution_id=operation_id)["proposal"]
        self.assertEqual(outcome["state"], "uncertain")
        self.assertIsNone(outcome["execution"]["receipt"])
        self.assertEqual(outcome["execution"]["execution_id"], operation_id)
        balance = self.client.get("/demo/orders/O113/refunds", headers=self.support).json()
        self.assertEqual(balance["remaining_cents"], 0)
        self.assertEqual(balance["pending_cents"], approved["payload"]["amount_cents"])
        self.assertEqual(self.rows("refund_ledger"), [])

    def test_sc17_verified_replacement_creates_one_request_without_refund(self):
        approved = self.prepare_and_approve("CP-0117")
        proposal = self.execute("CP-0117", approved)["proposal"]
        receipt = proposal["execution"]["receipt"]
        self.assertEqual((receipt["remedy"], receipt["quantity"]), ("replacement", 1))
        self.assertEqual(self.rows("replacement_requests")[0]["execution_id"], receipt["execution_id"])
        self.assertEqual(self.rows("refund_ledger"), [])
        self.assertEqual(self.rows("sandbox_outbox"), [])

    def test_sc17_replacement_rechecks_current_stock(self):
        approved = self.prepare_and_approve("CP-0117")
        self.update_order("O117", lambda order: order["lines"][0].update(replacement_stock=0))
        self.assertEqual(self.execute("CP-0117", approved)["proposal"]["state"], "invalidated")
        self.assertEqual(self.rows("replacement_requests"), [])

    def test_sc18_unknown_status_uses_a_verified_local_outbox_draft(self):
        approved = self.prepare_and_approve("CP-0118")
        self.assertEqual(approved["payload"]["remedy"], "delay_update")
        self.assertIn("no verified delivery date", approved["payload"]["draft"])
        proposal = self.execute("CP-0118", approved)["proposal"]
        self.assertEqual(proposal["state"], "completed")
        stored = self.rows("sandbox_outbox")[0]
        self.assertEqual(stored["execution_id"], proposal["execution"]["receipt"]["execution_id"])
        self.assertEqual(stored["draft"], approved["payload"]["draft"])

    def test_sc18_delivered_state_invalidates_replacement_after_approval(self):
        approved = self.prepare_and_approve("CP-0118-B")
        self.update_order("O318", lambda order: order.update(shipment_status="delivered", delivered_on="2026-11-18"))
        self.assertEqual(self.execute("CP-0118-B", approved)["proposal"]["state"], "invalidated")
        self.assertEqual(self.rows("replacement_requests"), [])


if __name__ == "__main__":
    unittest.main()
