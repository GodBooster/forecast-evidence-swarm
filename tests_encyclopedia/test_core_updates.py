"""Contract tests for actual core generation and repeated report imports."""
import contextlib
import copy
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

from forecast_encyclopedia.adapter import adapt_report, update_core_history
from forecast_encyclopedia.demo import load_demo
from forecast_encyclopedia.model import canonical
from forecast_encyclopedia.render import build_files
from forecast_swarm.demo import run_demo
from forecast_swarm.evidence import quality

ROOT = Path(__file__).resolve().parent.parent


class CoreUpdateTests(unittest.TestCase):
    def setUp(self):
        full = run_demo()
        self.report = {**full, "scenarios": [next(r for r in full["scenarios"] if r["scenario"] == "unresolved")]}
        self.key = self.report["scenarios"][0]["delivery"]["sha256"]
        self.grants = {self.key: load_demo()[0]["publication"]}
        self.prior = adapt_report(self.report, self.grants)

    def resolved_report(self):
        report = copy.deepcopy(self.report)
        row = report["scenarios"][0]
        evaluation = row["evaluation"]
        evaluation["as_of"] = "2026-11-05T12:00:00Z"
        evaluation["outcome"] = {"source": row["delivery"]["content"]["inputs"]["terms"]["source"], "value": 0, "final": True, "resolved_at": "2026-11-04T12:00:00Z", "available_at": "2026-11-04T12:05:00Z"}
        case = {**row["delivery"]["content"]["inputs"], "outcome": evaluation["outcome"], "evaluation_at": evaluation["as_of"]}
        evaluation["forecast_quality"] = quality(case, row["delivery"]["content"]["roles"]["analyst"])
        return report

    def test_new_resolution_appends_without_rewriting_history(self):
        before = canonical(self.prior)
        result = update_core_history(self.resolved_report(), self.prior, self.grants)
        self.assertEqual(canonical(self.prior), before)
        self.assertEqual(result[0]["versions"][:2], self.prior[0]["versions"])
        self.assertEqual(len(result[0]["versions"]), 3)
        self.assertEqual(result[0]["versions"][-1]["snapshot"]["outcome"]["status"], "FINAL")
        self.assertEqual(len({v["forecast_sha256"] for v in result[0]["versions"]}), 1)
        self.assertEqual(result, update_core_history(self.resolved_report(), result, self.grants))


    def test_proposed_to_final_retains_both_source_records(self):
        proposed = self.resolved_report()
        row = proposed["scenarios"][0]
        row["evaluation"]["outcome"]["final"] = False
        case = {**row["delivery"]["content"]["inputs"], "outcome": row["evaluation"]["outcome"], "evaluation_at": row["evaluation"]["as_of"]}
        row["evaluation"]["forecast_quality"] = quality(case, row["delivery"]["content"]["roles"]["analyst"])
        history = update_core_history(proposed, self.prior, self.grants)
        final = self.resolved_report()
        final["scenarios"][0]["evaluation"]["as_of"] = "2026-11-06T12:00:00Z"
        updated = update_core_history(final, history, self.grants)
        previous_ids = set(history[0]["versions"][-1]["snapshot"]["outcome"]["evidence_ids"])
        last = updated[0]["versions"][-1]["snapshot"]
        self.assertEqual(last["outcome"]["status"], "FINAL")
        self.assertTrue(previous_ids < {e["id"] for e in last["evidence"]})
        self.assertNotEqual(previous_ids, set(last["outcome"]["evidence_ids"]))
        self.assertEqual(updated, update_core_history(final, updated, self.grants))

    def test_older_and_same_time_changed_reports_fail(self):
        resolved = update_core_history(self.resolved_report(), self.prior, self.grants)
        with self.assertRaisesRegex(ValueError, "strictly increase"):
            update_core_history(self.report, resolved, self.grants)
        changed = self.resolved_report()
        changed["scenarios"][0]["evaluation"]["as_of"] = self.report["scenarios"][0]["evaluation"]["as_of"]
        changed["scenarios"][0]["evaluation"]["outcome"]["resolved_at"] = "2026-11-02T12:00:00Z"
        changed["scenarios"][0]["evaluation"]["outcome"]["available_at"] = "2026-11-02T12:05:00Z"
        with self.assertRaisesRegex(ValueError, "strictly increase"):
            update_core_history(changed, self.prior, self.grants)

    def test_reimport_does_not_inherit_publication_permission(self):
        result = update_core_history(self.report, self.prior)
        self.assertEqual(result[0]["versions"], self.prior[0]["versions"])
        self.assertNotIn("publication", result[0])
        self.assertEqual(json.loads(build_files(result)["index.json"])["claims"], [])

    def test_omitted_claim_is_retained_privately_for_audit(self):
        empty = {**self.report, "scenarios": []}
        result = update_core_history(empty, self.prior)
        self.assertEqual(result[0]["versions"], self.prior[0]["versions"])
        self.assertNotIn("publication", result[0])
        self.assertEqual(json.loads(build_files(result)["index.json"])["claims"], [])

    def test_corrupt_trusted_history_fails(self):
        broken = copy.deepcopy(self.prior)
        broken[0]["versions"][0]["snapshot"]["forecast"]["probability_bps"] = 9999
        with self.assertRaises(ValueError): update_core_history(self.report, broken, self.grants)
        with self.assertRaises(ValueError): update_core_history(self.report, self.prior * 2, self.grants)

    def test_one_command_integrated_demo_with_network_forbidden(self):
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as d:
            files = []
            for run in ("first", "second"):
                out = Path(d) / run
                argv = ["forecast_encyclopedia", "--core-demo", "--core-consent", str(ROOT / "fixtures_encyclopedia/core_demo_consent.json"), "--out", str(out)]
                with patch("sys.argv", argv), patch("socket.socket", side_effect=AssertionError("Network forbidden")), patch("socket.create_connection", side_effect=AssertionError("Network forbidden")), contextlib.redirect_stdout(io.StringIO()):
                    runpy.run_module("forecast_encyclopedia", run_name="__main__")
                self.assertEqual(len(json.loads((out / "index.json").read_text())["claims"]), 8)
                files.append({p.name: p.read_bytes() for p in out.iterdir()})
            self.assertEqual(files[0], files[1])


if __name__ == "__main__": unittest.main()
