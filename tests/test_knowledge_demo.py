import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from forecast_swarm.demo import load_cases, run_demo
from forecast_swarm.evidence import chain_deadlines, order_commitment
from forecast_swarm.knowledge_demo import (
    CONSENT_FIXTURE, RECEIPT_SCHEMA, RECEIPT_SCHEMA_V2, SNAPSHOT_SCHEMA, build_integration, run,
    simulation_receipts, validate_chain_snapshot, validate_receipts,
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

    def test_sandbox_receipts_label_the_paid_page_and_leave_others_simulated(self):
        result, _ = self.scenario_and_receipt("valid_wrong")
        digest = result["delivery"]["sha256"]
        sandbox = {"schema_version": RECEIPT_SCHEMA, "mode": "LOCAL_NEAR_SANDBOX",
                   "jobs": [{"job_id": "0", "artifact_sha256": digest, "customer": "c.test.near",
                             "worker": "w.test.near", "status": "PAID", "transaction_ids": ["test-only-tx"]}]}
        with tempfile.TemporaryDirectory(dir=os.path.realpath(tempfile.gettempdir())) as tmp:
            base = Path(tmp)
            receipts_path = base / "receipts.json"
            receipts_path.write_text(json.dumps(sandbox), encoding="utf-8")
            consent_path = base / "consent.json"
            consent_path.write_text(json.dumps(grant_for(digest)), encoding="utf-8")
            sidecar = run(base / "sandbox", receipts=receipts_path, consent=consent_path)
            claim_id = sidecar["receipts"][0]["claim_id"]
            pages = {p.name: p.read_text(encoding="utf-8") for p in (base / "sandbox" / "encyclopedia").glob("*.html")}
            for name in (f"{claim_id}.html", f"{claim_id}-v1.html"):
                self.assertIn("Customer acceptance · local NEAR Sandbox receipt<strong>PAID · job 0 · 1 tx</strong>", pages[name])
                self.assertNotIn("Customer acceptance · simulation", pages[name])
                self.assertNotIn("<strong>NOT_REQUESTED</strong>", pages[name])
            # The stored record keeps the replayed simulator state; only the card changes.
            claim_json = json.loads((base / "sandbox" / "encyclopedia" / f"{claim_id}.json").read_text(encoding="utf-8"))
            self.assertEqual([v["snapshot"]["customer_acceptance"] for v in claim_json["versions"]],
                             ["NOT_REQUESTED", "ACCEPTED"])
            others = [text for name, text in pages.items() if not name.startswith(claim_id) and name != "index.html"]
            self.assertTrue(others)
            self.assertTrue(all("Customer acceptance · simulation" in text for text in others))
            run(base / "simulated", consent=CONSENT_FIXTURE)
            simulated = (base / "simulated" / "encyclopedia" / f"{claim_id}.html").read_text(encoding="utf-8")
            self.assertIn("Customer acceptance · simulation<strong>ACCEPTED</strong>", simulated)
            self.assertNotIn("Sandbox receipt", simulated)

    def test_export_files_are_deterministic_and_have_landing_links(self):
        result, _ = self.scenario_and_receipt("valid_wrong")
        with tempfile.TemporaryDirectory(dir=os.path.realpath(tempfile.gettempdir())) as tmp:
            base = Path(tmp)  # exporters refuse symlinked paths (macOS /var)
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


CONTRACT = "escrow.testnet"
CUSTOMER, WORKER = "customer.testnet", "worker.testnet"


class NearTestnetTests(unittest.TestCase):
    def setUp(self):
        case = copy.deepcopy(next(c for c in load_cases() if c["scenario"] == "valid_wrong"))
        case["terms"]["job_id"] = "fes-testnet-a"
        case["outcome"] = None
        self.report = run_demo(cases=[case])
        delivery = self.report["scenarios"][0]["delivery"]
        self.digest = delivery["sha256"]
        self.terms = delivery["content"]["inputs"]["terms"]
        self.order = order_commitment(self.terms)
        self.job = {"id": 7, "customer": CUSTOMER, "worker": WORKER, "reward": "1000", "order_sha256": self.order,
                    **chain_deadlines(self.terms), "artifact_sha256": self.digest, "status": "ACCEPTED",
                    "pending_attempt_id": None, "publication_consent": True}
        self.snapshot = {"schema_version": SNAPSHOT_SCHEMA, "network": "testnet", "contract_id": CONTRACT,
                         "rpc_url": "https://rpc.testnet.example", "captured_at": "2026-11-09T10:00:00Z",
                         "block_height": 123, "block_hash": "blockhash", "config": {}, "jobs": {"7": self.job}}
        self.receipts = {"schema_version": RECEIPT_SCHEMA_V2, "mode": "NEAR_TESTNET", "network": "testnet",
                         "contract_id": CONTRACT,
                         "jobs": [{"job_id": "fes-testnet-a", "artifact_sha256": self.digest, "customer": CUSTOMER,
                                   "worker": WORKER, "status": "PAID", "transaction_ids": ["tx1", "tx2"],
                                   "chain_job_id": 7, "order_sha256": self.order}]}

    def build(self, receipts=None, snapshot=None, **kw):
        return build_integration(self.report, self.receipts if receipts is None else receipts,
                                 kw.get("consent"), self.snapshot if snapshot is None else snapshot)

    def test_paid_with_onchain_consent_publishes_one_claim(self):
        records, sidecar = self.build()
        self.assertEqual(len(sidecar["receipts"]), 1)
        self.assertEqual(sidecar["receipt_mode"], "NEAR_TESTNET")
        self.assertEqual((sidecar["network"], sidecar["contract_id"], sidecar["snapshot_block_height"],
                          sidecar["snapshot_block_hash"], sidecar["snapshot_captured_at"]),
                         ("testnet", CONTRACT, 123, "blockhash", "2026-11-09T10:00:00Z"))
        self.assertIn("one RPC node", sidecar["notice"])
        self.assertEqual(sidecar["receipts"][0]["chain_job_id"], 7)
        record = next(r for r in records if r["id"] == sidecar["receipts"][0]["claim_id"])
        self.assertTrue(record["publication"]["allowed"])
        self.assertEqual(record["publication"]["consent"]["by"], CUSTOMER)

    def test_label_and_page_text(self):
        with tempfile.TemporaryDirectory(dir=os.path.realpath(tempfile.gettempdir())) as tmp:
            base = Path(tmp)
            core = base / "core.json"
            core.write_text(json.dumps(self.report), encoding="utf-8")
            rp, sp = base / "r.json", base / "s.json"
            rp.write_text(json.dumps(self.receipts), encoding="utf-8")
            sp.write_text(json.dumps(self.snapshot), encoding="utf-8")
            sidecar = run(base / "out", core_report=core, receipts=rp, chain_snapshot=sp)
            claim = sidecar["receipts"][0]["claim_id"]
            page = (base / "out" / "encyclopedia" / f"{claim}.html").read_text(encoding="utf-8")
            self.assertIn("Customer acceptance · NEAR testnet receipt<strong>PAID · chain job 7 · 2 tx</strong>", page)
            index = (base / "out" / "index.html").read_text(encoding="utf-8")
            self.assertIn("checked against NEAR testnet contract state", index)
            self.assertIn("Synthetic data, scripted roles, private by default.", index)
            self.assertNotIn("local runner assertion", index)
            with self.assertRaisesRegex(ValueError, "chain snapshot"):
                run(base / "out2", core_report=core, receipts=rp)

    def test_no_onchain_consent_stays_private(self):
        self.job["publication_consent"] = False
        _, sidecar = self.build()
        self.assertEqual(sidecar["receipts"], [])

    def test_consent_file_and_missing_snapshot_rejected(self):
        with self.assertRaisesRegex(ValueError, "comes from the chain"):
            self.build(consent={self.digest: {"allowed": True, "consent": {}}})
        with self.assertRaisesRegex(ValueError, "require a chain snapshot"):
            build_integration(self.report, self.receipts)

    def test_chain_mismatches_rejected(self):
        def mutate(**changes):
            self.setUp()
            self.job.update(changes)
            return self.build
        with self.assertRaisesRegex(ValueError, "contract"):
            self.build(snapshot={**self.snapshot, "contract_id": "other.testnet"})
        with self.assertRaisesRegex(ValueError, "not ACCEPTED"):
            mutate(status="DELIVERED")()
        with self.assertRaisesRegex(ValueError, "artifact hash"):
            mutate(artifact_sha256="a" * 64)()
        with self.assertRaisesRegex(ValueError, "customer"):
            mutate(customer="evil.testnet")()
        with self.assertRaisesRegex(ValueError, "worker"):
            mutate(worker="evil.testnet")()
        with self.assertRaisesRegex(ValueError, "Deadlines"):
            mutate(dispute_deadline_ms=self.job["dispute_deadline_ms"] + 1000)()
        self.setUp()
        self.snapshot["jobs"] = {}
        with self.assertRaisesRegex(ValueError, "not in the chain snapshot"):
            self.build()

    def test_order_hash_mismatch_rejected(self):
        fake = "b" * 64
        self.job["order_sha256"] = fake
        self.receipts["jobs"][0]["order_sha256"] = fake
        with self.assertRaisesRegex(ValueError, "Order hash"):
            self.build()
        self.setUp()
        self.job["order_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "order_sha256"):
            self.build()

    def test_refunded_receipt_matches_chain_and_publishes_nothing(self):
        self.job.update(status="REFUNDED", artifact_sha256=None)
        receipt = self.receipts["jobs"][0]
        receipt.update(status="REFUNDED", artifact_sha256=None)
        _, sidecar = self.build()
        self.assertEqual(sidecar["receipts"], [])
        self.job["status"] = "ACCEPTED"
        with self.assertRaisesRegex(ValueError, "REFUNDED"):
            self.build()

    def test_v2_receipt_structure(self):
        validate_receipts(self.receipts)
        def broken(edit):
            doc = copy.deepcopy(self.receipts)
            edit(doc)
            with self.assertRaises(ValueError):
                validate_receipts(doc)
        broken(lambda d: d["jobs"][0].pop("chain_job_id"))
        broken(lambda d: d["jobs"][0].update(chain_job_id=True))
        broken(lambda d: d["jobs"][0].update(chain_job_id=-1))
        broken(lambda d: d["jobs"][0].update(transaction_ids=[]))
        broken(lambda d: d["jobs"][0].update(order_sha256="XYZ"))
        broken(lambda d: d.update(network="mainnet"))
        broken(lambda d: d.update(contract_id=""))
        broken(lambda d: d.update(mode="SIMULATION"))
        broken(lambda d: d.update(schema_version=RECEIPT_SCHEMA))
        broken(lambda d: d.pop("network"))

        def duplicate(d):
            other = copy.deepcopy(d["jobs"][0])
            other.update(job_id="fes-other", artifact_sha256="d" * 64)
            d["jobs"].append(other)
        broken(duplicate)
        v1 = {"schema_version": RECEIPT_SCHEMA, "mode": "NEAR_TESTNET", "jobs": []}
        with self.assertRaises(ValueError):
            validate_receipts(v1)

    def test_snapshot_structure(self):
        self.assertIs(validate_chain_snapshot(self.snapshot), self.snapshot)
        def broken(edit):
            doc = copy.deepcopy(self.snapshot)
            edit(doc)
            with self.assertRaises(ValueError):
                validate_chain_snapshot(doc)
        broken(lambda d: d.update(network="mainnet"))
        broken(lambda d: d.update(schema_version="x"))
        broken(lambda d: d.update(captured_at="2026-11-09"))
        broken(lambda d: d.update(block_height=True))
        broken(lambda d: d.update(block_height=-1))
        broken(lambda d: d.update(block_hash=""))
        broken(lambda d: d.update(config=[]))
        broken(lambda d: d.pop("rpc_url"))
        broken(lambda d: d["jobs"].update({"x": d["jobs"]["7"]}))
        broken(lambda d: d["jobs"]["7"].update(id=8))
        broken(lambda d: d["jobs"]["7"].pop("status"))
        broken(lambda d: d["jobs"]["7"].update(publication_consent="yes"))

    def test_snapshot_rejected_for_other_modes_and_default_notice_unchanged(self):
        report = run_demo()
        with self.assertRaises(ValueError):
            build_integration(report, simulation_receipts(report), None, self.snapshot)
        with self.assertRaises(ValueError):
            build_integration(report, None, None, self.snapshot)
        _, sidecar = build_integration(report)
        self.assertEqual(sidecar["notice"], "Local runner assertion bound to the core delivery hash. This JSON is not a cryptographic payment proof or authenticated customer identity.")
        self.assertNotIn("network", sidecar)


if __name__ == "__main__":
    unittest.main()
