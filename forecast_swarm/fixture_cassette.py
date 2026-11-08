"""Hand-authored synthetic analyst cassette for offline LLM-mode demos and tests.

No model wrote these responses. They are fixed example outputs, keyed by the
exact prompt each synthetic case produces, so `--roles llm --replay` exercises
the real prompt builder, output gates, trace and commitments without network
access or cost. The provider is `fixture` and the origin HAND_AUTHORED_SYNTHETIC,
and both appear in every committed trace and report.

    python3 -m forecast_swarm.fixture_cassette --check   # committed file is current
    python3 -m forecast_swarm.fixture_cassette --write   # regenerate after a prompt change
"""

import argparse
import json
import sys
from pathlib import Path

from .evidence import canonical_bytes, validate_case, verifier
from .inference import CASSETTE_SCHEMA, Limits, make_request, validate_cassette
from .llm_roles import build_prompt, pre_cutoff_evidence

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures" / "synthetic_cases.json"
CASSETTE = ROOT / "fixtures" / "llm_cassettes" / "hand_authored_analyst.json"
MODEL = "hand-authored-synthetic-analyst"
LIMITS = Limits(max_calls=1, max_output_tokens=1200, timeout_s=60, max_cost_nano_usd=10_000_000,
                input_price_nano_usd_per_token=0, output_price_nano_usd_per_token=0)

# Authored outputs keyed by (yes_count, sample_count) of the single pre-cutoff batch.
AUTHORED = {
    (15, 20): {
        "probability_bps": 7200,
        "evidence_ids": ["batch-01"],
        "rationale": ("batch-01 reports 15 YES in 20 synthetic observations (75%). With a single small batch "
                      "the estimate is pulled slightly toward 50%."),
        "uncertainty": {"low_bps": 5200, "high_bps": 8700,
                        "drivers": ["Only one batch of 20 observations.",
                                    "Comparability of past observations with the next event is unproven."]},
    },
    (0, 20): {
        "probability_bps": 600,
        "evidence_ids": ["batch-01"],
        "rationale": ("batch-01 reports 0 YES in 20 synthetic observations. Zero observed successes is a "
                      "known count, not missing data, but it does not make YES impossible."),
        "uncertainty": {"low_bps": 0, "high_bps": 2000,
                        "drivers": ["Only one batch of 20 observations.",
                                    "A zero count gives weak information about rare outcomes."]},
    },
}


def build_cassette():
    interactions = {}
    for case in json.loads(FIXTURES.read_text(encoding="utf-8")):
        validate_case(case)
        inputs = json.loads(canonical_bytes(case))
        inputs["evidence"].sort(key=lambda item: item["id"])
        if verifier(inputs)["status"] != "VALID":
            continue  # gate prevents a call; nothing to author
        provided = pre_cutoff_evidence(inputs)
        key = (sum(i["yes_count"] for i in provided), sum(i["sample_count"] for i in provided))
        system, user = build_prompt(inputs, provided)
        request = make_request(MODEL, system, user, LIMITS.max_output_tokens)
        text = json.dumps(AUTHORED[key], ensure_ascii=False)
        interactions[request["sha256"]] = {
            "request_sha256": request["sha256"], "outcome": "OK", "error": None,
            "response": {"text": text, "finish_reason": "fixture", "model_reported": None,
                         "provider_response_id": None, "input_tokens": None, "output_tokens": None}}
    cassette = {
        "schema_version": CASSETTE_SCHEMA, "origin": "HAND_AUTHORED_SYNTHETIC", "synthetic_inputs": True,
        "notice": ("Hand-authored synthetic analyst outputs for offline demos and tests. No model or provider "
                   "was called; prices are zero. Replaying exercises the real prompt, gates, trace and hashes."),
        "provider": "fixture", "api_base": None, "model": MODEL, "limits": LIMITS.record(),
        "temperature_milli": None, "options": {},
        "interactions": [interactions[k] for k in sorted(interactions)]}
    return validate_cassette(cassette)


def render(cassette):
    return json.dumps(cassette, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check or regenerate the hand-authored analyst cassette")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    text = render(build_cassette())
    if args.write:
        CASSETTE.parent.mkdir(parents=True, exist_ok=True)
        CASSETTE.write_text(text, encoding="utf-8")
        print(f"Wrote {CASSETTE}")
        return 0
    current = CASSETTE.read_text(encoding="utf-8") if CASSETTE.exists() else None
    if current != text:
        print("Cassette is stale; run with --write after reviewing the prompt change", file=sys.stderr)
        return 1
    print("Cassette matches the current prompt builder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
