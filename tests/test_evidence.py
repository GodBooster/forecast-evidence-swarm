import copy
import hashlib
import unittest

from forecast_swarm import SCHEMA_VERSION
from forecast_swarm.evidence import (
    build_bundle, canonical_bytes, commitment, quality, validate_bundle,
)


def synthetic_case():
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario": "test",
        "title": "Synthetic test fixture",
        "synthetic": True,
        "terms": {
            "job_id": "test-1", "question": "Will the event occur?",
            "source": "Synthetic Registry", "decision_at": "2030-01-01T00:00:00Z",
            "delivery_deadline": "2030-01-02T00:00:00Z",
            "resolution_at": "2030-02-01T00:00:00Z",
            "acceptance_deadline": "2030-01-03T00:00:00Z",
            "dispute_deadline": "2030-01-04T00:00:00Z", "budget_credits": 10,
        },
        "evidence": [{
            "id": "obs-1", "source": "Synthetic Registry",
            "observed_at": "2029-12-30T00:00:00Z",
            "available_at": "2029-12-31T00:00:00Z", "yes_count": 3,
            "sample_count": 5,
        }],
        "outcome": None,
        "evaluation_at": "2030-02-02T00:00:00Z",
    }


class EvidenceTests(unittest.TestCase):
    def test_cutoff_checks_observation_and_availability_independently(self):
        for key, expected in (("observed_at", "OBSERVED_AFTER_DECISION"),
                              ("available_at", "AVAILABLE_AFTER_DECISION")):
            case = synthetic_case()
            case["evidence"][0][key] = "2030-01-01T00:00:01Z"
            bundle = build_bundle(case)
            self.assertEqual(bundle["content"]["delivery_validity"], "INVALID")
            self.assertIn("obs-1:" + expected,
                          bundle["content"]["roles"]["verifier"]["reasons"])

    def test_missing_counts_differ_from_zero_counts(self):
        case = synthetic_case()
        case["evidence"][0]["yes_count"] = None
        missing = build_bundle(case)["content"]
        self.assertEqual(missing["delivery_validity"], "INSUFFICIENT_DATA")
        self.assertIn("obs-1:MISSING_YES_COUNT", missing["roles"]["verifier"]["reasons"])
        case = synthetic_case()
        case["evidence"][0].update(yes_count=0, sample_count=0)
        zero = build_bundle(case)["content"]
        self.assertEqual(zero["delivery_validity"], "INSUFFICIENT_DATA")
        self.assertIn("obs-1:EMPTY_SAMPLE", zero["roles"]["verifier"]["reasons"])
        self.assertNotIn("obs-1:MISSING_YES_COUNT", zero["roles"]["verifier"]["reasons"])

        case = synthetic_case()
        case["evidence"][0].update(yes_count=0, sample_count=4)
        valid_zero = build_bundle(case)["content"]
        self.assertEqual(valid_zero["delivery_validity"], "VALID")
        self.assertEqual(valid_zero["roles"]["analyst"]["probability_bps"], 0)

    def test_missing_source_and_empty_evidence_are_insufficient(self):
        cases = []
        case = synthetic_case()
        case["evidence"][0]["source"] = None
        cases.append((case, "obs-1:MISSING_SOURCE"))
        case = synthetic_case()
        case["evidence"] = []
        cases.append((case, "NO_EVIDENCE"))
        for case, reason in cases:
            with self.subTest(reason=reason):
                content = build_bundle(case)["content"]
                self.assertEqual(content["delivery_validity"], "INSUFFICIENT_DATA")
                self.assertIn(reason, content["roles"]["verifier"]["reasons"])

    def test_cutoff_is_inclusive_for_observed_and_available(self):
        for observed, available in (
            ("2030-01-01T00:00:00Z", "2030-01-01T00:00:00Z"),
            ("2029-12-31T23:59:59Z", "2029-12-31T23:59:59Z"),
        ):
            with self.subTest(observed=observed, available=available):
                case = synthetic_case()
                case["evidence"][0].update(observed_at=observed, available_at=available)
                self.assertEqual(build_bundle(case)["content"]["delivery_validity"], "VALID")

    def test_counts_require_non_boolean_integers(self):
        for value in (True, 1.0, "1", -1):
            with self.subTest(value=value):
                case = synthetic_case()
                case["evidence"][0]["yes_count"] = value
                with self.assertRaises(ValueError):
                    build_bundle(case)

    def test_quality_requires_final_correct_source_and_available_timing(self):
        cases = []
        for changes, reason in [
            ({"final": False}, "OUTCOME_NOT_FINAL"),
            ({"source": "Other Registry"}, "OUTCOME_SOURCE_MISSING_OR_MISMATCH"),
            ({"resolved_at": "2030-01-31T00:00:00Z"}, "RESOLVED_BEFORE_RESOLUTION_TIME"),
            ({"available_at": "2030-02-03T00:00:00Z"}, "OUTCOME_NOT_YET_AVAILABLE"),
        ]:
            case = synthetic_case()
            case["outcome"] = {"source": "Synthetic Registry", "value": 1,
                               "final": True, "resolved_at": "2030-02-01T01:00:00Z",
                               "available_at": "2030-02-01T02:00:00Z"}
            case["outcome"].update(changes)
            cases.append((case, reason))
        for case, reason in cases:
            with self.subTest(reason=reason):
                scored = quality(case, build_bundle(case)["content"]["roles"]["analyst"])
                self.assertEqual(scored["status"], "INSUFFICIENT_DATA")
                self.assertIn(reason, scored["reasons"])

    def test_resolution_and_availability_must_have_sane_order(self):
        case = synthetic_case()
        case["outcome"] = {"source": "Synthetic Registry", "value": 1,
                           "final": True, "resolved_at": "2030-02-01T01:00:00Z",
                           "available_at": "2030-02-01T00:30:00Z"}
        scored = quality(case, build_bundle(case)["content"]["roles"]["analyst"])
        self.assertIn("OUTCOME_AVAILABLE_BEFORE_RESOLUTION", scored["reasons"])

    def test_outcome_zero_and_exact_evaluation_boundaries_are_valid(self):
        case = synthetic_case()
        case["evaluation_at"] = "2030-02-01T02:00:00Z"
        case["outcome"] = {"source": "Synthetic Registry", "value": 0,
                           "final": True, "resolved_at": "2030-02-01T00:00:00Z",
                           "available_at": "2030-02-01T02:00:00Z"}
        analysis = build_bundle(case)["content"]["roles"]["analyst"]
        scored = quality(case, analysis)
        self.assertEqual(scored["status"], "EVALUATED")
        self.assertFalse(scored["direction_correct"])

    def test_unknown_or_incomplete_outcome_is_insufficient(self):
        base = {"source": "Synthetic Registry", "value": 1, "final": True,
                "resolved_at": "2030-02-01T01:00:00Z",
                "available_at": "2030-02-01T02:00:00Z"}
        cases = []
        case = synthetic_case()
        case["outcome"] = {**base, "value": None}
        cases.append((case, "UNKNOWN_OUTCOME"))
        case = synthetic_case()
        case["outcome"] = {**base, "resolved_at": None}
        cases.append((case, "MISSING_OUTCOME_TIMING"))
        case = synthetic_case()
        case["outcome"] = {**base, "available_at": None}
        cases.append((case, "MISSING_OUTCOME_TIMING"))
        case = synthetic_case()
        case["outcome"] = {**base, "available_at": "2030-02-03T00:00:00Z"}
        cases.append((case, "OUTCOME_NOT_YET_AVAILABLE"))
        for case, reason in cases:
            with self.subTest(reason=reason, outcome=case["outcome"]):
                analysis = build_bundle(case)["content"]["roles"]["analyst"]
                scored = quality(case, analysis)
                self.assertEqual(scored["status"], "INSUFFICIENT_DATA")
                self.assertIn(reason, scored["reasons"])

    def test_timestamp_rejects_naive_and_offset_forms(self):
        for key in ("observed_at", "available_at"):
            for value in ("2029-12-31T23:59:59", "2029-12-31T23:59:59+00:00", "2029-12-31T23:59:59-05:00"):
                with self.subTest(key=key, value=value):
                    case = synthetic_case()
                    case["evidence"][0][key] = value
                    with self.assertRaises(ValueError):
                        build_bundle(case)

    def test_duplicate_ids_and_successes_above_sample_are_rejected(self):
        case = synthetic_case()
        duplicate = copy.deepcopy(case["evidence"][0])
        case["evidence"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "Duplicate evidence id"):
            build_bundle(case)
        case = synthetic_case()
        case["evidence"][0].update(yes_count=6, sample_count=5)
        with self.assertRaisesRegex(ValueError, "yes_count cannot exceed sample_count"):
            build_bundle(case)

    def test_canonical_known_vector_and_domain_separated_digest(self):
        value = {"z": 2, "a": [True, "é"]}
        canonical = b'{"a":[true,"\xc3\xa9"],"z":2}'
        self.assertEqual(canonical_bytes(value), canonical)
        expected = hashlib.sha256((SCHEMA_VERSION + ":demo\n").encode("ascii") + canonical).hexdigest()
        self.assertEqual(commitment("demo", value), expected)
        self.assertEqual(commitment("demo", value), "cc141401889f6d6f0955fbc0b41da27009b80e2f80dd356a78a15228fb150b21")

    def test_stable_outputs_and_evidence_order(self):
        first = synthetic_case()
        first["evidence"].append({
            "id": "obs-2", "source": "Synthetic Registry",
            "observed_at": "2029-12-29T00:00:00Z", "available_at": "2029-12-30T00:00:00Z",
            "yes_count": 2, "sample_count": 4,
        })
        second = copy.deepcopy(first)
        second["evidence"].reverse()
        a, b = build_bundle(first), build_bundle(second)
        self.assertEqual(a, b)
        self.assertEqual(a, build_bundle(first))

    def test_outcome_changes_quality_but_not_delivery_commitment(self):
        unresolved = synthetic_case()
        resolved = copy.deepcopy(unresolved)
        resolved["outcome"] = {"source": "Synthetic Registry", "value": 1,
                               "final": True, "resolved_at": "2030-02-01T01:00:00Z",
                               "available_at": "2030-02-01T02:00:00Z"}
        a, b = build_bundle(unresolved), build_bundle(resolved)
        self.assertEqual(a["sha256"], b["sha256"])
        analysis = a["content"]["roles"]["analyst"]
        self.assertNotEqual(quality(unresolved, analysis), quality(resolved, analysis))

    def test_validate_detects_tampering_version_and_unknown_fields(self):
        original = build_bundle(synthetic_case())
        self.assertEqual(validate_bundle(original), original)
        mutations = []
        changed = copy.deepcopy(original)
        changed["content"]["roles"]["analyst"]["probability_bps"] += 1
        mutations.append(changed)
        changed = copy.deepcopy(original)
        changed["content"]["inputs"]["schema_version"] = "forecast-evidence-swarm/v9"
        mutations.append(changed)
        changed = copy.deepcopy(original)
        changed["content"]["surprise"] = True
        mutations.append(changed)
        changed = copy.deepcopy(original)
        changed["content"]["inputs"]["evidence"][0]["yes_count"] = 4
        changed["content"]["evidence_sha256"] = commitment(
            "evidence", changed["content"]["inputs"]["evidence"])
        mutations.append(changed)
        for bundle in mutations:
            with self.subTest(bundle=bundle):
                with self.assertRaises(ValueError):
                    validate_bundle(bundle)

    def test_outcome_does_not_enter_forecast_or_verification(self):
        case = synthetic_case()
        baseline = build_bundle(case)["content"]
        case["outcome"] = {"source": "Wrong source", "value": 0, "final": False,
                           "resolved_at": "2030-02-01T01:00:00Z",
                           "available_at": "2030-02-01T02:00:00Z"}
        updated = build_bundle(case)["content"]
        for role in ("analyst", "critic", "verifier"):
            self.assertEqual(baseline["roles"][role], updated["roles"][role])
        self.assertEqual(baseline["delivery_validity"], updated["delivery_validity"])


if __name__ == "__main__":
    unittest.main()
