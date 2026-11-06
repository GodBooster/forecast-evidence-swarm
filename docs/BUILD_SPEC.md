# First implementation milestone

## Product

Commission a forecast with inspectable evidence. A customer specifies a binary question, a precise resolution source, a resolution time, delivery deadline, acceptance policy and job budget. Three roles produce analysis, criticism and verification. A final report exposes uncertainty and missing information.

Initial tracks: AI Swarms and Agent Economy. Scope is independent of BUMM's security product. A knowledge-page view can follow after the core flow works.

## Offline deliverable

Use Python standard library where practical. A single documented command must run without network access, credentials or LLM calls and produce a local readable HTML report plus machine-readable JSON. Scripted roles must be clearly labelled as scripted.

Include at least three deterministic synthetic examples:

1. Valid evidence, forecast and criticism lead to a deliverable ready for customer acceptance.
2. Evidence unavailable at the decision time is rejected with an explicit reason.
3. Missing source, unresolved outcome or insufficient evidence produces an insufficient-data status rather than a positive verdict.

Define a versioned schema and canonical serialization before hashing. Exclude nondeterministic execution timestamps from the stable commitment, or distinguish execution metadata from committed content. Repeating the demo must produce identical committed outputs.

Keep forecast quality, delivery validity and customer payment acceptance separate. A validly delivered forecast can be wrong. Never release payment merely because a forecast later happened to be right.

## Planned payment state machine

Specify owner/worker permissions, budget accounting and legal transitions before implementing the contract. Candidate states: OPEN, ASSIGNED, SUBMITTED, ACCEPTED, REFUNDED, DISPUTED. Cancellation, submission, acceptance and deadline boundaries must be unambiguous.

Do not automatically award money based on a vote of the same agents that produced the work. First version uses explicit customer acceptance. Define what happens to submitted but unaccepted work; do not leave funds permanently locked by an unspecified timeout. Demonstrate no double release or refund/release race. For the offline milestone use a clearly labelled simulator; NEAR contract and sandbox tests follow.

For the real contract, account for asynchronous transfer failure and idempotent recovery. Function-call key allowance limits gas; job spending limits belong in contract logic.

## Validation

Meaningful tests: future-data rejection, unavailable versus zero data, outcome finality, stable commitments, permission checks, duplicate submission/payment and deadline/refund races. Run the offline demo and inspect generated outputs. Report actual results and limitations.

## Next milestone

After completing the offline milestone and contract specification, implement a minimal NEAR contract with local sandbox tests. Private inference and Agent Market are optional adapters after the independent flow works. Intents dry quotes do not demonstrate settlement. No authenticated integrations or token spending without owner-provided access and authorization.

## Context outside the public repository

The local parent document `near-hackathon/FIT_AND_MVP_2026-11-06_UK.md` contains the full feasibility research. Read it locally as needed; do not import private reports wholesale. Submission deadline is 2026-11-14 23:59 UTC (2026-11-15 01:59 Kyiv). Scope estimates are not guarantees of delivery.
