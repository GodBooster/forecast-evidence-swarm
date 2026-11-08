import json
import tempfile
import unittest
from pathlib import Path

from forecast_swarm.inference import (
    AnthropicProvider, CassetteMiss, ConfigError, InferenceEngine, InferenceError, Limits,
    OpenAICompatibleProvider, RecordingProvider, ReplayProvider, load_cassette, make_request,
    provider_from_env, provider_options_from_env, read_env_file, request_sha256, sanitize_base_url, usd_to_nano, validate_cassette)

SECRET = "sk-test-NOT-A-REAL-KEY-0123456789abcdef"


def limits(**overrides):
    values = dict(max_calls=1, max_output_tokens=100, timeout_s=5, max_cost_nano_usd=10_000_000,
                  input_price_nano_usd_per_token=100, output_price_nano_usd_per_token=500)
    values.update(overrides)
    return Limits(**values)


class FakeTransport:
    """Records requests; returns a scripted (status, body) or raises."""

    def __init__(self, status=200, body=None, error=None):
        self.status, self.body, self.error = status, body, error
        self.requests = []

    def __call__(self, url, headers, body, timeout_s):
        self.requests.append({"url": url, "headers": headers, "body": json.loads(body), "timeout": timeout_s})
        if self.error:
            raise self.error
        return self.status, json.dumps(self.body).encode("utf-8") if not isinstance(self.body, bytes) else self.body


OPENAI_OK = {"id": "chatcmpl-test", "model": "test-model-reported",
             "choices": [{"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 40, "completion_tokens": 7}}
ANTHROPIC_OK = {"id": "msg_test", "model": "claude-test", "stop_reason": "end_turn",
                "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "hel"},
                            {"type": "text", "text": "lo"}],
                "usage": {"input_tokens": 41, "output_tokens": 9}}


class AdapterTests(unittest.TestCase):
    def test_openai_compatible_request_and_response(self):
        transport = FakeTransport(body=OPENAI_OK)
        provider = OpenAICompatibleProvider("https://gateway.example/v1/", SECRET, "test-model", transport)
        request = make_request("test-model", "sys", "user", 100, temperature_milli=0)
        response = provider.complete(request, 7)
        sent = transport.requests[0]
        self.assertEqual(sent["url"], "https://gateway.example/v1/chat/completions")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer " + SECRET)
        self.assertEqual(sent["body"]["messages"], [{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}])
        self.assertEqual((sent["body"]["max_tokens"], sent["body"]["temperature"], sent["timeout"]), (100, 0, 7))
        self.assertEqual((response["text"], response["input_tokens"], response["output_tokens"]), ("hello", 40, 7))
        self.assertEqual(response["model_reported"], "test-model-reported")
        self.assertNotIn(SECRET, repr(provider))

    def test_openai_options_select_token_field_and_reasoning_effort_only(self):
        transport = FakeTransport(body=OPENAI_OK)
        provider = OpenAICompatibleProvider("https://api.example/v1", SECRET, "m", transport)
        options = {"max_tokens_field": "max_completion_tokens", "reasoning_effort": "low"}
        provider.complete(make_request("m", "s", "u", 50, options=options), 5)
        body = transport.requests[0]["body"]
        self.assertEqual((body["max_completion_tokens"], body["reasoning_effort"]), (50, "low"))
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("max_tokens_field", body)
        self.assertNotIn("temperature", body)
        for bad in ({"max_tokens_field": "tokens"}, {"logit_bias": "x"}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                provider.complete(make_request("m", "s", "u", 50, options=bad), 5)
        self.assertEqual(provider_options_from_env({"FORECAST_LLM_OPENAI_MAX_TOKENS_FIELD": "max_completion_tokens",
                                                    "FORECAST_LLM_OPENAI_REASONING_EFFORT": "low"}, "openai_compatible"),
                         options)

    def test_anthropic_request_uses_current_api_version_and_reads_text_blocks_only(self):
        transport = FakeTransport(body=ANTHROPIC_OK)
        provider = AnthropicProvider("https://api.anthropic.com", SECRET, "claude-test", transport)
        response = provider.complete(make_request("claude-test", "sys", "user", 100, options={"effort": "low"}), 5)
        sent = transport.requests[0]
        self.assertEqual(sent["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(sent["headers"]["x-api-key"], SECRET)
        self.assertEqual(sent["headers"]["anthropic-version"], "2026-10-21")
        self.assertNotIn("temperature", sent["body"])
        self.assertEqual(sent["body"]["system"], "sys")
        self.assertEqual(sent["body"]["output_config"], {"effort": "low"})
        self.assertEqual((response["text"], response["finish_reason"], response["output_tokens"]), ("hello", "end_turn", 9))
        with self.assertRaises(ConfigError):
            provider.complete(make_request("claude-test", "s", "u", 10, temperature_milli=0), 5)

    def test_refusal_http_error_and_malformed_response_are_typed_failures(self):
        cases = [
            (AnthropicProvider, {**ANTHROPIC_OK, "stop_reason": "refusal"}, 200, "REFUSAL"),
            (OpenAICompatibleProvider, {"error": {"message": "bad key " + SECRET}}, 401, "HTTP_ERROR"),
            (OpenAICompatibleProvider, {"choices": []}, 200, "MALFORMED_RESPONSE"),
            (OpenAICompatibleProvider, b"<html>not json</html>", 200, "MALFORMED_RESPONSE"),
        ]
        for cls, body, status, outcome in cases:
            with self.subTest(outcome=outcome, status=status):
                provider = cls("https://gateway.example", SECRET, "m", FakeTransport(status=status, body=body))
                with self.assertRaises(InferenceError) as caught:
                    provider.complete(make_request("m", "s", "u", 10), 5)
                self.assertEqual(caught.exception.outcome, outcome)
                self.assertNotIn(SECRET, str(caught.exception))

    def test_base_url_and_cost_parsing_fail_closed(self):
        self.assertEqual(sanitize_base_url("https://x.example/v1/"), "https://x.example/v1")
        self.assertEqual(sanitize_base_url("http://127.0.0.1:8080/v1"), "http://127.0.0.1:8080/v1")
        for bad in ("http://x.example/v1", "https://user:pw@x.example", "https://x.example/v1?key=1", "ftp://x", ""):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                sanitize_base_url(bad)
        self.assertEqual(usd_to_nano("0.05"), 50_000_000)
        self.assertEqual(usd_to_nano("1"), 1_000_000_000)
        for bad in ("-1", "0.0000000001", "abc", "nan"):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                usd_to_nano(bad)

    def test_environment_configuration_requires_key_and_reads_only_forecast_keys(self):
        with self.assertRaises(ConfigError):
            provider_from_env({"FORECAST_LLM_PROVIDER": "anthropic", "FORECAST_LLM_MODEL": "m"})
        with self.assertRaises(ConfigError):
            provider_from_env({"FORECAST_LLM_PROVIDER": "openai_compatible", "FORECAST_LLM_MODEL": "m",
                               "FORECAST_LLM_API_KEY": SECRET})  # base URL required
        with self.assertRaises(ConfigError):
            provider_from_env({"FORECAST_LLM_PROVIDER": "other", "FORECAST_LLM_MODEL": "m", "FORECAST_LLM_API_KEY": SECRET})
        provider = provider_from_env({"FORECAST_LLM_PROVIDER": "anthropic", "FORECAST_LLM_MODEL": "m",
                                      "FORECAST_LLM_API_KEY": SECRET})
        self.assertEqual((provider.kind, provider.api_base), ("anthropic", "https://api.anthropic.com"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "local.env"
            path.write_text("# comment\nexport FORECAST_LLM_MODEL='m'\nOTHER_SECRET=x\nFORECAST_LLM_API_KEY=k\n",
                            encoding="utf-8")
            self.assertEqual(read_env_file(path), {"FORECAST_LLM_MODEL": "m", "FORECAST_LLM_API_KEY": "k"})

    def test_env_example_has_no_values_for_secrets(self):
        text = (Path(__file__).resolve().parent.parent / ".env.example").read_text(encoding="utf-8")
        values = read_env_file_text(text)
        self.assertIn("FORECAST_LLM_API_KEY", values)
        self.assertEqual(set(values.values()), {""})


def read_env_file_text(text):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "e"
        path.write_text(text, encoding="utf-8")
        return read_env_file(path)


class CountingProvider:
    kind, api_base, model = "openai_compatible", "https://gateway.example", "m"

    def __init__(self, response=None, error=None):
        self.calls, self.response, self.error = 0, response, error

    def complete(self, request, timeout_s):
        self.calls += 1
        if self.error:
            raise self.error
        return dict(self.response)


OK_RESPONSE = {"text": "ok", "finish_reason": "stop", "model_reported": "m", "provider_response_id": "r1",
               "input_tokens": 10, "output_tokens": 5}


class BudgetAndTraceTests(unittest.TestCase):
    def test_successful_call_is_traced_with_hashes_usage_and_cost(self):
        engine = InferenceEngine(CountingProvider(OK_RESPONSE), limits())
        entry = engine.complete("analyst", "sys", "user")
        self.assertEqual(entry["outcome"], "OK")
        self.assertEqual(entry["usage"], {"input_tokens": 10, "output_tokens": 5, "source": "provider"})
        self.assertEqual(entry["cost_estimate_nano_usd"], 10 * 100 + 5 * 500)
        self.assertEqual(entry["request"]["sha256"], request_sha256(entry["request"]))
        self.assertEqual(len(entry["response"]["sha256"]), 64)
        self.assertIsNone(entry["attestation"])
        trace = engine.trace()
        self.assertEqual(trace["totals"]["cost_estimate_nano_usd"], 3500)
        self.assertEqual(trace["totals"]["calls_attempted"], 1)

    def test_call_limit_refuses_without_contacting_provider(self):
        provider = CountingProvider(OK_RESPONSE)
        engine = InferenceEngine(provider, limits(max_calls=1))
        engine.complete("analyst", "s", "u")
        refused = engine.complete("analyst", "s", "u")
        self.assertEqual((refused["outcome"], refused["error"], provider.calls), ("BUDGET_EXCEEDED", "MAX_CALLS_REACHED", 1))
        self.assertEqual(refused["cost_estimate_nano_usd"], 0)

    def test_worst_case_cost_over_budget_refuses_before_sending(self):
        provider = CountingProvider(OK_RESPONSE)
        engine = InferenceEngine(provider, limits(max_cost_nano_usd=1000))
        entry = engine.complete("analyst", "s", "u")
        self.assertEqual((entry["outcome"], entry["error"]), ("BUDGET_EXCEEDED", "WORST_CASE_COST_EXCEEDS_REMAINING_BUDGET"))
        self.assertEqual(provider.calls, 0)

    def test_failed_attempt_charges_worst_case_and_records_outcome(self):
        engine = InferenceEngine(CountingProvider(error=InferenceError("TIMEOUT", "Request timed out")), limits())
        entry = engine.complete("analyst", "s", "u")
        self.assertEqual(entry["outcome"], "TIMEOUT")
        self.assertEqual(entry["usage"]["source"], "worst_case_estimate")
        self.assertEqual(entry["cost_estimate_nano_usd"], limits().worst_case_cost(make_request("m", "s", "u", 100)))
        self.assertIsNone(entry["response"])

    def test_missing_provider_usage_is_charged_at_worst_case(self):
        engine = InferenceEngine(CountingProvider({**OK_RESPONSE, "input_tokens": None}), limits())
        entry = engine.complete("analyst", "s", "u")
        self.assertEqual(entry["usage"]["source"], "worst_case_estimate")
        self.assertGreater(entry["cost_estimate_nano_usd"], 0)


class CassetteTests(unittest.TestCase):
    def test_record_then_replay_reproduces_trace_without_secrets(self):
        transport = FakeTransport(body=OPENAI_OK)
        live = OpenAICompatibleProvider("https://gateway.example/v1", SECRET, "test-model", transport)
        recorder = RecordingProvider(live)
        live_trace_engine = InferenceEngine(recorder, limits())
        live_trace_engine.complete("analyst", "sys", "user")
        cassette = recorder.cassette(limits(), "test cassette")
        serialized = json.dumps(cassette) + json.dumps(live_trace_engine.trace())
        self.assertNotIn(SECRET, serialized)
        self.assertNotIn("Authorization", serialized)
        replay_engine = InferenceEngine(ReplayProvider(cassette), limits())
        replay_engine.complete("analyst", "sys", "user")
        self.assertEqual(replay_engine.trace(), live_trace_engine.trace())
        with self.assertRaises(CassetteMiss):
            InferenceEngine(ReplayProvider(cassette), limits()).complete("analyst", "sys", "different prompt")

    def test_cassette_validation_is_strict(self):
        base = {"schema_version": "forecast-inference-cassette/v1", "origin": "HAND_AUTHORED_SYNTHETIC",
                "synthetic_inputs": True, "notice": "n", "provider": "fixture", "api_base": None, "model": "m",
                "limits": limits().record(), "interactions": []}
        validate_cassette(base)
        for change in ({"provider": "anthropic"}, {"origin": "RECORDED_LIVE"}, {"synthetic_inputs": False},
                       {"interactions": [{"request_sha256": "0" * 64, "outcome": "WEIRD", "error": None, "response": None}]},
                       {"extra": 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_cassette({**base, **change})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps(base).replace('"timeout_s": 5', '"timeout_s": 5.0'), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_cassette(path)

    def test_replayed_failures_raise_the_recorded_outcome(self):
        request = make_request("m", "s", "u", 100)
        cassette = {"schema_version": "forecast-inference-cassette/v1", "origin": "HAND_AUTHORED_SYNTHETIC",
                    "synthetic_inputs": True, "notice": "n", "provider": "fixture", "api_base": None, "model": "m",
                    "limits": limits().record(),
                    "interactions": [{"request_sha256": request["sha256"], "outcome": "HTTP_ERROR",
                                      "error": "HTTP 503: overloaded", "response": None}]}
        with self.assertRaises(InferenceError) as caught:
            ReplayProvider(cassette).complete(request, 5)
        self.assertEqual(caught.exception.outcome, "HTTP_ERROR")


if __name__ == "__main__":
    unittest.main()
