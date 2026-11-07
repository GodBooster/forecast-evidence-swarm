import copy
import json
import tempfile
import unittest
from pathlib import Path

from forecast_swarm.demo import run_demo
from forecast_swarm.knowledge_demo import (
    CONSENT_FIXTURE, RECEIPT_SCHEMA, build_integration, run,
    simulation_receipts,
)
from forecast_encyclopedia.model import load_json


def grant_for(digest):
    grants = load_json(CONSENT_FIXTURE.read_text(encoding="utf-8"))
    return {digest: grants[digest]}


class KnowledgeDemoTests(unittest.TestCase):
    def setUp(self):
        self.report = run_demo()
        self.receipts = simulation_receipts(self.report)

    def scenario_and_receipt(self, scenario):
        result = next(item for item in self.report["scenarios"] if item["scenario"] == scenario)
        receipt = next(item for item in self.receipts["jobs"]
                       if item["artifact_sha256"] == result["delivery"]["sha256"])
        return result, receipt

    def test_imported_claims_are_private_without_explicit_consent(self):
        records, sidecar = build_integration(self.report, self.receipts)
        imported = records[3:]
        self.assertTrue(imported)
        self.assertTrue(all(not record.get("publication", {}).get("allowed", False) for record in imported))
        self.assertEqual(sidecar["receipts"], [])
        self.assertIn("not a cryptographic payment proof", sidecar["notice"])

    def test_matching_paid_hash_and_explicit_consent_publish_accepted_claim(self):
        result, receipt = self.scenario_and_receipt("valid_wrong")
        self.assertEqual(receipt["status"], "PAID")
        records, sidecar = build_integration(self.report, self.receipts,
                                             grant_for(result["delivery"]["sha256"]))
        imported = records[3:]
        public = [record for record in imported if record.get("publication", {}).get("allowed", False)]
        self.assertEqual(len(public), 1)
        self.assertEqual(public[0]["versions"][-1]["snapshot"]["delivery_validity"], "VALID")
        self.assertEqual(public[0]["versions"][-1]["snapshot"]["customer_acceptance"], "ACCEPTED")
        self.assertEqual(sidecar["receipts"][0]["artifact_sha256"], result["delivery"]["sha256"])
        self.assertEqual(sidecar["receipts"][0]["claim_id"], public[0]["id"])
        self.assertEqual(sidecar["receipts"][0]["history_tip_sha256"], public[0]["versions"][-1]["sha256"])

    def test_refunded_job_is_not_published_even_with_consent(self):
        result, receipt = self.scenario_and_receipt("future_data")
        self.assertEqual(receipt["status"], "REFUNDED")
        records, sidecar = build_integration(self.report, self.receipts,
                                             grant_for(result["delivery"]["sha256"]))
        imported = records[3:]
        self.assertTrue(all(not record.get("publication", {}).get("allowed", False) for record in imported))
        self.assertEqual(sidecar["receipts"], [])

    def test_malformed_receipts_hash_mismatch_and_invalid_paid_artifact_rejected(self):
        malformed = copy.deepcopy(self.receipts)
        malformed["unexpected"] = 1
        with self.assertRaises(ValueError):
            build_integration(self.report, malformed)

        mismatch = copy.deepcopy(self.receipts)
        mismatch["jobs"][0]["artifact_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "does not match a core delivery"):
            build_integration(self.report, mismatch)

        result, receipt = self.scenario_and_receipt("future_data")
        forged = {"schema_version": RECEIPT_SCHEMA, "mode": "LOCAL_NEAR_SANDBOX",
                  "jobs": [{**receipt, "status": "PAID", "transaction_ids": ["sandbox-tx-1"]}]}
        with self.assertRaisesRegex(ValueError, "cannot publish an invalid"):
            build_integration(self.report, forged, grant_for(result["delivery"]["sha256"]))

    def test_receipt_rehash_or_job_id_does_not_substitute_for_hash_binding(self):
        result, receipt = self.scenario_and_receipt("valid_wrong")
        tampered = copy.deepcopy(receipt)
        tampered["artifact_sha256"] = "f" * 64
        doc = {"schema_version": RECEIPT_SCHEMA, "mode": "LOCAL_NEAR_SANDBOX", "jobs": [tampered]}
        with self.assertRaises(ValueError):
            build_integration(self.report, doc, grant_for(result["delivery"]["sha256"]))

        sandbox = copy.deepcopy(self.receipts)
        sandbox["mode"] = "LOCAL_NEAR_SANDBOX"
        sandbox["jobs"] = [copy.deepcopy(receipt)]
        with self.assertRaisesRegex(ValueError, "must include transaction IDs"):
            build_integration(self.report, sandbox)

        sandbox["jobs"][0]["transaction_ids"] = ["sandbox-tx-valid"]
        result, _ = self.scenario_and_receipt("valid_wrong")
        sandbox["jobs"][0]["artifact_sha256"] = result["delivery"]["sha256"]
        _, sidecar = build_integration(self.report, sandbox,
                                       grant_for(result["delivery"]["sha256"]))
        self.assertEqual(sidecar["receipt_mode"], "LOCAL_NEAR_SANDBOX")
        self.assertEqual(sidecar["receipts"][0]["transaction_ids"], ["sandbox-tx-valid"])

    def test_export_files_are_deterministic_and_have_landing_links(self):
        result, _ = self.scenario_and_receipt("valid_wrong")
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            base = Path(tmp)
            out_a, out_b = base / "demo-a", base / "demo-b"
            run(out_a, consent=CONSENT_FIXTURE)
            run(out_b, consent=CONSENT_FIXTURE)
            files_a = {p.relative_to(out_a).as_posix(): p.read_bytes()
                       for p in out_a.rglob("*") if p.is_file()}
            files_b = {p.relative_to(out_b).as_posix(): p.read_bytes()
                       for p in out_b.rglob("*") if p.is_file()}
            self.assertEqual(files_a, files_b)
            landing = files_a["index.html"].decode("utf-8")
            self.assertIn("encyclopedia/index.html", landing)
            self.assertIn("payment-provenance.json", landing)
            payload = json.loads(files_a["payment-provenance.json"])
            self.assertTrue(payload["receipts"])


if __name__ == "__main__":
    unittest.main()
