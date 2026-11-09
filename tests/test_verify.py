import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from forecast_swarm import verify
from forecast_swarm.demo import run_demo


def _scenario(report, name):
    return next(item for item in report["scenarios"] if item["scenario"] == name)


class VerifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_demo()
        cls.valid = _scenario(cls.report, "valid_wrong")["delivery"]
        cls.invalid = _scenario(cls.report, "future_data")["delivery"]

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = verify.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_valid_bundle_matching_hash_passes_from_report_directory_and_bundle_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "report.json").write_text(json.dumps(self.report), encoding="utf-8")
            code, out, _ = self.run_cli("--bundle", str(base), "--expect-sha256", self.valid["sha256"])
            self.assertEqual(code, 0)
            self.assertIn("hash: MATCH", out)
            self.assertIn("delivery validity: VALID", out)
            self.assertIn("SAFE TO ACCEPT", out)

            bundle_path = base / "bundle.json"
            bundle_path.write_text(json.dumps(self.valid), encoding="utf-8")
            code, out, _ = self.run_cli("--bundle", str(bundle_path), "--expect-sha256", self.valid["sha256"].upper())
            self.assertEqual(code, 0)
            self.assertIn("hash: MATCH", out)

    def test_wrong_expected_hash_fails(self):
        other = self.invalid["sha256"]
        with tempfile.TemporaryDirectory() as tmp:
            bundle_path = Path(tmp) / "bundle.json"
            bundle_path.write_text(json.dumps(self.valid), encoding="utf-8")
            code, out, _ = self.run_cli("--bundle", str(bundle_path), "--expect-sha256", other)
            self.assertEqual(code, 1)
            self.assertIn("hash: MISMATCH", out)
            self.assertIn("DO NOT ACCEPT", out)

            report_path = Path(tmp) / "report.json"
            report_path.write_text(json.dumps(self.report), encoding="utf-8")
            code, _, err = self.run_cli("--bundle", str(report_path), "--expect-sha256", "0" * 64)
            self.assertEqual(code, 1)
            self.assertIn("No delivery in the report carries the expected sha256", err)

    def test_tampered_or_invalid_bundle_fails_even_with_its_own_hash(self):
        tampered = copy.deepcopy(self.valid)
        tampered["content"]["roles"]["analyst"]["probability_bps"] = 9900
        ok, lines = verify.verify(tampered, tampered["sha256"])
        self.assertFalse(ok)
        self.assertTrue(any(line.startswith("replay: FAILED") for line in lines))

        ok, lines = verify.verify(self.invalid, self.invalid["sha256"])
        self.assertFalse(ok)
        self.assertIn("hash: MATCH", lines)
        self.assertIn("delivery validity: INVALID", lines)
        self.assertIn("result: DO NOT ACCEPT", lines)

    def test_malformed_arguments_and_files_are_rejected(self):
        with self.assertRaises(SystemExit):
            self.run_cli("--bundle", "x.json", "--expect-sha256", "not-a-hash")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "odd.json"
            path.write_text(json.dumps({"unrelated": True}), encoding="utf-8")
            code, _, err = self.run_cli("--bundle", str(path), "--expect-sha256", self.valid["sha256"])
            self.assertEqual(code, 1)
            self.assertIn("neither a bundle", err)
            code, _, err = self.run_cli("--bundle", str(Path(tmp) / "missing"), "--expect-sha256", self.valid["sha256"])
            self.assertEqual(code, 1)
            self.assertIn("VERIFY FAILED", err)


class FakeRpc:
    """Stands in for near_rpc.NearRpc; returns one recorded get_job view."""
    rpc_url = "https://rpc.example.invalid"

    def __init__(self, job, error=None):
        self.job, self.error, self.calls = job, error, []

    def __call__(self, network="testnet", rpc_url=None):
        return self

    def view(self, contract_id, method, args=None):
        self.calls.append((contract_id, method, args))
        if self.error:
            raise RuntimeError(self.error)
        return {"value": self.job, "block_height": 7, "block_hash": "blockhash", "logs": []}


class ChainModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from forecast_swarm.evidence import chain_deadlines, order_commitment
        cls.bundle = _scenario(run_demo(), "valid_wrong")["delivery"]
        terms = cls.bundle["content"]["inputs"]["terms"]
        cls.order = order_commitment(terms)
        cls.job = {"id": 3, "customer": "customer.testnet", "worker": "worker.testnet", "reward": "1",
                   "order_sha256": cls.order, **chain_deadlines(terms),
                   "artifact_sha256": cls.bundle["sha256"], "status": "SUBMITTED",
                   "pending_attempt_id": None, "publication_consent": False}

    def run_chain(self, job, *extra, error=None, bundle=None):
        rpc = FakeRpc(job, error)
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.json"
            path.write_text(json.dumps(self.bundle if bundle is None else bundle), encoding="utf-8")
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = verify.main(["--bundle", str(path), "--near-contract", "escrow.testnet",
                                    "--job-id", "3", *extra], rpc_factory=rpc)
        return code, out.getvalue(), err.getvalue(), rpc

    def test_chain_mode_reads_the_job_and_accepts_only_the_ordered_delivery(self):
        code, out, _, rpc = self.run_chain(self.job)
        self.assertEqual(code, 0)
        self.assertEqual(rpc.calls, [("escrow.testnet", "get_job", {"id": 3})])
        for text in ("chain status: SUBMITTED", "hash: MATCH", "order vs chain: MATCH",
                     "deadlines vs chain: MATCH", "SAFE TO ACCEPT (bytes match the committed hash and the order"):
            self.assertIn(text, out)

    def test_a_valid_delivery_for_a_different_order_is_rejected(self):
        code, out, _, _ = self.run_chain({**self.job, "order_sha256": "0" * 64})
        self.assertEqual(code, 1)
        self.assertIn("order vs chain: MISMATCH", out)
        self.assertIn("DO NOT ACCEPT", out)
        code, out, _, _ = self.run_chain({**self.job, "delivery_deadline_ms": self.job["delivery_deadline_ms"] + 1})
        self.assertEqual(code, 1)
        self.assertIn("deadlines vs chain: MISMATCH (delivery_deadline_ms)", out)

    def test_chain_hash_mismatch_missing_job_and_rpc_failure_fail_closed(self):
        code, _, err, _ = self.run_chain({**self.job, "artifact_sha256": "1" * 64})
        self.assertEqual(code, 1)
        code, _, err, _ = self.run_chain({**self.job, "artifact_sha256": None})
        self.assertEqual(code, 1)
        self.assertIn("no submitted artifact hash", err)
        code, _, err, _ = self.run_chain(None)
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)
        code, _, err, _ = self.run_chain(self.job, error="node unreachable")
        self.assertEqual(code, 1)
        self.assertIn("Cannot read job 3", err)
        code, _, err, _ = self.run_chain(self.job, "--expect-sha256", "2" * 64)
        self.assertEqual(code, 1)
        self.assertIn("differs from the artifact hash stored on chain", err)

    def test_expected_order_hash_works_offline_and_flags_are_validated(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.json"
            path.write_text(json.dumps(self.bundle), encoding="utf-8")
            base = ["--bundle", str(path), "--expect-sha256", self.bundle["sha256"]]
            with contextlib.redirect_stdout(out):
                self.assertEqual(verify.main(base + ["--expect-order-sha256", self.order]), 0)
                self.assertEqual(verify.main(base + ["--expect-order-sha256", "f" * 64]), 1)
            self.assertIn("order: MATCH", out.getvalue())
            self.assertIn("order: MISMATCH", out.getvalue())
            with contextlib.redirect_stderr(io.StringIO()):
                for bad in (["--bundle", str(path)], ["--bundle", str(path), "--job-id", "1"],
                            ["--bundle", str(path), "--near-contract", "escrow.testnet"]):
                    with self.assertRaises(SystemExit):
                        verify.main(bad)


if __name__ == "__main__":
    unittest.main()
