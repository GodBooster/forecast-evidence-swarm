import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser

from forecast_swarm.demo import render_html, run_demo
from forecast_swarm.evidence import validate_bundle


ROOT = Path(__file__).resolve().parent.parent


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.ids, self.links, self.text = [], [], [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        for key in ("href", "src"):
            if key in attrs:
                self.links.append(attrs[key])

    def handle_data(self, data):
        self.text.append(data)


class DemoTests(unittest.TestCase):
    def test_scenarios_keep_delivery_quality_and_payment_independent(self):
        report = run_demo()
        expected = {
            "valid_wrong": ("VALID", "EVALUATED", "ACCEPTED"),
            "future_data": ("INVALID", "INSUFFICIENT_DATA", "REFUNDED"),
            "missing_data": ("INSUFFICIENT_DATA", "INSUFFICIENT_DATA", "REFUNDED"),
            "unresolved": ("VALID", "INSUFFICIENT_DATA", "AWAITING_CUSTOMER"),
            "zero_successes": ("VALID", "EVALUATED", "ACCEPTED"),
        }
        self.assertEqual({r["scenario"] for r in report["scenarios"]}, set(expected))
        for result in report["scenarios"]:
            with self.subTest(scenario=result["scenario"]):
                validate_bundle(result["delivery"])
                content = result["delivery"]["content"]
                score = result["evaluation"]["forecast_quality"]
                acceptance = result["customer_acceptance"]
                self.assertEqual((content["delivery_validity"], score["status"], acceptance["status"]),
                                 expected[result["scenario"]])
                self.assertNotIn("outcome", content["inputs"])
                self.assertEqual({r["mode"] for r in content["roles"].values()}, {"scripted"})
                ledger = acceptance["ledger"]
                self.assertEqual(ledger["budget"], ledger["escrow"] + ledger["paid_to_worker"] + ledger["refunded_to_customer"])
        wrong = report["scenarios"][0]
        self.assertFalse(wrong["evaluation"]["forecast_quality"]["direction_correct"])
        self.assertEqual(wrong["evaluation"]["forecast_quality"]["brier_score_scaled_1e8"], 56250000)
        self.assertEqual(wrong["customer_acceptance"]["ledger"]["paid_to_worker"], 100)

    def test_cli_is_repeatable_with_network_disabled(self):
        # The command itself runs in separate processes with different hash seeds,
        # no credential environment and fail-fast Python networking guards.
        script = """
import runpy, socket
def denied(*args, **kwargs):
    raise AssertionError('Network access attempted in offline demo')
socket.socket = socket.create_connection = socket.getaddrinfo = denied
runpy.run_module('forecast_swarm', run_name='__main__')
"""
        with tempfile.TemporaryDirectory() as directory:
            outputs = []
            for seed in ("1", "99"):
                output = Path(directory) / seed
                result = subprocess.run([sys.executable, "-c", script, "--out", str(output)],
                                        cwd=ROOT, env={"PYTHONHASHSEED": seed, "PYTHONUTF8": "1"},
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("All three roles are scripted", result.stdout)
                outputs.append({name: (output / name).read_bytes() for name in ("report.json", "report.html")})
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(json.loads(outputs[0]["report.json"]), run_demo())

    def test_html_is_self_contained_navigable_and_escapes_source_text(self):
        report = run_demo()
        markup = render_html(report)
        parser = ReportParser()
        parser.feed(markup)
        self.assertEqual(parser.tags.count("article"), 5)
        self.assertNotIn("script", parser.tags)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        for link in parser.links:
            self.assertTrue(link.startswith("#") or link == "report.json")
            if link.startswith("#"):
                self.assertIn(link[1:], parser.ids)
        text = " ".join(parser.text)
        for word in ("SIMULATION", "scripted", "INVALID", "INSUFFICIENT_DATA", "AWAITING_CUSTOMER"):
            self.assertIn(word, text)
        malicious = copy.deepcopy(report)
        malicious["scenarios"][0]["title"] = '<img src="https://example.invalid/exfil" onerror="alert(1)">'
        malicious["scenarios"][0]["delivery"]["content"]["inputs"]["terms"]["question"] = "<script>alert(1)</script>"
        escaped = render_html(malicious)
        safe_parser = ReportParser()
        safe_parser.feed(escaped)
        self.assertNotIn("img", safe_parser.tags)
        self.assertNotIn("script", safe_parser.tags)
        self.assertIn("&lt;script&gt;", escaped)


if __name__ == "__main__":
    unittest.main()
