"""Versioned inputs, deterministic scripted roles, and byte commitments."""

import hashlib
import json
import re
from datetime import datetime

from . import SCHEMA_VERSION


def canonical_bytes(value):
    """Project canonical JSON v1 (not RFC 8785); floats are forbidden."""
    def check(item):
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child)
            return
        raise ValueError("Canonical v1 accepts only null, strings, booleans, integers, lists and string-keyed objects")

    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def commitment(domain, value):
    return hashlib.sha256((SCHEMA_VERSION + ":" + domain + "\n").encode("ascii")
                          + canonical_bytes(value)).hexdigest()


def timestamp(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError("Timestamps must use YYYY-MM-DDTHH:MM:SSZ (UTC, whole seconds)")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def fields(value, expected, label):
    if type(value) is not dict or set(value) != set(expected.split()):
        raise ValueError(f"Unexpected or missing {label} fields")


def nonempty(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")


def integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")


def validate_terms(terms):
    fields(terms, "job_id question source decision_at delivery_deadline resolution_at acceptance_deadline dispute_deadline budget_credits", "terms")
    for key in ("job_id", "question", "source"):
        nonempty(terms[key], key)
    times = {key: timestamp(terms[key]) for key in
             ("decision_at", "delivery_deadline", "resolution_at", "acceptance_deadline", "dispute_deadline")}
    if not (times["decision_at"] < times["delivery_deadline"] < times["resolution_at"]):
        raise ValueError("Require decision_at < delivery_deadline < resolution_at")
    if not (times["delivery_deadline"] < times["acceptance_deadline"] < times["dispute_deadline"]):
        raise ValueError("Require delivery_deadline < acceptance_deadline < dispute_deadline")
    integer(terms["budget_credits"], "budget_credits", 1)


def validate_case(case):
    fields(case, "schema_version scenario title synthetic terms evidence outcome evaluation_at", "case")
    if case["schema_version"] != SCHEMA_VERSION or case["synthetic"] is not True:
        raise ValueError("Only v1 explicitly synthetic fixtures are supported")
    for key in ("scenario", "title"):
        nonempty(case[key], key)
    validate_terms(case["terms"])
    evaluation = timestamp(case["evaluation_at"])
    if evaluation < timestamp(case["terms"]["decision_at"]):
        raise ValueError("evaluation_at cannot precede decision_at")
    if type(case["evidence"]) is not list:
        raise ValueError("evidence must be a list")
    seen = set()
    for item in case["evidence"]:
        fields(item, "id source observed_at available_at yes_count sample_count", "evidence")
        nonempty(item["id"], "evidence id")
        if item["id"] in seen:
            raise ValueError("Duplicate evidence id")
        seen.add(item["id"])
        if item["source"] is not None:
            nonempty(item["source"], "evidence source")
        for key in ("observed_at", "available_at"):
            if item[key] is not None:
                timestamp(item[key])
        for key in ("yes_count", "sample_count"):
            if item[key] is not None:
                integer(item[key], key)
        if item["yes_count"] is not None and item["sample_count"] is not None and item["yes_count"] > item["sample_count"]:
            raise ValueError("yes_count cannot exceed sample_count")
    outcome = case["outcome"]
    if outcome is not None:
        fields(outcome, "source value final resolved_at available_at", "outcome")
        if outcome["source"] is not None:
            nonempty(outcome["source"], "outcome source")
        if outcome["value"] is not None and (type(outcome["value"]) is not int or outcome["value"] not in (0, 1)):
            raise ValueError("outcome value must be 0, 1 or null")
        if type(outcome["final"]) is not bool:
            raise ValueError("outcome final must be boolean")
        for key in ("resolved_at", "available_at"):
            if outcome[key] is not None:
                timestamp(outcome[key])


def verifier(case):
    """Scripted rules: availability, provenance and sufficient sample count."""
    cutoff = timestamp(case["terms"]["decision_at"])
    issues, missing = [], []
    if not case["evidence"]:
        missing.append("NO_EVIDENCE")
    for item in case["evidence"]:
        prefix = item["id"] + ":"
        for key in ("source", "observed_at", "available_at", "yes_count", "sample_count"):
            if item[key] is None:
                missing.append(prefix + "MISSING_" + key.upper())
        if item["source"] is not None and item["source"] != case["terms"]["source"]:
            issues.append(prefix + "SOURCE_MISMATCH")
        observed = timestamp(item["observed_at"]) if item["observed_at"] else None
        available = timestamp(item["available_at"]) if item["available_at"] else None
        if observed and observed > cutoff:
            issues.append(prefix + "OBSERVED_AFTER_DECISION")
        if available and available > cutoff:
            issues.append(prefix + "AVAILABLE_AFTER_DECISION")
        if observed and available and available < observed:
            issues.append(prefix + "AVAILABLE_BEFORE_OBSERVATION")
        if item["sample_count"] == 0:
            missing.append(prefix + "EMPTY_SAMPLE")
    status = "INVALID" if issues else "INSUFFICIENT_DATA" if missing else "VALID"
    return {"role": "verifier", "mode": "scripted", "status": status,
            "reasons": sorted(issues + missing)}


def analyst(case, verification):
    # Deliberately only pre-decision evidence enters this calculation. No outcome.
    probability = None
    if verification["status"] == "VALID":
        yes = sum(item["yes_count"] for item in case["evidence"])
        total = sum(item["sample_count"] for item in case["evidence"])
        probability = (yes * 10000 + total // 2) // total
    return {"role": "analyst", "mode": "scripted", "probability_bps": probability,
            "method": "Synthetic historical frequency; half-up rounding to basis points.",
            "status": "FORECAST" if probability is not None else "ABSTAIN"}


def critic(analysis):
    return {"role": "critic", "mode": "scripted",
            "status": "CAUTION" if analysis["status"] == "FORECAST" else "BLOCKED",
            "findings": ["Synthetic observations do not establish predictive skill.",
                         "Historical frequency assumes comparable, independent observations; this is unproven.",
                         "A valid delivery may still contain an incorrect forecast."]}


def quality(case, analysis):
    probability = analysis["probability_bps"]
    reasons = []
    outcome = case["outcome"]
    if probability is None:
        reasons.append("NO_VALID_FORECAST")
    if outcome is None:
        reasons.append("MISSING_OUTCOME")
    else:
        if outcome["source"] != case["terms"]["source"]:
            reasons.append("OUTCOME_SOURCE_MISSING_OR_MISMATCH")
        if outcome["value"] is None:
            reasons.append("UNKNOWN_OUTCOME")
        if not outcome["final"]:
            reasons.append("OUTCOME_NOT_FINAL")
        resolved, available = outcome["resolved_at"], outcome["available_at"]
        if resolved is None or available is None:
            reasons.append("MISSING_OUTCOME_TIMING")
        else:
            if timestamp(resolved) < timestamp(case["terms"]["resolution_at"]):
                reasons.append("RESOLVED_BEFORE_RESOLUTION_TIME")
            if timestamp(available) < timestamp(resolved):
                reasons.append("OUTCOME_AVAILABLE_BEFORE_RESOLUTION")
            if max(timestamp(resolved), timestamp(available)) > timestamp(case["evaluation_at"]):
                reasons.append("OUTCOME_NOT_YET_AVAILABLE")
    result = {"status": "INSUFFICIENT_DATA" if reasons else "EVALUATED",
              "reasons": sorted(reasons), "direction_correct": None,
              "brier_score_scaled_1e8": None}
    if not reasons:
        result["direction_correct"] = int(probability >= 5000) == outcome["value"]
        result["brier_score_scaled_1e8"] = (probability - outcome["value"] * 10000) ** 2
    return result


def build_bundle(case):
    validate_case(case)
    # Deep copy through the canonical form; caller mutation cannot change a bundle.
    inputs = json.loads(canonical_bytes(case))
    inputs["evidence"].sort(key=lambda item: item["id"])
    verification = verifier(inputs)
    analysis = analyst(inputs, verification)
    # Resolution is a later, separate evaluation, never part of a delivery.
    del inputs["outcome"]
    del inputs["evaluation_at"]
    content = {"schema_version": SCHEMA_VERSION, "inputs": inputs,
               "evidence_sha256": commitment("evidence", inputs["evidence"]),
               "roles": {"analyst": analysis, "critic": critic(analysis), "verifier": verification},
               "delivery_validity": verification["status"]}
    return {"content": content, "sha256": commitment("bundle", content)}


def validate_bundle(bundle):
    fields(bundle, "content sha256", "bundle")
    try:
        inputs = bundle["content"]["inputs"]
        expected = build_bundle({**inputs, "outcome": None,
                                 "evaluation_at": inputs["terms"]["decision_at"]})
    except (KeyError, TypeError) as exc:
        raise ValueError("Malformed bundle") from exc
    if canonical_bytes(expected) != canonical_bytes(bundle):
        raise ValueError("Bundle differs from deterministic replay or commitment")
    return expected
