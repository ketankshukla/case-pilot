import json
import sqlite3
import unittest
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from casepilot.app import create_app
from casepilot.database import FIXTURE_VERSION, reset_fixture_database, upgrade_fixture_database
from casepilot.investigation import investigate
from casepilot.preview import app as hosted_preview_app


DEMO_TOKEN = "fixture-demo-token"
REVIEWER_TOKEN = "fixture-audit-reviewer-placeholder-at-least-32"


class AuditTrailTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "audit.sqlite3"
        reset_fixture_database(self.path)
        self.enterContext(patch.dict("os.environ", {
            "CASEPILOT_DEMO_TOKEN": DEMO_TOKEN,
            "CASEPILOT_REVIEWER_TOKEN": REVIEWER_TOKEN,
        }))
        self.client = self.enterContext(TestClient(create_app(self.path), base_url="http://127.0.0.1"))
        self.support = {"Authorization": f"Bearer {DEMO_TOKEN}"}
        self.reviewer = {"Authorization": f"Bearer {REVIEWER_TOKEN}"}

    @staticmethod
    def route(case_id):
        return f"/demo/cases/{case_id}/review"

    def saved(self, case_id):
        response = self.client.get(self.route(case_id), headers=self.support)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def post(self, case_id, action, **fields):
        response = self.client.post(self.route(case_id), headers=self.reviewer, json={"action": action, **fields})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def execute(self, case_id, simulation):
        proposal = self.post(case_id, "prepare")["proposal"]
        self.post(case_id, "approve", revision=proposal["revision"])
        request = {"revision": proposal["revision"], "idempotency_key": proposal["idempotency_key"]}
        return self.post(case_id, "execute", **request, simulation=simulation)

    def test_sc01_saves_the_run_that_prepared_the_proposal_once(self):
        self.assertEqual(self.saved("CP-0100")["runs"], [])
        with patch("casepilot.sandbox.investigate", wraps=investigate) as replay:
            prepared = self.post("CP-0100", "prepare")
            self.assertEqual(self.post("CP-0100", "prepare")["runs"], prepared["runs"])
            replay.assert_called_once()
        saved = self.saved("CP-0100")
        self.assertEqual(saved["scenario_id"], "SC01")
        self.assertEqual(len(saved["runs"]), 1)
        run = saved["runs"][0]
        self.assertEqual(run["case_id"], "CP-0100")
        self.assertEqual(run["actor"], "demo-reviewer-c100")
        self.assertEqual(run["proposal_revision"], saved["proposal"]["revision"])
        self.assertEqual(run["order_version"], saved["proposal"]["payload"]["order_version"])
        self.assertEqual(run["evidence"], saved["proposal"]["payload"]["policy_versions"])
        self.assertEqual(run["fixture_version"], FIXTURE_VERSION)
        self.assertEqual((run["mode"], run["provider_calls"]), ("replay", 0))
        self.assertGreaterEqual(run["latency_ms"], 0)
        self.assertEqual(run["tools"][-1]["operation"], "replay.decision")
        self.assertEqual(self.saved("CP-0103")["runs"], [])

    def test_sc05_saves_paused_runs_without_preparing_actions(self):
        for _ in range(2):
            snapshot = self.post("CP-0105", "record_run")
        self.assertIsNone(snapshot["proposal"])
        self.assertEqual(snapshot["events"], [])
        self.assertEqual(len(snapshot["runs"]), 2)
        self.assertNotEqual(snapshot["runs"][0]["run_id"], snapshot["runs"][1]["run_id"])
        self.assertTrue(all(run["proposal_revision"] is None for run in snapshot["runs"]))
        self.assertTrue(all(run["state"] == "awaiting_information" for run in snapshot["runs"]))
        self.assertTrue(all(run["order_version"] is None for run in snapshot["runs"]))
        self.assertEqual(self.saved("CP-0105")["runs"], snapshot["runs"])

    def test_sc06_audit_writes_require_reviewer_and_reads_are_case_scoped(self):
        path = self.route("CP-0100")
        response = self.client.post(path, headers=self.support, json={"action": "record_run"})
        self.assertEqual(response.status_code, 401)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 401)
        with closing(sqlite3.connect(self.path)) as db, db:
            other = json.loads(db.execute("SELECT record FROM cases WHERE case_id = 'CP-0100'").fetchone()[0])
            other.update(case_id="CP-0900", customer_id="C200", order_id="O900")
            db.execute("INSERT INTO cases VALUES (?, ?, ?, ?)", ("CP-0900", "C200", "O900", json.dumps(other)))
        self.assertEqual(self.client.get(self.route("CP-0900"), headers=self.support).status_code, 404)
        response = self.client.post(self.route("CP-0900"), headers=self.reviewer, json={"action": "record_run"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.saved("CP-0100")["runs"], [])
        with TestClient(hosted_preview_app, base_url="https://binding.example.test") as hosted:
            self.assertEqual(hosted.get(path, headers=self.support).status_code, 404)
            response = hosted.post(path, headers=self.reviewer, json={"action": "record_run"})
            self.assertEqual(response.status_code, 405)

    def test_sc13_tracks_uncertainty_and_verification_with_same_operation(self):
        uncertain = self.execute("CP-0113", "timeout_after_commit")
        execution = uncertain["proposal"]["execution"]
        self.assertIsNone(execution["receipt"])
        key = uncertain["proposal"]["idempotency_key"]
        fingerprint = sha256(key.encode()).hexdigest()[:12]
        self.assertEqual(uncertain["events"][-1]["before_state"], "executing")
        self.assertEqual(uncertain["events"][-1]["after_state"], "uncertain")
        result = self.post("CP-0113", "reconcile", execution_id=execution["execution_id"])
        event = result["events"][-1]
        self.assertEqual(event["operation"], "execution.verified")
        self.assertEqual(event["before_state"], "uncertain")
        self.assertEqual(event["after_state"], "completed")
        self.assertEqual(event["execution_id"], execution["execution_id"])
        self.assertEqual(event["revision"], result["proposal"]["revision"])
        self.assertEqual(event["idempotency_identity"], fingerprint)
        self.assertNotIn(key, json.dumps(result["events"]))
        self.assertEqual(result, self.saved("CP-0113"))

    def test_sc14_audit_excludes_raw_request_and_masks_credentials(self):
        request = "Raw customer note must be excluded from audit."

        def replay_with_notes(db, case, clock):
            result = investigate(db, case, clock)
            result.request = request
            result.decision_summary = f"Protect {DEMO_TOKEN}"
            result.history[0].detail = f"Protect Bearer {REVIEWER_TOKEN}"
            return result

        with patch("casepilot.sandbox.investigate", side_effect=replay_with_notes):
            saved = self.post("CP-0100", "record_run")
        self.assertEqual(saved["runs"][0]["decision_summary"], "Protect [redacted]")
        self.assertEqual(saved["runs"][0]["tools"][0]["detail"], "Protect [redacted]")
        with closing(sqlite3.connect(self.path)) as db:
            stored = db.execute("SELECT snapshot FROM sandbox_runs").fetchone()[0]
        for secret in (request, DEMO_TOKEN, REVIEWER_TOKEN):
            self.assertNotIn(secret, stored)

    def test_sc01_upgrade_preserves_receipt_history_and_current_order_version(self):
        before = self.execute("CP-0100", "normal")
        with closing(sqlite3.connect(self.path)) as db, db:
            # Model a v3 database with a completed action, without the v4 audit table or a new fixture case.
            original_order = db.execute("SELECT record FROM orders WHERE order_id = 'O100'").fetchone()[0]
            db.execute("DROP TABLE sandbox_runs")
            db.execute("DELETE FROM cases WHERE case_id = 'CP-0105-B'")
            db.execute("UPDATE fixture_metadata SET fixture_version = 'stage1-v3'")
        self.assertEqual(upgrade_fixture_database(self.path)["fixture_version"], FIXTURE_VERSION)
        after = self.saved("CP-0100")
        self.assertEqual(after["proposal"], before["proposal"])
        self.assertEqual(after["events"], before["events"])
        self.assertEqual(after["runs"], [])
        self.assertEqual(self.saved("CP-0105-B")["scenario_id"], "SC05")
        self.post("CP-0100", "record_run")
        recorded = self.saved("CP-0100")
        self.assertEqual(upgrade_fixture_database(self.path)["fixture_version"], FIXTURE_VERSION)
        self.assertEqual(self.saved("CP-0100"), recorded)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT record FROM orders WHERE order_id = 'O100'").fetchone()[0], original_order)


if __name__ == "__main__":
    unittest.main()
