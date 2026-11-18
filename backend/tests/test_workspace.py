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

    def case(self, scenario_id):
        response = self.client.get("/demo/workspace", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        return next(case for case in response.json()["cases"] if case["scenario_id"] == scenario_id)

    def test_sc01_preview_loads_full_refund_without_ledger_write(self):
        case = self.case("SC01")
        self.assertEqual(case["state"], "awaiting_review")
        self.assertEqual(case["order"]["order_id"], "O100")
        self.assertEqual(case["order"]["version"], 3)
        self.assertEqual(case["proposal"]["amount_cents"], 8000)
        self.assertEqual(case["proposal"]["currency"], "USD")
        self.assertEqual([(item["source_id"], item["version"]) for item in case["evidence"]], [("KB01", 1), ("KB04", 1)])
        self.case("SC01")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM refund_ledger").fetchone()[0], 0)

    def test_sc05_preview_pauses_with_no_order_or_proposal(self):
        case = self.case("SC05")
        self.assertEqual(case["state"], "awaiting_information")
        self.assertTrue(case["missing_information"])
        self.assertIsNone(case["order"])
        self.assertIsNone(case["proposal"])

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

    def test_sc18_preview_shows_unknown_shipment_and_no_eta_or_proposal(self):
        case = self.case("SC18")
        facts = {fact["label"]: fact["value"] for fact in case["order"]["facts"]}
        self.assertEqual(facts["Shipment status"], "Unknown")
        self.assertEqual(facts["Promised for"], "2026-11-10 (8 days ago)")
        self.assertNotIn("Estimated delivery", facts)
        self.assertIsNone(case["proposal"])

    def test_sc01_hosted_preview_uses_packaged_fixtures_and_rejects_writes(self):
        workspace_path = "/demo/workspace"
        binding_host = "https://binding.example.test"
        self.assertEqual(self.client.get(f"{binding_host}{workspace_path}", headers=self.headers).status_code, 400)
        with TestClient(hosted_preview_app, base_url=binding_host) as client:
            self.assertEqual(client.get(workspace_path).status_code, 401)
            workspace = client.get(workspace_path, headers=self.headers)
            self.assertEqual(workspace.status_code, 200)
            self.assertEqual(workspace.json()["fixture_version"], "stage1-v1")
            self.assertEqual(workspace.json()["cases"][0]["proposal"]["amount_cents"], 8000)
            self.assertEqual(client.post(workspace_path, headers=self.headers).status_code, 405)


if __name__ == "__main__":
    unittest.main()
