"""Provider-neutral, bounded inference with a committed call trace.

Standard library only. One interface (`complete(request, timeout_s)`) with three
implementations: an OpenAI-compatible Chat Completions adapter (also usable for
NEAR AI Cloud or any compatible gateway), an Anthropic Messages API adapter and
a cassette replayer for deterministic offline runs. Keys and base URLs come only
from the caller's environment mapping; they never enter traces, cassettes,
exceptions or logs.

Limits are explicit per order: number of calls, output tokens per call, request
timeout and a cost ceiling in integer nano-USD computed from operator-supplied
per-token prices. A call is refused before it is sent if its worst case could
exceed the remaining budget. Every attempt, including refused or failed ones,
becomes a trace entry. Integers only: canonical JSON v1 forbids floats.
"""

import hashlib
import json
import re
import socket
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

TRACE_SCHEMA = "forecast-inference-trace/v1"
CASSETTE_SCHEMA = "forecast-inference-cassette/v1"
REQUEST_DOMAIN = "forecast-inference/v1:request\n"
RESPONSE_DOMAIN = "forecast-inference/v1:response\n"
ANTHROPIC_VERSION = "2026-10-21"
NANO_PER_USD = 1_000_000_000
# Worst-case input estimate: UTF-8 bytes (a BPE token covers >= 1 byte) plus a
# fixed allowance for chat-template tokens added by the provider.
TEMPLATE_TOKEN_ALLOWANCE = 64
MAX_ERROR_CHARS = 300
PROVIDER_KINDS = ("openai_compatible", "anthropic")
ORIGINS = ("HAND_AUTHORED_SYNTHETIC", "RECORDED_LIVE")
FAILURE_OUTCOMES = ("TIMEOUT", "TRANSPORT_ERROR", "HTTP_ERROR", "MALFORMED_RESPONSE", "REFUSAL")


class InferenceError(Exception):
    """A provider attempt failed. `outcome` is one of FAILURE_OUTCOMES."""

    def __init__(self, outcome, message):
        if outcome not in FAILURE_OUTCOMES:
            raise ValueError("Unknown inference failure outcome")
        super().__init__(message)
        self.outcome = outcome


class CassetteMiss(RuntimeError):
    """Replay has no recorded answer for this exact request. A harness error,
    never converted into a delivery outcome."""


class ConfigError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256_text(domain, text):
    return hashlib.sha256(domain.encode("ascii") + text.encode("utf-8")).hexdigest()


def _int(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ConfigError(f"{label} must be an integer >= {minimum}")
    return value


def usd_to_nano(text):
    """Parse a decimal USD amount such as '0.05' into integer nano-USD."""
    try:
        amount = Decimal(str(text))
    except InvalidOperation as exc:
        raise ConfigError("USD amount must be a decimal number") from exc
    nano = amount * NANO_PER_USD
    if not amount.is_finite() or amount < 0 or nano != nano.to_integral_value():
        raise ConfigError("USD amount must be nonnegative with at most 9 decimal places")
    return int(nano)


def format_usd(nano):
    return f"${Decimal(nano) / NANO_PER_USD:.6f}"


class Limits:
    """Per-order limits and operator-supplied prices, all integers."""

    FIELDS = ("max_calls", "max_output_tokens", "timeout_s", "max_cost_nano_usd",
              "input_price_nano_usd_per_token", "output_price_nano_usd_per_token")

    def __init__(self, max_calls, max_output_tokens, timeout_s, max_cost_nano_usd,
                 input_price_nano_usd_per_token, output_price_nano_usd_per_token):
        self.max_calls = _int(max_calls, "max_calls")
        self.max_output_tokens = _int(max_output_tokens, "max_output_tokens", 1)
        self.timeout_s = _int(timeout_s, "timeout_s", 1)
        self.max_cost_nano_usd = _int(max_cost_nano_usd, "max_cost_nano_usd")
        self.input_price_nano_usd_per_token = _int(input_price_nano_usd_per_token, "input price")
        self.output_price_nano_usd_per_token = _int(output_price_nano_usd_per_token, "output price")

    def record(self):
        return {name: getattr(self, name) for name in self.FIELDS}

    @classmethod
    def from_record(cls, record):
        if type(record) is not dict or set(record) != set(cls.FIELDS):
            raise ConfigError("Unexpected or missing limit fields")
        return cls(**record)

    def worst_case_cost(self, request):
        estimate = len((request["system"] + request["user"]).encode("utf-8")) + TEMPLATE_TOKEN_ALLOWANCE
        return (estimate * self.input_price_nano_usd_per_token
                + request["max_output_tokens"] * self.output_price_nano_usd_per_token)

    def cost(self, input_tokens, output_tokens):
        return (input_tokens * self.input_price_nano_usd_per_token
                + output_tokens * self.output_price_nano_usd_per_token)


def make_request(model, system, user, max_output_tokens, temperature_milli=None, options=None):
    """A provider-independent request record. Its hash keys cassettes."""
    if type(model) is not str or not model.strip():
        raise ConfigError("model must be a nonempty string")
    if type(system) is not str or type(user) is not str:
        raise ConfigError("prompts must be strings")
    _int(max_output_tokens, "max_output_tokens", 1)
    if temperature_milli is not None:
        _int(temperature_milli, "temperature_milli")
    options = dict(options or {})
    if any(type(k) is not str or type(v) is not str for k, v in options.items()):
        raise ConfigError("provider options must map strings to strings")
    body = {"model": model, "system": system, "user": user, "max_output_tokens": max_output_tokens,
            "temperature_milli": temperature_milli, "options": options}
    body["sha256"] = hashlib.sha256(REQUEST_DOMAIN.encode("ascii") + _canonical(body)).hexdigest()
    return body


def request_sha256(request):
    body = {key: request[key] for key in ("model", "system", "user", "max_output_tokens",
                                          "temperature_milli", "options")}
    return hashlib.sha256(REQUEST_DOMAIN.encode("ascii") + _canonical(body)).hexdigest()


def sanitize_base_url(url):
    """Keep scheme, host, port and path. Refuse credentials, query and fragment."""
    if type(url) is not str or not url.strip():
        raise ConfigError("Base URL must be a nonempty string")
    parts = urlsplit(url.strip())
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ConfigError("Base URL must use https (http only for localhost)")
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigError("Base URL must not contain credentials, query or fragment")
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname}{port}{parts.path.rstrip('/')}"


def _redact(text, secret):
    text = str(text)
    if secret:
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(bearer\s+|x-api-key[\"':\s]+)[A-Za-z0-9._\-]{8,}", r"\1[REDACTED]", text)
    return text[:MAX_ERROR_CHARS]


def urllib_transport(url, headers, body, timeout_s):
    """POST JSON; return (status, response_bytes). Raises InferenceError."""
    import urllib.error  # lazy: offline modes never load the HTTP/TLS stack
    import urllib.request
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read()
        except Exception:  # noqa: BLE001 - error body is optional diagnostics
            payload = b""
        return exc.code, payload
    except (socket.timeout, TimeoutError) as exc:
        raise InferenceError("TIMEOUT", "Request timed out") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise InferenceError("TIMEOUT", "Request timed out") from exc
        raise InferenceError("TRANSPORT_ERROR", f"Transport error: {type(exc.reason).__name__}") from exc
    except OSError as exc:
        raise InferenceError("TRANSPORT_ERROR", f"Transport error: {type(exc).__name__}") from exc


class _HttpProvider:
    kind = None

    def __init__(self, base_url, api_key, model, transport=None):
        if type(api_key) is not str or not api_key.strip():
            raise ConfigError("An API key is required in the environment")
        if type(model) is not str or not model.strip():
            raise ConfigError("A model name is required")
        self.api_base = sanitize_base_url(base_url)
        self.model = model
        self._api_key = api_key.strip()
        self._transport = transport or urllib_transport

    def __repr__(self):
        return f"{type(self).__name__}(api_base={self.api_base!r}, model={self.model!r}, api_key=[REDACTED])"

    def _post(self, path, headers, payload, timeout_s):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            status, raw = self._transport(self.api_base + path, headers, body, timeout_s)
        except InferenceError as exc:
            raise InferenceError(exc.outcome, _redact(exc, self._api_key)) from None
        if status != 200:
            snippet = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else ""
            raise InferenceError("HTTP_ERROR", _redact(f"HTTP {status}: {snippet}", self._api_key))
        try:
            data = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise InferenceError("MALFORMED_RESPONSE", "Provider response is not JSON") from exc
        if type(data) is not dict:
            raise InferenceError("MALFORMED_RESPONSE", "Provider response is not a JSON object")
        return data


def _usage_int(value):
    return value if type(value) is int and value >= 0 else None


class OpenAICompatibleProvider(_HttpProvider):
    """POST {base}/chat/completions with a bearer key.

    Options (committed in the request record): `max_tokens_field` chooses the
    body field for the output limit (`max_tokens`, or `max_completion_tokens`
    for newer OpenAI models, where it also bounds reasoning tokens);
    `reasoning_effort` is forwarded as is. No other option is sent."""

    kind = "openai_compatible"
    TOKEN_FIELDS = ("max_tokens", "max_completion_tokens")

    def complete(self, request, timeout_s):
        options = request["options"]
        field = options.get("max_tokens_field", "max_tokens")
        if field not in self.TOKEN_FIELDS or set(options) - {"max_tokens_field", "reasoning_effort"}:
            raise ConfigError("Unsupported openai_compatible options")
        payload = {"model": request["model"], field: request["max_output_tokens"],
                   "messages": [{"role": "system", "content": request["system"]},
                                {"role": "user", "content": request["user"]}]}
        if request["temperature_milli"] is not None:
            payload["temperature"] = request["temperature_milli"] / 1000
        if "reasoning_effort" in options:
            payload["reasoning_effort"] = options["reasoning_effort"]
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + self._api_key,
                   "User-Agent": "forecast-evidence-swarm/ai-worker"}
        data = self._post("/chat/completions", headers, payload, timeout_s)
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise InferenceError("MALFORMED_RESPONSE", "Missing choices[0].message.content") from exc
        if type(text) is not str:
            raise InferenceError("MALFORMED_RESPONSE", "Message content is not text")
        usage = data.get("usage") if type(data.get("usage")) is dict else {}
        return {"text": text, "finish_reason": str(choice.get("finish_reason")),
                "model_reported": str(data.get("model")) if data.get("model") is not None else None,
                "provider_response_id": str(data.get("id")) if data.get("id") is not None else None,
                "input_tokens": _usage_int(usage.get("prompt_tokens")),
                "output_tokens": _usage_int(usage.get("completion_tokens"))}


class AnthropicProvider(_HttpProvider):
    """POST {base}/v1/messages, API version 2026-10-21 (no sampling parameters)."""

    kind = "anthropic"

    def complete(self, request, timeout_s):
        if request["temperature_milli"] is not None:
            raise ConfigError("Anthropic API version 2026-10-21 rejects temperature; leave it unset")
        payload = {"model": request["model"], "max_tokens": request["max_output_tokens"],
                   "system": request["system"],
                   "messages": [{"role": "user", "content": request["user"]}]}
        if "effort" in request["options"]:
            payload["output_config"] = {"effort": request["options"]["effort"]}
        headers = {"Content-Type": "application/json", "x-api-key": self._api_key,
                   "anthropic-version": ANTHROPIC_VERSION,
                   "User-Agent": "forecast-evidence-swarm/ai-worker"}
        data = self._post("/v1/messages", headers, payload, timeout_s)
        stop = data.get("stop_reason")
        if stop == "refusal":
            raise InferenceError("REFUSAL", "Provider returned stop_reason=refusal")
        blocks = data.get("content")
        if type(blocks) is not list:
            raise InferenceError("MALFORMED_RESPONSE", "Missing content blocks")
        texts = [b.get("text") for b in blocks if type(b) is dict and b.get("type") == "text"]
        if not texts or any(type(t) is not str for t in texts):
            raise InferenceError("MALFORMED_RESPONSE", "No text content block")
        usage = data.get("usage") if type(data.get("usage")) is dict else {}
        return {"text": "".join(texts), "finish_reason": str(stop),
                "model_reported": str(data.get("model")) if data.get("model") is not None else None,
                "provider_response_id": str(data.get("id")) if data.get("id") is not None else None,
                "input_tokens": _usage_int(usage.get("input_tokens")),
                "output_tokens": _usage_int(usage.get("output_tokens"))}


RESPONSE_FIELDS = ("text", "finish_reason", "model_reported", "provider_response_id",
                   "input_tokens", "output_tokens")


def _check_response(response):
    if type(response) is not dict or set(response) != set(RESPONSE_FIELDS):
        raise ValueError("Recorded response has unexpected or missing fields")
    if type(response["text"]) is not str:
        raise ValueError("Recorded response text must be a string")
    for key in ("finish_reason", "model_reported", "provider_response_id"):
        if response[key] is not None and type(response[key]) is not str:
            raise ValueError(f"Recorded {key} must be a string or null")
    for key in ("input_tokens", "output_tokens"):
        if response[key] is not None and (type(response[key]) is not int or response[key] < 0):
            raise ValueError(f"Recorded {key} must be a nonnegative integer or null")


def load_cassette(path):
    """Load and strictly validate a cassette file; return (cassette, file_sha256)."""
    raw = Path(path).read_bytes()

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key in cassette")
            result[key] = value
        return result

    def no_float(_):
        raise ValueError("Cassettes are integer-only")

    cassette = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_float=no_float,
                          parse_constant=no_float)
    validate_cassette(cassette)
    return cassette, hashlib.sha256(raw).hexdigest()


def validate_cassette(cassette):
    required = {"schema_version", "origin", "synthetic_inputs", "notice", "provider", "api_base",
                "model", "limits", "interactions"}
    if type(cassette) is not dict or set(cassette) != required:
        raise ValueError("Cassette has unexpected or missing fields")
    if cassette["schema_version"] != CASSETTE_SCHEMA or cassette["origin"] not in ORIGINS:
        raise ValueError("Unsupported cassette schema or origin")
    if cassette["synthetic_inputs"] is not True:
        raise ValueError("Only cassettes over synthetic inputs are supported")
    hand = cassette["origin"] == "HAND_AUTHORED_SYNTHETIC"
    if hand != (cassette["provider"] == "fixture"):
        raise ValueError("Hand-authored cassettes must use provider 'fixture'; recorded ones a real provider kind")
    if not hand and cassette["provider"] not in PROVIDER_KINDS:
        raise ValueError("Unknown provider kind in cassette")
    if hand:
        if cassette["api_base"] is not None:
            raise ValueError("A hand-authored cassette has no API base")
    else:
        sanitize_base_url(cassette["api_base"])
    for key in ("notice", "model"):
        if type(cassette[key]) is not str or not cassette[key].strip():
            raise ValueError(f"Cassette {key} must be nonempty")
    Limits.from_record(cassette["limits"])
    if type(cassette["interactions"]) is not list:
        raise ValueError("Cassette interactions must be a list")
    seen = set()
    for item in cassette["interactions"]:
        if type(item) is not dict or set(item) != {"request_sha256", "outcome", "error", "response"}:
            raise ValueError("Cassette interaction has unexpected or missing fields")
        digest = item["request_sha256"]
        if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest) or digest in seen:
            raise ValueError("Cassette request hashes must be unique SHA-256 digests")
        seen.add(digest)
        if item["outcome"] == "OK":
            if item["error"] is not None:
                raise ValueError("A successful interaction has no error")
            _check_response(item["response"])
        elif item["outcome"] in FAILURE_OUTCOMES:
            if item["response"] is not None or type(item["error"]) is not str:
                raise ValueError("A failed interaction records an error string and no response")
        else:
            raise ValueError("Unknown interaction outcome")
    return cassette


class ReplayProvider:
    """Answers only exact recorded requests. No network, no fallback."""

    def __init__(self, cassette):
        validate_cassette(cassette)
        self.kind = cassette["provider"]
        self.api_base = cassette["api_base"]
        self.model = cassette["model"]
        self._answers = {item["request_sha256"]: item for item in cassette["interactions"]}

    def complete(self, request, timeout_s):
        item = self._answers.get(request_sha256(request))
        if item is None:
            raise CassetteMiss("No recorded interaction for request " + request_sha256(request))
        if item["outcome"] != "OK":
            raise InferenceError(item["outcome"], item["error"])
        return dict(item["response"])


class RecordingProvider:
    """Wraps a live provider and keeps sanitized interactions for a cassette."""

    def __init__(self, inner):
        self._inner = inner
        self.kind, self.api_base, self.model = inner.kind, inner.api_base, inner.model
        self.interactions = []

    def complete(self, request, timeout_s):
        digest = request_sha256(request)
        try:
            response = self._inner.complete(request, timeout_s)
        except InferenceError as exc:
            self._remember({"request_sha256": digest, "outcome": exc.outcome, "error": str(exc), "response": None})
            raise
        self._remember({"request_sha256": digest, "outcome": "OK", "error": None,
                        "response": {key: response[key] for key in RESPONSE_FIELDS}})
        return response

    def _remember(self, item):
        self.interactions = [x for x in self.interactions if x["request_sha256"] != item["request_sha256"]]
        self.interactions.append(item)

    def cassette(self, limits, notice):
        cassette = {"schema_version": CASSETTE_SCHEMA, "origin": "RECORDED_LIVE", "synthetic_inputs": True,
                    "notice": notice, "provider": self.kind, "api_base": self.api_base, "model": self.model,
                    "limits": limits.record(),
                    "interactions": sorted(self.interactions, key=lambda x: x["request_sha256"])}
        return validate_cassette(cassette)


class TranscriptProvider:
    """Replays the calls recorded inside a delivery trace, in order, for
    deterministic validation of a committed bundle."""

    def __init__(self, trace):
        self.kind, self.api_base, self.model = trace["provider"], trace["api_base"], trace["model"]
        self._queue = [entry for entry in trace["calls"] if entry["outcome"] != "BUDGET_EXCEEDED"]

    def complete(self, request, timeout_s):
        if not self._queue:
            raise ValueError("Trace has fewer provider calls than its replay requires")
        entry = self._queue.pop(0)
        if entry["request"]["sha256"] != request_sha256(request):
            raise ValueError("Trace request differs from deterministic replay")
        if entry["outcome"] != "OK":
            raise InferenceError(entry["outcome"], entry["error"])
        response = entry["response"]
        usage = entry["usage"]
        provider_usage = usage["source"] == "provider"
        return {"text": response["text"], "finish_reason": response["finish_reason"],
                "model_reported": response["model_reported"],
                "provider_response_id": response["provider_response_id"],
                "input_tokens": usage["input_tokens"] if provider_usage else None,
                "output_tokens": usage["output_tokens"] if provider_usage else None}

    def exhausted(self):
        return not self._queue


class InferenceEngine:
    """Per-order budget enforcement and trace recording around one provider."""

    def __init__(self, provider, limits, temperature_milli=None, options=None):
        if not isinstance(limits, Limits):
            raise ConfigError("limits must be a Limits instance")
        self.provider = provider
        self.limits = limits
        self.temperature_milli = temperature_milli
        self.options = dict(options or {})
        self.calls = []
        self.spent = 0

    def complete(self, role, system, user):
        request = make_request(self.provider.model, system, user, self.limits.max_output_tokens,
                               self.temperature_milli, self.options)
        entry = {"index": len(self.calls), "role": role,
                 "request": {key: request[key] for key in ("sha256", "model", "system", "user",
                                                           "max_output_tokens", "temperature_milli", "options")},
                 "outcome": None, "error": None, "response": None,
                 "usage": {"input_tokens": 0, "output_tokens": 0, "source": "not_called"},
                 "cost_estimate_nano_usd": 0, "over_budget": False, "attestation": None}
        attempted = sum(1 for call in self.calls if call["outcome"] != "BUDGET_EXCEEDED")
        worst = self.limits.worst_case_cost(request)
        if attempted >= self.limits.max_calls:
            entry.update(outcome="BUDGET_EXCEEDED", error="MAX_CALLS_REACHED")
        elif self.spent + worst > self.limits.max_cost_nano_usd:
            entry.update(outcome="BUDGET_EXCEEDED", error="WORST_CASE_COST_EXCEEDS_REMAINING_BUDGET")
        else:
            try:
                response = self.provider.complete(request, self.limits.timeout_s)
            except InferenceError as exc:
                # Billing of a failed attempt is unknown: charge the worst case.
                entry.update(outcome=exc.outcome, error=str(exc)[:MAX_ERROR_CHARS],
                             usage={"input_tokens": None, "output_tokens": None, "source": "worst_case_estimate"},
                             cost_estimate_nano_usd=worst)
            else:
                _check_response({key: response.get(key) for key in RESPONSE_FIELDS}
                                if type(response) is dict else response)
                text = response["text"]
                entry["outcome"] = "OK"
                entry["response"] = {"text": text, "sha256": sha256_text(RESPONSE_DOMAIN, text),
                                     "finish_reason": response["finish_reason"],
                                     "model_reported": response["model_reported"],
                                     "provider_response_id": response["provider_response_id"]}
                if response["input_tokens"] is None or response["output_tokens"] is None:
                    entry["usage"] = {"input_tokens": None, "output_tokens": None, "source": "worst_case_estimate"}
                    entry["cost_estimate_nano_usd"] = worst
                else:
                    entry["usage"] = {"input_tokens": response["input_tokens"],
                                      "output_tokens": response["output_tokens"], "source": "provider"}
                    entry["cost_estimate_nano_usd"] = self.limits.cost(response["input_tokens"], response["output_tokens"])
            self.spent += entry["cost_estimate_nano_usd"]
            entry["over_budget"] = self.spent > self.limits.max_cost_nano_usd
        self.calls.append(entry)
        return entry

    def trace(self):
        known = [c["usage"] for c in self.calls if c["usage"]["source"] == "provider"]
        return {"schema_version": TRACE_SCHEMA, "provider": self.provider.kind,
                "api_base": self.provider.api_base, "model": self.provider.model,
                "limits": self.limits.record(),
                "temperature_milli": self.temperature_milli, "options": dict(self.options),
                "pricing_note": "Cost is an estimate from operator-supplied integer prices, not a provider invoice.",
                "calls": [dict(call) for call in self.calls],
                "totals": {"calls_attempted": sum(1 for c in self.calls if c["outcome"] != "BUDGET_EXCEEDED"),
                           "calls_refused": sum(1 for c in self.calls if c["outcome"] == "BUDGET_EXCEEDED"),
                           "provider_input_tokens": sum(u["input_tokens"] for u in known),
                           "provider_output_tokens": sum(u["output_tokens"] for u in known),
                           "cost_estimate_nano_usd": self.spent}}


def validate_trace_shape(trace):
    required = {"schema_version", "provider", "api_base", "model", "limits", "temperature_milli", "options",
                "pricing_note", "calls", "totals"}
    if type(trace) is not dict or set(trace) != required or trace["schema_version"] != TRACE_SCHEMA:
        raise ValueError("Malformed inference trace")
    if type(trace["calls"]) is not list:
        raise ValueError("Trace calls must be a list")
    for entry in trace["calls"]:
        if type(entry) is not dict or type(entry.get("request")) is not dict or "outcome" not in entry:
            raise ValueError("Malformed trace call")
    return Limits.from_record(trace["limits"])


# ---------------------------------------------------------------- configuration

ENV_KEYS = ("FORECAST_LLM_PROVIDER", "FORECAST_LLM_MODEL", "FORECAST_LLM_API_KEY", "FORECAST_LLM_BASE_URL",
            "FORECAST_LLM_ANTHROPIC_EFFORT", "FORECAST_LLM_OPENAI_MAX_TOKENS_FIELD",
            "FORECAST_LLM_OPENAI_REASONING_EFFORT", "FORECAST_LLM_INPUT_NANO_USD_PER_TOKEN",
            "FORECAST_LLM_OUTPUT_NANO_USD_PER_TOKEN")


def read_env_file(path):
    """Parse KEY=VALUE lines for FORECAST_LLM_* keys only. No shell expansion."""
    values = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep:
            raise ConfigError(f"Env file line {number} is not KEY=VALUE")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key in ENV_KEYS:
            values[key] = value
    return values


def provider_from_env(env, transport=None):
    """Build a live provider from FORECAST_LLM_* values. Never logs the key."""
    kind = env.get("FORECAST_LLM_PROVIDER", "").strip()
    model = env.get("FORECAST_LLM_MODEL", "").strip()
    key = env.get("FORECAST_LLM_API_KEY", "")
    if kind not in PROVIDER_KINDS:
        raise ConfigError("FORECAST_LLM_PROVIDER must be one of: " + ", ".join(PROVIDER_KINDS))
    if not model:
        raise ConfigError("FORECAST_LLM_MODEL is required")
    if not key.strip():
        raise ConfigError("FORECAST_LLM_API_KEY is required (set it in your local environment, never in git)")
    if kind == "anthropic":
        base = env.get("FORECAST_LLM_BASE_URL", "").strip() or "https://api.anthropic.com"
        return AnthropicProvider(base, key, model, transport)
    base = env.get("FORECAST_LLM_BASE_URL", "").strip()
    if not base:
        raise ConfigError("FORECAST_LLM_BASE_URL is required for openai_compatible providers")
    return OpenAICompatibleProvider(base, key, model, transport)


def provider_options_from_env(env, kind):
    if kind == "anthropic":
        effort = env.get("FORECAST_LLM_ANTHROPIC_EFFORT", "").strip()
        if not effort:
            return {}
        if effort not in ("low", "medium", "high", "xhigh", "max"):
            raise ConfigError("FORECAST_LLM_ANTHROPIC_EFFORT must be low, medium, high, xhigh or max")
        return {"effort": effort}
    options = {}
    field = env.get("FORECAST_LLM_OPENAI_MAX_TOKENS_FIELD", "").strip()
    if field:
        if field not in OpenAICompatibleProvider.TOKEN_FIELDS:
            raise ConfigError("FORECAST_LLM_OPENAI_MAX_TOKENS_FIELD must be max_tokens or max_completion_tokens")
        options["max_tokens_field"] = field
    effort = env.get("FORECAST_LLM_OPENAI_REASONING_EFFORT", "").strip()
    if effort:
        if not re.fullmatch(r"[a-z]{1,16}", effort):
            raise ConfigError("FORECAST_LLM_OPENAI_REASONING_EFFORT must be a short lowercase word")
        options["reasoning_effort"] = effort
    return options
