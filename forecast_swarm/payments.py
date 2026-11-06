"""Local synchronous escrow SIMULATION. No tokens, wallets or transfers."""

from copy import deepcopy

from .evidence import nonempty, timestamp, validate_bundle, validate_terms


class TransitionError(ValueError):
    """A rejected command; it must leave all state and balances unchanged."""


class JobSimulator:
    """Single fixed worker budget. Time is caller-supplied only in this simulation."""

    def __init__(self, terms, customer, resolver, now):
        validate_terms(terms)
        for actor in (customer, resolver):
            nonempty(actor, "actor")
        if customer == resolver:
            raise ValueError("Customer and resolver must differ")
        if timestamp(now) > timestamp(terms["decision_at"]):
            raise ValueError("Create the job no later than decision_at")
        self._terms = deepcopy(terms)
        self._customer, self._resolver, self._worker = customer, resolver, None
        self._state = "OPEN"
        self._escrow = terms["budget_credits"]
        self._paid = self._refunded = 0
        self._artifact = None
        self._last_time = now
        self._events = [{"action": "create", "actor": customer, "at": now, "state": "OPEN"}]

    def snapshot(self):
        # No live references: returned reports cannot mutate simulator state.
        return deepcopy({"mode": "SIMULATION", "unit": "synthetic_credits",
                         "state": self._state, "customer": self._customer,
                         "worker": self._worker, "resolver": self._resolver,
                         "budget": self._terms["budget_credits"], "escrow": self._escrow,
                         "paid_to_worker": self._paid, "refunded_to_customer": self._refunded,
                         "artifact_sha256": self._artifact, "events": self._events})

    def _check(self, actor, now, states, allowed=None, before=None, at_or_after=None):
        nonempty(actor, "actor")
        moment = timestamp(now)
        if moment < timestamp(self._last_time):
            raise TransitionError("Time cannot move backwards")
        if self._state not in states:
            raise TransitionError(f"Action not allowed in {self._state}")
        if allowed is not None and actor not in allowed:
            raise TransitionError("Actor is not authorized")
        if before is not None and moment >= timestamp(before):
            raise TransitionError("Deadline reached; action requires now < deadline")
        if at_or_after is not None and moment < timestamp(at_or_after):
            raise TransitionError("Too early; action requires now >= boundary")

    def _record(self, action, actor, now, state):
        self._state, self._last_time = state, now
        self._events.append({"action": action, "actor": actor, "at": now, "state": state})
        self._assert_accounting()

    def _assert_accounting(self):
        assert self._escrow + self._paid + self._refunded == self._terms["budget_credits"]
        assert min(self._escrow, self._paid, self._refunded) >= 0
        assert not (self._paid and self._refunded)
        assert (self._escrow == 0) == (self._state in ("ACCEPTED", "REFUNDED"))

    def _settle(self, pay_worker):
        if pay_worker:
            self._paid += self._escrow
        else:
            self._refunded += self._escrow
        self._escrow = 0

    def assign(self, actor, worker, now):
        self._check(actor, now, {"OPEN"}, {self._customer}, before=self._terms["delivery_deadline"])
        nonempty(worker, "worker")
        if worker in (self._customer, self._resolver):
            raise TransitionError("Worker must differ from customer and resolver")
        self._worker = worker
        self._record("assign", actor, now, "ASSIGNED")

    def cancel(self, actor, now):
        self._check(actor, now, {"OPEN"}, {self._customer}, before=self._terms["delivery_deadline"])
        self._settle(False)
        self._record("cancel", actor, now, "REFUNDED")

    def submit(self, actor, bundle, now):
        self._check(actor, now, {"ASSIGNED"}, {self._worker},
                    before=self._terms["delivery_deadline"], at_or_after=self._terms["decision_at"])
        validated = validate_bundle(bundle)
        content = validated["content"]
        if content["inputs"]["terms"] != self._terms:
            raise TransitionError("Delivery terms do not match this job")
        if content["delivery_validity"] != "VALID":
            raise TransitionError("Delivery failed acceptance policy: " + content["delivery_validity"])
        self._artifact = validated["sha256"]
        self._record("submit", actor, now, "SUBMITTED")

    def accept(self, actor, now):
        self._check(actor, now, {"SUBMITTED"}, {self._customer}, before=self._terms["acceptance_deadline"])
        self._settle(True)
        self._record("customer_accept", actor, now, "ACCEPTED")

    def dispute(self, actor, now):
        self._check(actor, now, {"SUBMITTED"}, {self._customer, self._worker},
                    before=self._terms["acceptance_deadline"])
        self._record("dispute", actor, now, "DISPUTED")

    def resolve(self, actor, pay_worker, now):
        self._check(actor, now, {"DISPUTED"}, {self._resolver}, before=self._terms["dispute_deadline"])
        if type(pay_worker) is not bool:
            raise TransitionError("Resolution must explicitly choose payment or refund")
        self._settle(pay_worker)
        self._record("resolve_pay" if pay_worker else "resolve_refund", actor, now,
                     "ACCEPTED" if pay_worker else "REFUNDED")

    def timeout(self, actor, now):
        deadlines = {"OPEN": "delivery_deadline", "ASSIGNED": "delivery_deadline",
                     "SUBMITTED": "acceptance_deadline", "DISPUTED": "dispute_deadline"}
        if self._state not in deadlines:
            raise TransitionError("Terminal jobs cannot be refunded again")
        self._check(actor, now, set(deadlines), at_or_after=self._terms[deadlines[self._state]])
        self._settle(False)
        self._record("timeout_refund", actor, now, "REFUNDED")
