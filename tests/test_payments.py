import copy
import json
import unittest
from pathlib import Path

from forecast_swarm.evidence import build_bundle, commitment
from forecast_swarm.payments import JobSimulator, TransitionError


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / "fixtures" / "synthetic_cases.json").read_text())
GOOD_CASE = next(case for case in FIXTURES if case["scenario"] == "valid_wrong")
FUTURE_CASE = next(case for case in FIXTURES if case["scenario"] == "future_data")

CUSTOMER, WORKER, RESOLVER = "customer-1", "worker-1", "resolver-1"
DECISION = "2026-11-01T12:00:00Z"
BEFORE_DELIVERY = "2026-11-01T12:59:59Z"
DELIVERY = "2026-11-01T13:00:00Z"
BEFORE_ACCEPTANCE = "2026-11-01T13:59:59Z"
ACCEPTANCE = "2026-11-01T14:00:00Z"
BEFORE_DISPUTE = "2026-11-01T15:59:59Z"
DISPUTE = "2026-11-01T16:00:00Z"


def make_job():
    return JobSimulator(GOOD_CASE["terms"], CUSTOMER, RESOLVER, DECISION)


def good_bundle():
    return build_bundle(GOOD_CASE)


def assigned_job():
    job = make_job()
    job.assign(CUSTOMER, WORKER, DECISION)
    return job


def submitted_job():
    job = assigned_job()
    job.submit(WORKER, good_bundle(), DECISION)
    return job


class PaymentTests(unittest.TestCase):
    def assert_conserved(self, job):
        snapshot = job.snapshot()
        self.assertEqual(snapshot["escrow"] + snapshot["paid_to_worker"] +
                         snapshot["refunded_to_customer"], snapshot["budget"])
        self.assertGreaterEqual(snapshot["escrow"], 0)
        self.assertFalse(snapshot["paid_to_worker"] and snapshot["refunded_to_customer"])

    def test_actor_permissions_for_assign_submit_accept_dispute_resolve_cancel(self):
        actions = [
            (make_job(), lambda j: j.assign(WORKER, "worker-2", DECISION)),
            (assigned_job(), lambda j: j.submit(CUSTOMER, good_bundle(), DECISION)),
            (submitted_job(), lambda j: j.accept(WORKER, BEFORE_ACCEPTANCE)),
            (submitted_job(), lambda j: j.dispute(RESOLVER, BEFORE_ACCEPTANCE)),
            (disputed_job(), lambda j: j.resolve(CUSTOMER, True, BEFORE_DISPUTE)),
            (make_job(), lambda j: j.cancel(RESOLVER, DECISION)),
        ]
        for job, action in actions:
            before = job.snapshot()
            with self.subTest(state=before["state"]):
                with self.assertRaises(TransitionError):
                    action(job)
                self.assertEqual(job.snapshot(), before)

    def test_creation_budget_time_and_distinct_roles_are_enforced(self):
        for budget in (0, -1, True, 1.5):
            with self.subTest(budget=budget):
                terms = copy.deepcopy(GOOD_CASE["terms"])
                terms["budget_credits"] = budget
                with self.assertRaises(ValueError):
                    JobSimulator(terms, CUSTOMER, RESOLVER, DECISION)
        with self.assertRaises(ValueError):
            JobSimulator(GOOD_CASE["terms"], CUSTOMER, CUSTOMER, DECISION)
        with self.assertRaises(ValueError):
            JobSimulator(GOOD_CASE["terms"], CUSTOMER, RESOLVER, "2026-11-01T12:00:01Z")
        for worker in (CUSTOMER, RESOLVER):
            job = make_job()
            before = job.snapshot()
            with self.assertRaises(TransitionError):
                job.assign(CUSTOMER, worker, DECISION)
            self.assertEqual(job.snapshot(), before)

    def test_repeated_submission_payment_and_refund_are_rejected(self):
        job = submitted_job()
        before = job.snapshot()
        with self.assertRaises(TransitionError):
            job.submit(WORKER, good_bundle(), DECISION)
        self.assertEqual(job.snapshot(), before)
        job.accept(CUSTOMER, BEFORE_ACCEPTANCE)
        paid = job.snapshot()
        with self.assertRaises(TransitionError):
            job.accept(CUSTOMER, BEFORE_ACCEPTANCE)
        self.assertEqual(job.snapshot(), paid)
        job = submitted_job()
        job.timeout("observer-one", ACCEPTANCE)
        refunded = job.snapshot()
        with self.assertRaises(TransitionError):
            job.timeout("observer-two", ACCEPTANCE)
        self.assertEqual(job.snapshot(), refunded)

    def test_assign_and_cancel_only_open_and_cancel_refunds(self):
        job = make_job()
        job.cancel(CUSTOMER, DECISION)
        self.assertEqual(job.snapshot()["state"], "REFUNDED")
        self.assertEqual(job.snapshot()["refunded_to_customer"], 100)
        for action in (lambda: job.cancel(CUSTOMER, DECISION),
                       lambda: job.assign(CUSTOMER, WORKER, DECISION)):
            with self.assertRaises(TransitionError):
                action()
        self.assert_conserved(job)
        for state_job in (assigned_job(), submitted_job()):
            before = state_job.snapshot()
            with self.assertRaises(TransitionError):
                state_job.cancel(CUSTOMER, BEFORE_DELIVERY)
            self.assertEqual(state_job.snapshot(), before)

    def test_submit_decision_inclusive_and_delivery_deadline_exclusive(self):
        job = assigned_job()
        with self.assertRaises(TransitionError):
            job.submit(WORKER, good_bundle(), "2026-11-01T11:59:59Z")
        self.assertEqual(job.snapshot()["state"], "ASSIGNED")
        job.submit(WORKER, good_bundle(), DECISION)
        self.assertEqual(job.snapshot()["state"], "SUBMITTED")
        job = assigned_job()
        with self.assertRaises(TransitionError):
            job.submit(WORKER, good_bundle(), DELIVERY)
        self.assertEqual(job.snapshot()["state"], "ASSIGNED")
        job.submit(WORKER, good_bundle(), BEFORE_DELIVERY)

    def test_delivery_timeout_is_inclusive_and_before_deadline_rejected(self):
        for job in (make_job(), assigned_job()):
            before = job.snapshot()
            with self.assertRaises(TransitionError):
                job.timeout("anyone", BEFORE_DELIVERY)
            self.assertEqual(job.snapshot(), before)
            job.timeout("anyone", DELIVERY)
            self.assertEqual(job.snapshot()["state"], "REFUNDED")
            self.assertEqual(job.snapshot()["refunded_to_customer"], 100)
            self.assert_conserved(job)

    def test_accept_before_deadline_pays_but_exact_acceptance_deadline_times_out(self):
        job = submitted_job()
        job.accept(CUSTOMER, BEFORE_ACCEPTANCE)
        self.assertEqual(job.snapshot()["state"], "ACCEPTED")
        self.assertEqual(job.snapshot()["paid_to_worker"], 100)
        self.assert_conserved(job)
        job = submitted_job()
        with self.assertRaises(TransitionError):
            job.accept(CUSTOMER, ACCEPTANCE)
        self.assertEqual(job.snapshot()["state"], "SUBMITTED")
        job.timeout("anyone", ACCEPTANCE)
        self.assertEqual(job.snapshot()["state"], "REFUNDED")
        self.assert_conserved(job)

    def test_dispute_deadline_exact_refunds_and_does_not_resolve(self):
        job = submitted_job()
        with self.assertRaises(TransitionError):
            job.dispute(CUSTOMER, ACCEPTANCE)
        job.dispute(CUSTOMER, BEFORE_ACCEPTANCE)
        self.assertEqual(job.snapshot()["state"], "DISPUTED")
        with self.assertRaises(TransitionError):
            job.resolve(RESOLVER, True, DISPUTE)
        self.assertEqual(job.snapshot()["state"], "DISPUTED")
        job.timeout("anyone", DISPUTE)
        snap = job.snapshot()
        self.assertEqual(snap["state"], "REFUNDED")
        self.assertEqual(snap["refunded_to_customer"], 100)
        self.assertEqual(snap["paid_to_worker"], 0)
        self.assert_conserved(job)

    def test_disputed_resolution_can_pay_or_refund_and_unresolved_timeout_refunds(self):
        for pay in (True, False):
            with self.subTest(pay_worker=pay):
                job = disputed_job()
                job.resolve(RESOLVER, pay, BEFORE_DISPUTE)
                snap = job.snapshot()
                self.assertEqual(snap["state"], "ACCEPTED" if pay else "REFUNDED")
                self.assertEqual(snap["paid_to_worker"], 100 if pay else 0)
                self.assertEqual(snap["refunded_to_customer"], 0 if pay else 100)
                self.assert_conserved(job)
        job = disputed_job()
        with self.assertRaises(TransitionError):
            job.resolve(RESOLVER, "pay", BEFORE_DISPUTE)
        self.assertEqual(job.snapshot()["state"], "DISPUTED")
        job.timeout("anyone", DISPUTE)
        self.assertEqual(job.snapshot()["state"], "REFUNDED")

    def test_duplicate_terminal_accept_refund_and_same_time_calls_do_not_settle_twice(self):
        cases = []
        job = submitted_job()
        job.accept(CUSTOMER, BEFORE_ACCEPTANCE)
        cases.append((job, lambda j: j.timeout("anyone", BEFORE_ACCEPTANCE)))
        job = submitted_job()
        job.timeout("anyone", ACCEPTANCE)
        cases.append((job, lambda j: j.accept(CUSTOMER, ACCEPTANCE)))
        job = make_job()
        job.timeout("anyone", DELIVERY)
        cases.append((job, lambda j: j.cancel(CUSTOMER, DELIVERY)))
        job = disputed_job()
        job.resolve(RESOLVER, False, BEFORE_DISPUTE)
        cases.append((job, lambda j: j.resolve(RESOLVER, True, BEFORE_DISPUTE)))
        for job, duplicate in cases:
            before = job.snapshot()
            with self.subTest(state=before["state"], events=len(before["events"])):
                with self.assertRaises(TransitionError):
                    duplicate(job)
                self.assertEqual(job.snapshot(), before)
                self.assert_conserved(job)

    def test_unaccepted_submission_times_out_at_acceptance_deadline(self):
        job = submitted_job()
        job.timeout("anyone", ACCEPTANCE)
        self.assertEqual(job.snapshot()["state"], "REFUNDED")
        self.assertEqual(job.snapshot()["refunded_to_customer"], 100)
        self.assert_conserved(job)

    def test_submission_rejects_invalid_future_and_forged_delivery(self):
        job = assigned_job()
        invalid = build_bundle(FUTURE_CASE)
        with self.assertRaisesRegex(TransitionError, "terms do not match"):
            job.submit(WORKER, invalid, DECISION)
        self.assertEqual(job.snapshot()["state"], "ASSIGNED")

        wrong_terms = copy.deepcopy(GOOD_CASE)
        wrong_terms["evidence"][0]["available_at"] = "2026-11-01T12:00:01Z"
        future_bundle = build_bundle(wrong_terms)
        with self.assertRaisesRegex(TransitionError, "acceptance policy: INVALID"):
            job.submit(WORKER, future_bundle, DECISION)

        forged = copy.deepcopy(future_bundle)
        forged["content"]["delivery_validity"] = "VALID"
        forged["sha256"] = commitment("bundle", forged["content"])
        with self.assertRaises(ValueError):
            job.submit(WORKER, forged, DECISION)
        self.assertEqual(job.snapshot()["state"], "ASSIGNED")

    def test_mismatched_job_terms_rejected_without_mutation(self):
        job = assigned_job()
        mismatched = copy.deepcopy(GOOD_CASE)
        mismatched["terms"]["job_id"] = "other-job"
        before = job.snapshot()
        with self.assertRaisesRegex(TransitionError, "terms do not match"):
            job.submit(WORKER, build_bundle(mismatched), DECISION)
        self.assertEqual(job.snapshot(), before)

    def test_snapshots_and_input_mutations_cannot_change_simulator(self):
        terms = copy.deepcopy(GOOD_CASE["terms"])
        job = JobSimulator(terms, CUSTOMER, RESOLVER, DECISION)
        terms["budget_credits"] = 999
        job.assign(CUSTOMER, WORKER, DECISION)
        bundle = good_bundle()
        job.submit(WORKER, bundle, DECISION)
        saved = job.snapshot()
        saved["events"][0]["actor"] = "tampered"
        saved["escrow"] = 0
        bundle["content"]["roles"]["analyst"]["probability_bps"] = 0
        self.assertEqual(job.snapshot()["budget"], 100)
        self.assertEqual(job.snapshot()["escrow"], 100)
        self.assertEqual(job.snapshot()["events"][0]["actor"], CUSTOMER)
        self.assert_conserved(job)

    def test_failed_calls_leave_all_state_unchanged_and_time_cannot_rollback(self):
        job = assigned_job()
        before = job.snapshot()
        with self.assertRaises(ValueError):
            job.submit(WORKER, {}, DECISION)
        self.assertEqual(job.snapshot(), before)
        job.submit(WORKER, good_bundle(), BEFORE_DELIVERY)
        before = job.snapshot()
        with self.assertRaises(TransitionError):
            job.accept(CUSTOMER, DECISION)
        self.assertEqual(job.snapshot(), before)
        with self.assertRaises(ValueError):
            job.accept("", BEFORE_ACCEPTANCE)
        self.assertEqual(job.snapshot(), before)

    def test_conservation_over_transition_sequences(self):
        sequences = []
        job = make_job()
        job.assign(CUSTOMER, WORKER, DECISION)
        job.submit(WORKER, good_bundle(), BEFORE_DELIVERY)
        job.accept(CUSTOMER, BEFORE_ACCEPTANCE)
        sequences.append(job)
        job = disputed_job()
        job.resolve(RESOLVER, True, BEFORE_DISPUTE)
        sequences.append(job)
        job = disputed_job()
        job.resolve(RESOLVER, False, BEFORE_DISPUTE)
        sequences.append(job)
        job = assigned_job()
        job.timeout("anyone", DELIVERY)
        sequences.append(job)
        job = submitted_job()
        job.timeout("anyone", ACCEPTANCE)
        sequences.append(job)
        for job in sequences:
            with self.subTest(events=job.snapshot()["events"]):
                self.assert_conserved(job)


def disputed_job():
    job = submitted_job()
    job.dispute(CUSTOMER, BEFORE_ACCEPTANCE)
    return job


if __name__ == "__main__":
    unittest.main()
