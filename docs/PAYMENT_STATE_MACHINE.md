# Job and budget state machine

**This document describes the Python simulator** (`forecast_swarm/payments.py`), which
serves as the readable specification of the job and budget state machine. It has no
wallets, token calls, gas, networking, persistent storage or concurrency; all balances
are integer synthetic credits. The NEAR contract that implements this machine on chain is
in `contracts/forecast_jobs/` and documented in [NEAR_CONTRACT.md](NEAR_CONTRACT.md).
One deliberate difference: the simulator replays `validate_bundle` and rejects a
non-VALID delivery at `submit`; the contract checks only digest syntax and leaves
validity to the customer's own check before `accept`.

## Terms, authority and conservation

A customer creates a job no later than its decision cutoff, earmarking one positive
fixed budget. The customer selects one worker and a distinct resolver. Customer,
worker and resolver identities must differ. They are string labels in this simulator,
not authenticated accounts. The three scripted analytical roles are work performed
by the worker; they hold no signing authority or individual balances.

`budget = escrow + paid_to_worker + refunded_to_customer` at every successful step.
Balances are nonnegative; payout and refund are mutually exclusive. There are no
partial payments, platform fees, top-ups, inferred costs or extra-budget spending.
Only terminal ACCEPTED/REFUNDED has zero escrow. The input terms and exported
snapshots are copied to avoid accidental mutation. Rejected commands do not alter
state, the last accepted time, history or balances.

All timestamps are UTC whole seconds. Calls must be monotonic in time (same-time
calls are allowed). Time is supplied by the test/demo caller; a contract must use
block time, never a user-supplied timestamp. Legal boundaries are deliberately
non-overlapping: action **before** deadline; timeout **at or after** deadline.

## Transitions

| From | Command / actor | Time and other conditions | To / budget effect |
| --- | --- | --- | --- |
| creation | create / customer | now <= decision; positive budget | OPEN; full escrow |
| OPEN | assign / customer | now < delivery; distinct worker | ASSIGNED; unchanged |
| OPEN | cancel / customer | now < delivery | REFUNDED; full refund |
| OPEN or ASSIGNED | timeout / anyone | now >= delivery | REFUNDED; full refund |
| ASSIGNED | submit / assigned worker | decision <= now < delivery; exact terms; canonical bundle replay; delivery VALID | SUBMITTED; commitment retained, funds held |
| SUBMITTED | accept / customer | now < acceptance | ACCEPTED; full worker payout |
| SUBMITTED | dispute / customer or worker | now < acceptance | DISPUTED; funds held |
| SUBMITTED | timeout / anyone | now >= acceptance | REFUNDED; full refund |
| DISPUTED | resolve(pay) / resolver | now < dispute deadline | ACCEPTED; full worker payout |
| DISPUTED | resolve(refund) / resolver | now < dispute deadline | REFUNDED; full refund |
| DISPUTED | timeout / anyone | now >= dispute deadline | REFUNDED; full refund |
| ACCEPTED or REFUNDED | any state-changing call | never legal | rejected; no money moved |

Only a valid bundle can enter SUBMITTED. INVALID or INSUFFICIENT_DATA submissions
leave ASSIGNED unchanged and can be replaced before delivery closes. A second
submission after success is rejected. A customer cannot cancel assigned or submitted
work; an unsatisfactory submitted delivery uses dispute, while silence eventually
allows timeout. No transition is triggered by later forecast correctness or an agent
vote. Normal payment is an explicit customer acceptance. Dispute resolution is a
separate explicit decision by the named trusted resolver; roles cannot self-approve.

Acceptance has a fixed deadline after delivery, so late valid work still gets the
configured review interval. A dispute can extend that interval only until the fixed
dispute deadline. Timeout requires a caller; the simulation does not run background
timers. Refund-on-silence is a deliberate customer-protective policy and creates a
worker nonpayment risk. A worker can dispute before acceptance closes; a resolver
can still fail to act, resulting in a refund. These tradeoffs are explicit terms,
not a claim of fair or trustless arbitration.

## Races and review policy

The simulator processes one command at a time, like the intended contract's atomic
state transitions. Accept before the boundary consumes escrow; later timeouts fail.
At the boundary acceptance is already illegal and timeout succeeds. If multiple
timeout/refund calls arrive, only the first changes state. Tests exercise both call
orders, repeated payouts, repeated refunds, permissions and exact boundaries.
This demonstrates the transition model, not real network concurrency safety.

The simulator replays evidence checks locally before submission. A real onchain
contract is **not assumed to validate source data or run Python roles**. Its minimum
policy should bind the submitted commitment to explicit customer acceptance, with
any reviewer adapter clearly named and trusted. Adapting BUMM's trusted security
reviewer does not make forecast truth or customer acceptance automatic.

## NEAR implementation requirements

These requirements guided the contract in `contracts/forecast_jobs/`. Its API, state
diagram, recovery limits and the local-sandbox evidence for each point are in
[NEAR_CONTRACT.md](NEAR_CONTRACT.md) and [SANDBOX.md](SANDBOX.md); callback out-of-gas
recovery and gas measurement remain open.

- Use predecessor identity, authenticated ownership and block timestamp. Reserve
  storage/gas independently of job rewards; specify units and storage deposits.
- Bind acceptance to job ID and the exact submitted artifact/revision hash. Maintain
  a bounded budget in contract state; a function-call key allowance only limits gas.
- Keep entitlement decisions separate from asynchronous cash transfer. Design pending
  payouts/refunds or pull claims with a unique attempt ID; mark amounts reserved before
  scheduling transfers so a concurrent action cannot release them twice.
- A private callback must validate the pending operation and promise result. Failed
  payout **and refund** transfers must restore a recoverable claim. Retried/stale
  callbacks cannot duplicate a payment. Specify callback failure and stuck-pending
  recovery without permitting a retry while transfer success is unknown.
- Initialize securely as part of deployment, bound input/storage growth and document
  resolver governance. No unattended balance can be permanently locked by an
  unspecified acceptance/dispute timeout.
- Sandbox tests must exercise actual successful/failed transfer receipts, permission
  failures, duplicate callbacks/claims, timeout races and conservation including
  outstanding liabilities and fees. Python simulation is not a replacement. (Two such
  tests ran on a local NEAR Sandbox on 2026-11-08; see SANDBOX.md.)

See [NEAR reuse assessment](NEAR_REUSE.md) for adjacent BUMM work and the product
boundary. No existing NEAR code or external dependencies were copied in this milestone.
