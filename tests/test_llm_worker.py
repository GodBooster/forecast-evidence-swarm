import argparse
import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forecast_encyclopedia.adapter import adapt_report
from forecast_swarm import fixture_cassette, llm_cli
from forecast_swarm.demo import load_cases, run_demo, simulate
from forecast_swarm.evidence import commitment, quality, validate_bundle
from forecast_swarm.inference import (CASSETTE_SCHEMA, InferenceEngine, InferenceError, Limits,
                                      ReplayProvider, load_cassette, make_request)
from forecast_swarm.llm_roles import (LLM_SCHEMA_VERSION, build_llm_bundle, build_prompt, gate_output,
                                      pre_cutoff_evidence)

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_CASSETTE = ROOT / "fixtures" / "llm_cassettes" / "hand_authored_analyst.json"
LIMITS = Limits(max_calls=1, max_output_tokens=800, timeout_s=30, max_cost_nano_usd=5_000_000,
                input_price_nano_usd_per_token=100, output_price_nano_usd_per_token=500)
GOOD = {"probability_bps": 7000, "evidence_ids": ["batch-01"], "rationale": "batch-01: 15 of 20 were YES.",
        "uncertainty": {"low_bps": 5000, "high_bps": 8500, "drivers": ["Small sample."]}}


def case(name):
    return copy.deepcopy(next(c for c in load_cases() if c["scenario"] == name))


def prepared(c):
    inputs = json.loads(json.dumps(c))
    inputs["evidence"].sort(key=lambda item: item["id"])
    return inputs, pre_cutoff_evidence(inputs)


def cassette_for(c, outcome="OK", text=None, error=None, finish_reason="end_turn", limits=LIMITS, usage=(900, 120)):
    inputs, provided = prepared(c)
    system, user = build_prompt(inputs, provided)
    request = make_request("test-model", system, user, limits.max_output_tokens)
    response = None
    if outcome == "OK":
        response = {"text": text, "finish_reason": finish_reason, "model_reported": "test-model-2026",
                    "provider_response_id": "resp-1", "input_tokens": usage[0], "output_tokens": usage[1]}
    return {"schema_version": CASSETTE_SCHEMA, "origin": "RECORDED_LIVE", "synthetic_inputs": True,
            "notice": "test", "provider": "openai_compatible", "api_base": "https://gateway.example/v1",
            "model": "test-model", "limits": limits.record(),
            "interactions": [{"request_sha256": request["sha256"], "outcome": outcome,
                              "error": error, "response": response}]}


def bundle_with(c, limits=LIMITS, **kwargs):
    cassette = cassette_for(c, limits=limits, **kwargs)
    return build_llm_bundle(c, InferenceEngine(ReplayProvider(cassette), limits))


class GateTests(unittest.TestCase):
    def gate(self, value, finish_reason="end_turn", scenario="valid_wrong"):
        inputs, provided = prepared(case(scenario))
        text = value if isinstance(value, str) else json.dumps(value)
        return gate_output(text, finish_reason, inputs, provided)

    def test_valid_output_passes(self):
        parsed, status, reasons, fmt = self.gate(GOOD)
        self.assertEqual((status, reasons, fmt), ("VALID", [], "json"))
        _, status, _, fmt = self.gate("```json\n" + json.dumps(GOOD) + "\n```")
        self.assertEqual((status, fmt), ("VALID", "fenced_json"))

    def test_invalid_outputs_fail_closed_with_explicit_reasons(self):
        cases = {
            "NOT_JSON": "The probability is about 70%.",
            "NON_INTEGER_NUMBER": json.dumps({**GOOD, "probability_bps": 70.5}),
            "DUPLICATE_KEY": '{"probability_bps": 1, "probability_bps": 2, "evidence_ids": [], "rationale": "x", "uncertainty": null}',
            "NON_NUMERIC_PROBABILITY": {**GOOD, "probability_bps": "7000"},
            "PROBABILITY_OUT_OF_RANGE": {**GOOD, "probability_bps": 10001,
                                         "uncertainty": {**GOOD["uncertainty"], "high_bps": 10001}},
            "CITES_UNKNOWN_EVIDENCE:batch-99": {**GOOD, "evidence_ids": ["batch-01", "batch-99"]},
            "NO_EVIDENCE_CITED": {**GOOD, "evidence_ids": []},
            "UNEXPECTED_OR_MISSING_FIELDS": {**GOOD, "confidence": "high"},
            "MISSING_OR_MALFORMED_UNCERTAINTY": {**GOOD, "uncertainty": None},
            "INVALID_UNCERTAINTY_INTERVAL": {**GOOD, "uncertainty": {**GOOD["uncertainty"], "low_bps": 7500}},
            "INVALID_UNCERTAINTY_DRIVERS": {**GOOD, "uncertainty": {**GOOD["uncertainty"], "drivers": []}},
            "MISSING_RATIONALE": {**GOOD, "rationale": " "},
            "REFERENCES_DATE_AFTER_CUTOFF:2026-11-03": {**GOOD, "rationale": "Resolved NO on 2026-11-03."},
        }
        for reason, value in cases.items():
            with self.subTest(reason=reason):
                _, status, reasons, _ = self.gate(value)
                self.assertEqual(status, "INVALID")
                self.assertIn(reason, reasons)
        _, status, reasons, _ = self.gate("Here you go:\n" + json.dumps(GOOD))
        self.assertEqual((status, reasons), ("INVALID", ["NOT_JSON"]))
        _, status, reasons, _ = self.gate(GOOD, finish_reason="max_tokens")
        self.assertEqual((status, reasons), ("INVALID", ["TRUNCATED_OUTPUT"]))

    def test_resolution_date_is_allowed_but_later_dates_are_not(self):
        _, status, _, _ = self.gate({**GOOD, "rationale": "Resolves at 2026-11-02 per the terms; batch-01 is 75% YES."})
        self.assertEqual(status, "VALID")

    def test_citing_withheld_post_cutoff_evidence_is_invalid(self):
        c = case("valid_wrong")
        c["evidence"].append({**c["evidence"][0], "id": "batch-02", "available_at": "2026-11-01T12:30:00Z"})
        inputs, provided = prepared(c)
        self.assertEqual([item["id"] for item in provided], ["batch-01"])
        _, status, reasons, _ = gate_output(json.dumps({**GOOD, "evidence_ids": ["batch-02"]}), "stop", inputs, provided)
        self.assertEqual(status, "INVALID")
        self.assertIn("CITES_WITHHELD_EVIDENCE:batch-02", reasons)

    def test_abstention_is_insufficient_data_not_a_forecast(self):
        _, status, reasons, _ = self.gate({"probability_bps": None, "evidence_ids": [], "rationale": "Too little data.",
                                           "uncertainty": None})
        self.assertEqual((status, reasons), ("INSUFFICIENT_DATA", ["ANALYST_ABSTAINED"]))


class PromptTests(unittest.TestCase):
    def test_prompt_contains_only_pre_cutoff_evidence_and_no_outcome(self):
        c = case("valid_wrong")
        c["evidence"].append({**c["evidence"][0], "id": "batch-late", "available_at": "2026-11-01T12:00:01Z"})
        inputs, provided = prepared(c)
        system, user = build_prompt(inputs, provided)
        job = json.loads(user.split("\n\nReply format")[0].removeprefix("Forecast job:\n"))
        self.assertEqual(set(job), {"job_id", "question", "resolution_source", "decision_cutoff", "resolution_time",
                                    "data_notice", "evidence"})
        self.assertEqual([item["id"] for item in job["evidence"]], ["batch-01"])
        self.assertNotIn("batch-late", system + user)
        self.assertNotIn("2026-11-02T12:05:00Z", user)  # outcome availability time
        self.assertNotIn("final", user)

    def test_model_is_not_called_when_the_evidence_gate_fails(self):
        class Exploding:
            kind, api_base, model = "openai_compatible", "https://gateway.example", "m"

            def complete(self, request, timeout_s):
                raise AssertionError("model called despite failed evidence gate")

        for name, validity in (("future_data", "INVALID"), ("missing_data", "INSUFFICIENT_DATA")):
            with self.subTest(name=name):
                bundle = build_llm_bundle(case(name), InferenceEngine(Exploding(), LIMITS))
                content = bundle["content"]
                self.assertEqual(content["delivery_validity"], validity)
                self.assertEqual(content["inference_trace"]["calls"], [])
                self.assertEqual(content["roles"]["analyst"]["gate"]["status"], "NOT_RUN")
                validate_bundle(bundle)


class BundleTests(unittest.TestCase):
    def test_valid_llm_delivery_commits_trace_and_replays(self):
        bundle = bundle_with(case("valid_wrong"), text=json.dumps(GOOD))
        content = bundle["content"]
        self.assertEqual(content["schema_version"], LLM_SCHEMA_VERSION)
        self.assertEqual(content["delivery_validity"], "VALID")
        analyst = content["roles"]["analyst"]
        self.assertEqual((analyst["mode"], analyst["probability_bps"], analyst["model"]), ("llm", 7000, "test-model"))
        self.assertEqual({content["roles"]["critic"]["mode"], content["roles"]["verifier"]["mode"]}, {"scripted"})
        call = content["inference_trace"]["calls"][0]
        self.assertEqual(call["cost_estimate_nano_usd"], 900 * 100 + 120 * 500)
        self.assertEqual(bundle["sha256"], commitment("bundle", content, LLM_SCHEMA_VERSION))
        self.assertEqual(validate_bundle(bundle), bundle)
        c = case("valid_wrong")
        self.assertEqual(simulate(c, bundle)["status"], "ACCEPTED")
        self.assertEqual(quality(c, analyst)["direction_correct"], False)

    def test_invalid_output_blocks_payment_and_scoring(self):
        bundle = bundle_with(case("valid_wrong"), text=json.dumps({**GOOD, "evidence_ids": ["batch-07"]}))
        content = bundle["content"]
        self.assertEqual(content["delivery_validity"], "INVALID")
        self.assertIn("analyst:CITES_UNKNOWN_EVIDENCE:batch-07", content["roles"]["verifier"]["reasons"])
        self.assertIsNone(content["roles"]["analyst"]["probability_bps"])
        self.assertEqual(content["roles"]["analyst"]["status"], "REJECTED")
        self.assertIn("batch-07", content["inference_trace"]["calls"][0]["response"]["text"])  # kept for audit
        validate_bundle(bundle)
        acceptance = simulate(case("valid_wrong"), bundle)
        self.assertEqual(acceptance["status"], "REFUNDED")
        self.assertIn("INVALID", acceptance["submission_rejection"])
        self.assertIn("NO_VALID_FORECAST", quality(case("valid_wrong"), content["roles"]["analyst"])["reasons"])

    def test_provider_failures_become_insufficient_data(self):
        for outcome in ("TIMEOUT", "HTTP_ERROR", "TRANSPORT_ERROR", "MALFORMED_RESPONSE", "REFUSAL"):
            with self.subTest(outcome=outcome):
                bundle = bundle_with(case("valid_wrong"), outcome=outcome, error=outcome.lower())
                content = bundle["content"]
                self.assertEqual(content["delivery_validity"], "INSUFFICIENT_DATA")
                self.assertEqual(content["roles"]["verifier"]["reasons"], ["analyst:PROVIDER_" + outcome])
                self.assertEqual(content["inference_trace"]["calls"][0]["outcome"], outcome)
                self.assertGreater(content["inference_trace"]["totals"]["cost_estimate_nano_usd"], 0)
                validate_bundle(bundle)
                self.assertEqual(simulate(case("valid_wrong"), bundle)["status"], "REFUNDED")

    def test_budget_exhaustion_makes_no_call_and_is_insufficient(self):
        tight = Limits(**{**LIMITS.record(), "max_cost_nano_usd": 1000})
        bundle = bundle_with(case("valid_wrong"), limits=tight, text=json.dumps(GOOD))
        content = bundle["content"]
        self.assertEqual(content["delivery_validity"], "INSUFFICIENT_DATA")
        self.assertEqual(content["inference_trace"]["calls"][0]["outcome"], "BUDGET_EXCEEDED")
        self.assertEqual(content["inference_trace"]["totals"], {
            "calls_attempted": 0, "calls_refused": 1, "provider_input_tokens": 0, "provider_output_tokens": 0,
            "cost_estimate_nano_usd": 0})
        validate_bundle(bundle)

    def test_actual_cost_over_ceiling_invalidates_delivery(self):
        bundle = bundle_with(case("valid_wrong"), text=json.dumps(GOOD), usage=(10, 9_000_000))
        self.assertEqual(bundle["content"]["delivery_validity"], "INVALID")
        self.assertEqual(bundle["content"]["roles"]["verifier"]["reasons"], ["analyst:COST_LIMIT_EXCEEDED"])

    def test_tampering_is_detected_even_with_a_recomputed_hash(self):
        bundle = bundle_with(case("valid_wrong"), text=json.dumps(GOOD))
        mutations = [
            lambda c: c["roles"]["analyst"].__setitem__("probability_bps", 9000),
            lambda c: c["inference_trace"]["calls"][0]["response"].__setitem__("text", json.dumps({**GOOD, "probability_bps": 9000})),
            lambda c: c["inference_trace"]["calls"][0]["usage"].__setitem__("output_tokens", 1),
            lambda c: c["inference_trace"]["limits"].__setitem__("max_cost_nano_usd", 1000),  # recorded call would be refused
            lambda c: c["roles"]["critic"]["findings"].pop(),
            lambda c: c["inference_trace"]["calls"].append(copy.deepcopy(c["inference_trace"]["calls"][0])),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                forged = copy.deepcopy(bundle)
                mutate(forged["content"])
                forged["sha256"] = commitment("bundle", forged["content"], LLM_SCHEMA_VERSION)
                with self.assertRaises(ValueError):
                    validate_bundle(forged)


    def test_replay_proves_gate_consistency_not_model_provenance(self):
        # A fully rebuilt bundle around fabricated model text is self-consistent.
        # Replay cannot tell who wrote the text; only the hash bound at submission
        # (and, later, provider attestation) can. Documented in docs/AI_WORKER.md.
        fabricated = bundle_with(case("valid_wrong"), text=json.dumps({**GOOD, "probability_bps": 9000,
                                                                        "uncertainty": {**GOOD["uncertainty"], "high_bps": 9500}}))
        genuine = bundle_with(case("valid_wrong"), text=json.dumps(GOOD))
        self.assertEqual(validate_bundle(fabricated), fabricated)
        self.assertNotEqual(fabricated["sha256"], genuine["sha256"])


class ReportAndCliTests(unittest.TestCase):
    def fixture_setup(self):
        cassette, digest = load_cassette(FIXTURE_CASSETTE)
        provider = ReplayProvider(cassette)
        info = {"analyst": "llm", "critic": "scripted", "verifier": "scripted", "provider": "fixture",
                "model": cassette["model"], "inference_source": "REPLAY",
                "cassette": {"file": FIXTURE_CASSETTE.name, "sha256": digest, "origin": cassette["origin"]},
                "run_cost_cap_nano_usd": None}
        return (lambda: InferenceEngine(provider, Limits.from_record(cassette["limits"]))), info

    def test_each_order_is_a_distinct_request_so_live_and_replay_hashes_agree(self):
        requests = set()
        for c in load_cases():
            inputs, provided = prepared(c)
            requests.add(make_request("m", *build_prompt(inputs, provided), 10)["sha256"])
        self.assertEqual(len(requests), len(load_cases()))

    def test_fixture_cassette_matches_current_prompt_builder(self):
        self.assertEqual(FIXTURE_CASSETTE.read_text(encoding="utf-8"),
                         fixture_cassette.render(fixture_cassette.build_cassette()))

    def test_llm_report_is_deterministic_and_adapts_to_encyclopedia(self):
        factory, info = self.fixture_setup()
        first, second = run_demo(factory, info), run_demo(factory, info)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        records = adapt_report(first)
        self.assertEqual(len(records), 5)
        snapshot = records[0]["versions"][0]["snapshot"]
        self.assertTrue(snapshot["forecast"]["method"].startswith("LLM analyst (fixture/"))
        self.assertTrue(any(s["text"].startswith("Analyst rationale (LLM") for s in snapshot["statements"]))
        mixed = copy.deepcopy(first)
        mixed["schema_version"] = "forecast-evidence-swarm/v1"
        mixed["mode"] = "OFFLINE_SYNTHETIC_SIMULATION"
        del mixed["role_mode"]
        with self.assertRaises(ValueError):
            adapt_report(mixed)
        scripted = run_demo()
        self.assertNotIn("role_mode", scripted)
        self.assertEqual({r["delivery"]["content"]["schema_version"] for r in scripted["scenarios"]},
                         {"forecast-evidence-swarm/v1"})

    def test_cli_rejects_unsafe_or_ambiguous_mode_combinations(self):
        cases = load_cases()
        bad = [
            ["--replay", str(FIXTURE_CASSETTE)],
            ["--roles", "llm"],
            ["--roles", "llm", "--live", "--replay", str(FIXTURE_CASSETTE)],
            ["--roles", "llm", "--replay", str(FIXTURE_CASSETTE), "--max-cost-usd", "1"],
            ["--roles", "llm", "--live"],
            ["--roles", "llm", "--live", "--max-cost-usd", "0.01", "--max-run-cost-usd", "0.02",
             "--input-price-nano-usd-per-token", "100", "--output-price-nano-usd-per-token", "500"],
            ["--roles", "llm", "--live", "--max-cost-usd", "0.01", "--max-run-cost-usd", "1",
             "--input-price-nano-usd-per-token", "100", "--output-price-nano-usd-per-token", "500"],
        ]
        for argv in bad:
            with self.subTest(argv=argv):
                parser = argparse.ArgumentParser()
                llm_cli.add_arguments(parser)
                args = parser.parse_args(argv)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    llm_cli.setup_from_args(parser, args, cases, environ={})

    def test_live_setup_builds_bounded_engines_without_contacting_anyone(self):
        parser = argparse.ArgumentParser()
        llm_cli.add_arguments(parser)
        args = parser.parse_args(["--roles", "llm", "--live", "--max-cost-usd", "0.01", "--max-run-cost-usd", "0.03",
                                  "--input-price-nano-usd-per-token", "100", "--output-price-nano-usd-per-token", "500"])
        env = {"FORECAST_LLM_PROVIDER": "anthropic", "FORECAST_LLM_MODEL": "m", "FORECAST_LLM_API_KEY": "k-test",
               "FORECAST_LLM_ANTHROPIC_EFFORT": "low"}
        setup = llm_cli.setup_from_args(parser, args, load_cases(), environ=env)
        engine = setup.engine_factory()
        self.assertEqual(engine.limits.max_calls, 1)
        self.assertEqual(engine.limits.max_cost_nano_usd, 10_000_000)
        self.assertEqual(engine.options, {"effort": "low"})
        self.assertEqual(setup.role_info["inference_source"], "LIVE")
        self.assertNotIn("k-test", json.dumps(setup.role_info))

    def test_offline_walkthrough_replays_llm_analyst_with_network_disabled(self):
        script = """
import runpy, socket, sys
def denied(*args, **kwargs):
    raise AssertionError('Network access attempted in replay walkthrough')
socket.socket = socket.create_connection = socket.getaddrinfo = denied
sys.argv = ['walkthrough'] + sys.argv[1:]
runpy.run_module('forecast_swarm.walkthrough', run_name='__main__')
"""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw).resolve()
            outputs = []
            for seed in ("1", "77"):
                out = tmp / seed
                result = subprocess.run([sys.executable, "-c", script, "--out", str(out), "--roles", "llm",
                                         "--replay", str(FIXTURE_CASSETTE)],
                                        cwd=ROOT, env={"PYTHONHASHSEED": seed, "PYTHONUTF8": "1"},
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("LLM analyst inside deterministic gates", result.stdout)
                self.assertIn("HAND_AUTHORED_SYNTHETIC", result.stdout)
                self.assertIn("All walkthrough checks passed.", result.stdout)
                summary = json.loads((out / "walkthrough.json").read_text(encoding="utf-8"))
                self.assertEqual(summary["roles"]["analyst"], "llm")
                self.assertEqual(summary["inference"]["calls"][0]["outcome"], "OK")
                self.assertEqual(summary["run_calls_attempted"], 3)
                html = (out / "core" / "report.html").read_text(encoding="utf-8")
                self.assertIn("Inference trace", html)
                page = (out / summary["encyclopedia"]["page"]).read_text(encoding="utf-8")
                self.assertIn("LLM analyst (fixture/hand-authored-synthetic-analyst)", page)
                outputs.append((out / "core" / "report.json").read_bytes())
            self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
