# Bounded AI worker (LLM analyst)

Status on 2026-11-08: **implemented, verified offline, and exercised in one owner-approved
live run** (OpenAI API, `gpt-6.1-terra`, 3 calls, estimated $0.004656 against a $1 ceiling;
all three outputs passed the gates). Details, tokens and hashes are in
[VALIDATION.md](VALIDATION.md). One run on synthetic inputs says nothing about forecast
quality.

## What changes and what does not

| | `--roles scripted` (default) | `--roles llm` |
| --- | --- | --- |
| Analyst | Pooled frequency, half-up to basis points | One bounded LLM call per order, inside the gates below |
| Critic | Fixed findings (`mode: scripted`) | Deterministic, adds data-driven findings about the model output (`mode: scripted`) |
| Verifier | Evidence gate (`mode: scripted`) | Evidence gate + model-output gate (`mode: scripted`) |
| Delivery schema | `forecast-evidence-swarm/v1` | `forecast-evidence-swarm/llm-analyst/v1` |
| Network | None | None for `--replay`; provider HTTPS only for `--live` |
| Output | Byte-identical to earlier releases | Report, walkthrough and encyclopedia name the mode, provider and model |

Scripted mode stays the default and its JSON, HTML and hashes are unchanged (checked by
byte comparison against the previous outputs and by the existing tests).

### Why only the analyst is an LLM

- **The verifier is the gate.** It decides whether money can move. It must be
  deterministic and replayable from the committed bundle; an LLM verifier would make
  validity depend on sampling and on the same kind of agent whose work it judges.
  [BUILD_SPEC.md](BUILD_SPEC.md) forbids releasing money on a vote of the agents that
  produced the work.
- **The critic stays deterministic** but reads the model output: it reports the gap
  between the model's probability and the pooled frequency of the cited batches, states
  that the model's uncertainty interval is not a statistical interval, and notes how many
  supplied batches were cited. An LLM critic is a possible later step with the same gates
  and its own call budget; it would double cost and add a second unverifiable judgement
  without changing who decides validity.
- One model call per order keeps cost, latency and the audit trail small.

## Flow and gates

```
case ─► evidence gate (scripted verifier) ──not VALID──► no call; analyst ABSTAIN (gate NOT_RUN)
              │ VALID
              ▼
        prompt: question, source, cutoff, resolution time, evidence observed AND published ≤ cutoff
              │ (outcome, evaluation time and payment state are never passed)
              ▼
        budget preflight ──refused──► trace BUDGET_EXCEEDED, delivery INSUFFICIENT_DATA
              │
              ▼
        provider call (timeout) ──failure──► trace TIMEOUT / HTTP_ERROR / TRANSPORT_ERROR /
              │                              MALFORMED_RESPONSE / REFUSAL → INSUFFICIENT_DATA
              ▼
        output gate ──violation──► INVALID (no probability is delivered; raw text kept in trace)
              │ abstention ──► INSUFFICIENT_DATA
              ▼
        VALID forecast → deterministic critic → verifier → bundle + SHA-256 → simulator / escrow
```

Only a `VALID` delivery can be submitted to the payment simulator or the escrow
contract; `INVALID` and `INSUFFICIENT_DATA` deliveries are refunded at the deadline
exactly as in scripted mode. Nothing is retried or repaired automatically.

### Output gate (`forecast_swarm/llm_roles.py:gate_output`)

The model must answer with exactly one JSON object with the keys `probability_bps`,
`evidence_ids`, `rationale`, `uncertainty`. A single complete Markdown ```` ```json ````
fence is accepted and recorded as `output_format: fenced_json`; any other surrounding
text fails.

| Check | Result on violation |
| --- | --- |
| Not JSON, text around the object, duplicate keys | INVALID `NOT_JSON`, `DUPLICATE_KEY` |
| Any non-integer number (e.g. `70.5`) | INVALID `NON_INTEGER_NUMBER` |
| Missing or extra keys | INVALID `UNEXPECTED_OR_MISSING_FIELDS` |
| `probability_bps` not an integer / outside 0–10000 | INVALID `NON_NUMERIC_PROBABILITY` / `PROBABILITY_OUT_OF_RANGE` |
| Cited ID not supplied in the prompt | INVALID `CITES_UNKNOWN_EVIDENCE:<id>` |
| Cited ID that exists but was withheld (post-cutoff) | INVALID `CITES_WITHHELD_EVIDENCE:<id>` |
| Forecast without citations | INVALID `NO_EVIDENCE_CITED` |
| Missing interval, `low ≤ p ≤ high` violated, 1–5 drivers violated | INVALID `MISSING_OR_MALFORMED_UNCERTAINTY`, `INVALID_UNCERTAINTY_INTERVAL`, `INVALID_UNCERTAINTY_DRIVERS` |
| Empty or > 2000-character rationale | INVALID `MISSING_RATIONALE`, `RATIONALE_TOO_LONG` |
| A `YYYY-MM-DD` date after the cutoff day in rationale or drivers (the stated resolution day is allowed) | INVALID `REFERENCES_DATE_AFTER_CUTOFF:<date>` |
| Provider says output was cut (`length`, `max_tokens`) | INVALID `TRUNCATED_OUTPUT` |
| Actual cost above the per-order ceiling | INVALID `COST_LIMIT_EXCEEDED` |
| `probability_bps: null` with no citations and no interval | INSUFFICIENT_DATA `ANALYST_ABSTAINED` |

The date check is a heuristic against leaked post-cutoff knowledge, not a proof that
none occurred. The citation check proves that cited IDs exist and were supplied; it does
not prove that the rationale follows from them.

## Inference adapter (`forecast_swarm/inference.py`)

Standard library only (`urllib`). One interface, `complete(request, timeout_s)`:

| Implementation | Endpoint | Notes |
| --- | --- | --- |
| `OpenAICompatibleProvider` | `POST {FORECAST_LLM_BASE_URL}/chat/completions`, bearer key | For OpenAI, NEAR AI Cloud or any compatible gateway. Base URL is required; use the provider's documented value. Optional `FORECAST_LLM_OPENAI_MAX_TOKENS_FIELD=max_completion_tokens` (needed by newer OpenAI models; it also bounds hidden reasoning tokens) and `FORECAST_LLM_OPENAI_REASONING_EFFORT`. No other body fields are sent. |
| `AnthropicProvider` | `POST {base or https://api.anthropic.com}/v1/messages`, `x-api-key`, `anthropic-version: 2026-10-21` | No sampling parameters (that API version rejects them). Optional `FORECAST_LLM_ANTHROPIC_EFFORT` → `output_config.effort`. Reads `text` blocks only; `stop_reason: refusal` → `REFUSAL`. |
| `ReplayProvider` | none | Answers only exact recorded request hashes; a miss is a hard error. |
| `RecordingProvider` | wraps a live provider | Keeps model text and token usage for a cassette; no headers or keys. |

Keys and base URLs are read only from `FORECAST_LLM_*` values (process environment or
`--env-file`). Base URLs must be `https` (plain `http` only for localhost) and must not
contain credentials, query strings or fragments. Error messages are truncated to 300
characters with the key and bearer/`x-api-key` patterns redacted; providers' `repr`
hides the key. The HTTP stack is imported only when a live call is made.

## Limits and cost

All limits are explicit integers committed in every trace:

| Limit | Live default | Meaning |
| --- | --- | --- |
| `max_calls` | 1 | Calls per order; no automatic retry |
| `max_output_tokens` | 1500 (`--max-output-tokens`) | Sent as `max_tokens`; with reasoning models it also bounds thinking tokens |
| `timeout_s` | 60 (`--timeout-s`) | Per call |
| `max_cost_nano_usd` | required (`--max-cost-usd`) | Per-order ceiling |
| `input_/output_price_nano_usd_per_token` | required | Operator-supplied; 1000 = $1 per million tokens |

Before a call the engine computes a worst case: `(UTF-8 bytes of system+user + 64) ×
input price + max_output_tokens × output price`, and refuses the call if it would exceed
the remaining per-order budget. A failed attempt, or a success without reported usage, is
charged at that worst case. With `--live` the CLI also requires `--max-run-cost-usd` and
refuses to start unless *(orders that pass the evidence gate) × (per-order ceiling)* fits
it; with the five synthetic cases that is three orders. Costs are estimates from the
prices you supply, not invoices; check the provider's billing page after a live run.

The current prompt is 1,964 UTF-8 bytes. Worst cases per order with 1500 output tokens,
for illustration only (prices must be re-checked on the provider's live price page):

| Example prices (input / output per million tokens) | Flags | Worst case per order | Worst case for 3 orders |
| --- | --- | --- | --- |
| $0.10 / $0.50 | `--input-price-nano-usd-per-token 100 --output-price-nano-usd-per-token 500` | $0.00095 | $0.00286 |
| $2.00 / $10.00 | `2000` / `10000` | $0.019 | $0.057 |

## Trace format (`forecast-inference-trace/v1`)

Stored in the delivery as `content.inference_trace` and therefore covered by the delivery
SHA-256:

```json
{
  "schema_version": "forecast-inference-trace/v1",
  "provider": "anthropic | openai_compatible | fixture",
  "api_base": "https://… (sanitized) or null",
  "model": "requested model",
  "limits": {"max_calls": 1, "max_output_tokens": 1500, "timeout_s": 60, "max_cost_nano_usd": 0,
             "input_price_nano_usd_per_token": 0, "output_price_nano_usd_per_token": 0},
  "temperature_milli": null, "options": {"effort": "low"},
  "pricing_note": "Cost is an estimate from operator-supplied integer prices, not a provider invoice.",
  "calls": [{
    "index": 0, "role": "analyst",
    "request": {"sha256": "…", "model": "…", "system": "…", "user": "…", "max_output_tokens": 1500,
                "temperature_milli": null, "options": {}},
    "outcome": "OK | TIMEOUT | HTTP_ERROR | TRANSPORT_ERROR | MALFORMED_RESPONSE | REFUSAL | BUDGET_EXCEEDED",
    "error": null,
    "response": {"text": "…", "sha256": "…", "finish_reason": "…", "model_reported": "…", "provider_response_id": "…"},
    "usage": {"input_tokens": 0, "output_tokens": 0, "source": "provider | worst_case_estimate | not_called"},
    "cost_estimate_nano_usd": 0, "over_budget": false, "attestation": null
  }],
  "totals": {"calls_attempted": 1, "calls_refused": 0, "provider_input_tokens": 0,
             "provider_output_tokens": 0, "cost_estimate_nano_usd": 0}
}
```

Request hashes use the domain `forecast-inference/v1:request\n` over canonical JSON of
model, prompts, token limit, temperature and options; response hashes use
`forecast-inference/v1:response\n` over the UTF-8 text. No wall-clock timestamps or
latencies are committed, so a live run and a replay of its recorded cassette produce the
same delivery hash.

`attestation` is always `null` today. NEAR AI Cloud advertises TEE attestation, but this
code does not fetch or verify it; an attestation will be recorded only after it is
actually obtained, together with what was and was not verified.

## Replay validation: what it proves

`validate_bundle` dispatches LLM deliveries to `validate_llm_bundle`, which rebuilds the
prompt from the committed inputs, checks every recorded request hash, feeds the recorded
model text back through the same gates, critic and verifier, recomputes costs from the
committed limits, and compares the complete canonical bundle. Tampering with the
probability, critic findings, usage, limits that contradict a recorded call, or adding an
unrecorded call is rejected even if the outer hash is recomputed.

Replay does **not** prove that a provider produced the text: a bundle rebuilt around
fabricated model text is self-consistent (a test documents this). Provenance relies on
the hash bound at submission (and, in future, provider attestation or signed responses).

## Cassettes (`forecast-inference-cassette/v1`)

A cassette stores, per request hash, the outcome and either the model text with usage or
the error string, plus the provider kind, sanitized base URL, model, the limits and the
request options/temperature used. Replay uses all of them so hashes reproduce (the
2026-11-08 live run is replayed with identical delivery hashes). Two origins exist and are enforced:

- `HAND_AUTHORED_SYNTHETIC` (provider must be `fixture`, prices zero):
  `fixtures/llm_cassettes/hand_authored_analyst.json`. **No model wrote these answers.**
  They let anyone run the LLM path offline. Regenerate after a prompt change with
  `python3 -m forecast_swarm.fixture_cassette --write`; a test fails if it is stale.
- `RECORDED_LIVE` (a real provider kind): written by `--live --record PATH`. Contains
  model text over synthetic inputs and token counts; no headers, keys or account data.
  Committing one is a publication decision for the owner.

## Commands

```sh
# Offline LLM path (hand-authored cassette; no network, no cost)
python3 -m forecast_swarm.walkthrough --roles llm --replay fixtures/llm_cassettes/hand_authored_analyst.json --out artifacts/walkthrough-llm
python3 -m forecast_swarm --roles llm --replay fixtures/llm_cassettes/hand_authored_analyst.json --out artifacts/demo-llm

# Live run (paid; only with the owner's explicit approval and limits)
cp .env.example .env.local   # fill in locally; .env.* is Git-ignored
python3 -m forecast_swarm.walkthrough --roles llm --live --env-file .env.local \
  --max-cost-usd 0.01 --max-run-cost-usd 0.03 \
  --record artifacts/live-cassette.json --out artifacts/walkthrough-live

# Replay that live run offline later (same delivery hashes)
python3 -m forecast_swarm.walkthrough --roles llm --replay artifacts/live-cassette.json --out artifacts/walkthrough-live-replay
```

In LLM mode the walkthrough writes `demo-consent.json` next to its outputs: synthetic
publication consent bound to that run's delivery hashes, because new model text means new
hashes and consent never transfers between hashes. The recorded local-sandbox receipts in
`docs/evidence/` bind scripted delivery hashes and therefore cannot be combined with
`--roles llm`. The testnet run also uses scripted roles; a chain run over LLM deliveries
has not been done.

## Tests

`tests/test_inference.py` (15) covers adapter request/response shapes, OpenAI token-field and reasoning-effort options, API version and
missing sampling parameters for Anthropic, refusal/HTTP/malformed failures with key
redaction, base-URL and price parsing, environment handling, `.env.example` emptiness,
budget refusal before sending, worst-case charging, record→replay equality and strict
cassette validation. `tests/test_llm_worker.py` (20) covers every output-gate rule,
withheld post-cutoff citations, prompt content, no call when the evidence gate fails,
provider failures, budget exhaustion, actual-cost overrun, tampering, the replay
limitation above, fixture freshness, report determinism and encyclopedia adaptation,
distinct requests per order (so a live run and its replay agree), unsafe CLI combinations, live setup without contacting anyone, and the full walkthrough
in a subprocess with sockets disabled.

## Limitations

- Only one live run (three calls, one model) exists; model quality, latency and refusal
  rate across inputs are unknown. Latency is not recorded.
- The model sees synthetic fixtures only; no live data source is connected.
- One sample per order: no ensembling, self-consistency or calibration. No accuracy claim.
- Prices are operator-supplied; costs are estimates.
- Gates prove structure, citation existence and the absence of obvious post-cutoff dates,
  not semantic support or truthfulness. The date gate matches only ISO `YYYY-MM-DD`
  strings; "November 3, 2026" or `03.11.2026` after the cutoff would pass it.
- The `timeout_s` limit is applied by `urllib` per socket operation (connect, each read),
  not to the whole request, so a slow-dripping provider can exceed it in total. The
  response body is read without a size bound before it is parsed.
- TEE attestation is not fetched or verified.
- The escrow contract does not know which role mode produced a delivery: it binds an
  order hash and a delivery hash, and the order hash is the same for scripted and LLM
  deliveries of one order.
