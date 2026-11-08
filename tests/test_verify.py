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


if __name__ == "__main__":
    unittest.main()
