import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from forecast_swarm import walkthrough
from forecast_swarm.demo import run_demo
from forecast_swarm.knowledge_demo import RECEIPT_SCHEMA


def _hash(report, scenario):
    return next(item for item in report["scenarios"] if item["scenario"] == scenario)["delivery"]["sha256"]


class WalkthroughTests(unittest.TestCase):
    def test_default_walkthrough_passes_all_checks_with_simulation_receipts(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = str(Path(raw).resolve())  # macOS /var is a symlink; exporters refuse symlinked paths
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = walkthrough.main(["--out", tmp])
            self.assertEqual(code, 0)
            text = stdout.getvalue()
            self.assertIn("All walkthrough checks passed.", text)
            self.assertIn("no NEAR transfer occurred", text)
            summary = json.loads((Path(tmp) / "walkthrough.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["receipt_mode"], "SIMULATION")
            self.assertEqual(summary["evidence_checks"]["future_data"], "INVALID")
            self.assertEqual([v["outcome"] for v in summary["encyclopedia"]["versions"]], ["UNRESOLVED", "FINAL"])
            self.assertTrue((Path(tmp) / summary["encyclopedia"]["page"]).is_file())
            self.assertTrue((Path(tmp) / "core" / "report.html").is_file())

    def test_sandbox_style_receipts_publish_only_the_paid_delivery(self):
        report = run_demo()
        receipts = {
            "schema_version": RECEIPT_SCHEMA,
            "mode": "LOCAL_NEAR_SANDBOX",
            "jobs": [
                {"job_id": "0", "artifact_sha256": _hash(report, "valid_wrong"), "customer": "c.test.near",
                 "worker": "w.test.near", "status": "PAID", "transaction_ids": ["test-only-tx-1"]},
                {"job_id": "1", "artifact_sha256": _hash(report, "zero_successes"), "customer": "c2.test.near",
                 "worker": "w2.test.near", "status": "REFUNDED", "transaction_ids": ["test-only-tx-2"]},
            ],
        }
        with tempfile.TemporaryDirectory() as raw:
            tmp = str(Path(raw).resolve())  # macOS /var is a symlink; exporters refuse symlinked paths
            path = Path(tmp) / "receipts.json"
            path.write_text(json.dumps(receipts), encoding="utf-8")
            summary = walkthrough.build(Path(tmp) / "out", path)
        self.assertEqual(summary["receipt_mode"], "LOCAL_NEAR_SANDBOX")
        self.assertEqual(summary["public_paid_claims"], 1)
        self.assertEqual(summary["refunded_artifacts_kept_private"], [_hash(report, "zero_successes")])

    def test_unpaid_focus_delivery_fails_the_walkthrough(self):
        report = run_demo()
        receipts = {
            "schema_version": RECEIPT_SCHEMA,
            "mode": "SIMULATION",
            "jobs": [],
        }
        with tempfile.TemporaryDirectory() as raw:
            tmp = str(Path(raw).resolve())  # macOS /var is a symlink; exporters refuse symlinked paths
            path = Path(tmp) / "receipts.json"
            path.write_text(json.dumps(receipts), encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                code = walkthrough.main(["--out", str(Path(tmp) / "out"), "--receipts", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("PAID receipt", stderr.getvalue())
        self.assertTrue(report)


if __name__ == "__main__":
    unittest.main()
