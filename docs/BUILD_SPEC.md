# First implementation milestone

## Product

Commission a forecast with inspectable evidence. A customer specifies a binary question, a precise resolution source, a resolution time, delivery deadline, acceptance policy and job budget. Three roles produce analysis, criticism and verification. A final report exposes uncertainty and missing information.

A knowledge-page view (the encyclopedia) publishes only paid, valid, consented deliveries.

## Offline deliverable

Use Python standard library where practical. A single documented command must run without network access, credentials or LLM calls and produce a local readable HTML report plus machine-readable JSON. Scripted roles must be clearly labelled as scripted.

Include at least three deterministic synthetic examples:

1. Valid evidence, forecast and criticism lead to a deliverable ready for customer acceptance.
2. Evidence unavailable at the decision time is rejected with an explicit reason.
3. Missing source, unresolved outcome or insufficient evidence produces an insufficient-data status rather than a positive verdict.

Define a versioned schema and canonical serialization before hashing. Exclude nondeterministic execution timestamps from the stable commitment, or distinguish execution metadata from committed content. Repeating the demo must produce identical committed outputs.

Keep forecast quality, delivery validity and customer payment acceptance separate. A validly delivered forecast can be wrong. Never release payment merely because a forecast later happened to be right.

## Payment state machine

Specify customer/worker permissions, budget accounting and legal transitions for the contract (see `docs/PAYMENT_STATE_MACHINE.md`). States include OPEN, ASSIGNED, SUBMITTED, ACCEPTED, REFUNDED, DISPUTED. Cancellation, submission, acceptance and deadline boundaries must be unambiguous.

Do not automatically award money based on a vote of the same agents that produced the work. First version uses explicit customer acceptance. Define what happens to submitted but unaccepted work; do not leave funds permanently locked by an unspecified timeout. Demonstrate no double release or refund/release race. The offline flow uses a clearly labelled simulator; the NEAR contract is tested natively, on a local sandbox and on NEAR testnet (`docs/TESTNET.md`).

The contract accounts for asynchronous transfer failure and idempotent recovery. A job binds the order hash and four deadlines. Function-call key allowance limits gas; job spending limits belong in contract logic.

## Validation

Meaningful tests: future-data rejection, unavailable versus zero data, outcome finality, stable commitments, permission checks, duplicate submission/payment and deadline/refund races. Run the offline demo and inspect generated outputs. Report actual results and limitations.

## Scope

Private inference and agent-market integrations are optional adapters; the flow works without them. Intents dry quotes do not demonstrate settlement. Authenticated integrations and token spending are outside the repository's scope and are decisions for the operator who runs the commands. Estimates of scope are not guarantees of delivery.
