# Offline schema and commitments, v1

Implemented schema identifier: `forecast-evidence-swarm/v1`. Python standard library only.
Fixtures are explicitly synthetic. Unsupported versions, extra/missing fields, duplicate
evidence IDs, malformed timestamps and invalid types fail closed with `ValueError`.
Missing information is represented as JSON `null`, never as zero or an empty string.

## Input

`fixtures/synthetic_cases.json` is a list of cases. Each case has exactly:

| Field | Meaning |
| --- | --- |
| `schema_version` | Exact v1 identifier above |
| `scenario`, `title` | Nonempty synthetic scenario identifiers and labels |
| `synthetic` | Must be `true` in this milestone |
| `terms` | Immutable job identity, question, source, times and budget |
| `evidence` | List of uniquely identified synthetic observation batches |
| `outcome` | Nullable later resolution record; never available to the analyst |
| `evaluation_at` | Fixed retrospective evaluation cutoff |

Terms contain `job_id`, `question`, `source`, `decision_at`, `delivery_deadline`,
`resolution_at`, `acceptance_deadline`, `dispute_deadline`, `budget_credits`.
Identifiers and source are nonempty strings. Budget is a positive integer in
**synthetic credits**, with no relationship to token units or gas.
All timestamps are strictly `YYYY-MM-DDTHH:MM:SSZ`, UTC, whole seconds.
Required ordering: decision < delivery < resolution, and delivery < acceptance < dispute.

Each observation contains `id`, `source`, `observed_at`, `available_at`, `yes_count`,
`sample_count`. Every field except `id` can be null, yielding insufficient data.
Counts must be nonnegative integers (booleans and floats are rejected), with
yes_count <= sample_count. A zero sample is insufficient; zero successes in a
positive sample is valid. Both observation and publication must be <= decision_at;
publication cannot precede observation. Source must match the specified registry.
Any invalid observation invalidates the whole delivery; known invalid data takes
precedence over missing data. No silent filtering of inconvenient evidence occurs.

This prototype assumes batches represent distinct observations. Unique IDs do not
prove that batches are disjoint or authentic. The critic explicitly calls out
unproven comparability and independence; no production statistical claim follows.

## Scripted roles and statuses

Analyst pools known successes/sample counts, rounds the frequency half-up to integer
basis points (0–10000), or abstains if verification is not VALID. This intentionally
simple demonstration is not a calibrated forecasting model. Critic emits fixed
limitations, not independent reasoning. Verifier applies explicit deterministic rules.
Every role has `mode: scripted`.

The three dimensions remain separate:

| Dimension | Values | Effect |
| --- | --- | --- |
| `delivery.content.delivery_validity` | `VALID`, `INVALID`, `INSUFFICIENT_DATA` | Local submission policy; never a measure of accuracy |
| `evaluation.forecast_quality.status` | `EVALUATED`, `INSUFFICIENT_DATA` | Retrospective score only; never authorizes payment |
| `customer_acceptance.status` | `ACCEPTED`, `REFUNDED`, `AWAITING_CUSTOMER` in the demo | Explicit simulator actions and ledger state |

General simulator ledger states additionally include OPEN, ASSIGNED, SUBMITTED and
DISPUTED; see [payment specification](PAYMENT_STATE_MACHINE.md).

An outcome has `source`, `value` (0/1/null), `final` (boolean), `resolved_at`,
`available_at`. A score requires a valid forecast, matching source, known final
outcome, resolution >= resolution_at, and resolution <= availability <= evaluation_at.
Missing, provisional, mismatched or future outcomes are insufficient, not successes.
`direction_correct` uses probability >= 5000 as the YES direction; a tie goes to YES.
`brier_score_scaled_1e8` is `(probability_bps - outcome * 10000)^2`.
Divide by 100,000,000 to display the score. One outcome cannot establish calibration
or predictive skill. The quality section is a separate replay, not evidence that was
available at delivery time.

## Canonical JSON and hashing

Project canonical JSON v1 is explicitly **not RFC 8785**:

1. Allow only null, booleans, integers, Unicode strings, lists and string-keyed objects.
   No floats, NaN, infinity, custom objects or ambiguous timestamp representations.
2. Sort observation records by their unique `id` before building the delivery.
   Reordering observation batches therefore does not change the commitment.
3. Sort object keys using Python Unicode order; retain all other list order.
4. Serialize UTF-8 with `ensure_ascii=False`, compact separators `,` and `:`, and no
   whitespace or trailing newline. Do not normalize Unicode strings.
5. Hash `UTF8(schema_version + ':' + domain + '\n') || canonical_json_bytes` with SHA-256.
   Domains are `evidence` and `bundle`. Output is lowercase 64-character hex.

`evidence_sha256` covers the sorted observations. The full delivery commitment covers
`content`: schema version; delivery inputs (scenario, title, synthetic flag, terms,
evidence); evidence hash; three scripted role outputs; and delivery validity.
The enclosing `{content, sha256}` never hashes its own `sha256` field.
It excludes outcome, evaluation_at, quality score and payment history. Changing those
later records cannot retroactively change the forecast commitment. Changing job terms
or evidence does change it. There are no runtime timestamps, random IDs or system paths
in either generated file. A JSON report's pretty-printed bytes are not the canonical
bytes used for its embedded commitments.

`validate_bundle` replays the roles from committed inputs and compares the complete
canonical bundle. Merely recomputing a hash over forged role results is insufficient.
A new role algorithm or canonical format needs a new schema version.

These are unsigned local artifacts. A hash proves byte agreement, not truth,
authorship, source authenticity, publication time, or onchain timestamping. Future
NEAR submission can anchor a commitment; independent source authentication remains
a separate requirement. No signatures or onchain anchoring are implemented here.

## LLM-analyst deliveries (`forecast-evidence-swarm/llm-analyst/v1`)

`--roles llm` produces a separate delivery schema; scripted v1 deliveries and hashes are
unchanged. Inputs are the same v1 case fields. Content adds `inference_trace`
(`forecast-inference-trace/v1`), the analyst role has `mode: llm` with provider, model,
prompt version, cited evidence IDs, rationale, uncertainty interval and the output-gate
verdict; critic and verifier remain `mode: scripted`. Commitments use the same canonical
JSON rules with the domain prefix `forecast-evidence-swarm/llm-analyst/v1:` (`evidence`,
`bundle`). `validate_bundle` replays the gates against the recorded model text rather
than calling a model. Reports in this mode use mode `SYNTHETIC_SIMULATION_LLM_ANALYST`
and an unhashed `role_mode` wrapper. Full description: [AI_WORKER.md](AI_WORKER.md).

## Order commitment and on-chain deadlines

The escrow contract binds each job to the customer's order. The order commitment is
`order_commitment(terms)` in `forecast_swarm/evidence.py`: SHA-256 of
`UTF8("forecast-evidence-swarm/v1:terms\n") || canonical_json_bytes(terms)` with the same
canonical JSON rules as above and the domain `terms`. It always uses the v1 schema prefix,
whatever the delivery schema, so scripted and LLM deliveries of one order share one order hash.
`terms` is validated first (exact fields, ordering rules). Because every delivery bundle
contains `content.inputs.terms`, the order hash can be recomputed from the delivered bytes.
The contract stores it as `order_sha256` (64 lowercase hex characters) and does not interpret it.

The four on-chain deadlines are the terms' times as epoch milliseconds (UTC, whole seconds times 1000):

| Contract argument | Terms field |
| --- | --- |
| `decision_deadline_ms` | `decision_at` |
| `delivery_deadline_ms` | `delivery_deadline` |
| `acceptance_deadline_ms` | `acceptance_deadline` |
| `dispute_deadline_ms` | `dispute_deadline` |

`resolution_at` and `budget_credits` are not on chain; the reward is the NEAR deposit.
See [NEAR_CONTRACT.md](NEAR_CONTRACT.md) for how the check is used.

## NEAR receipts, chain snapshot and run log

These are recording formats for the chain layer; none of them is hashed into a delivery. All
fields are required and unknown fields are rejected by the readers.

**`forecast-near-receipts/v1`** (modes `SIMULATION`, `LOCAL_NEAR_SANDBOX`): top level
`schema_version`, `mode`, `jobs`; each job has `job_id`, `artifact_sha256`, `customer`,
`worker`, `status`, `transaction_ids`. See [KNOWLEDGE_DEMO.md](KNOWLEDGE_DEMO.md).

**`forecast-near-receipts/v2`** (mode `NEAR_TESTNET`, network `testnet`): top level
`schema_version`, `mode`, `network`, `contract_id`, `jobs`. Each job has the v1 fields plus
`chain_job_id` (integer id on the contract) and `order_sha256`. `status` is `PAID` or
`REFUNDED`; `transaction_ids` must be nonempty; `chain_job_id` and `job_id` are unique.

**`forecast-near-chain-snapshot/v1`**: `schema_version`, `network` (`testnet`), `contract_id`,
`rpc_url`, `captured_at` (UTC timestamp), `block_height`, `block_hash`, `config` (the
contract's `get_config` answer) and `jobs`, an object keyed by decimal job id whose values are
the `get_job` answers: `id`, `customer`, `worker`, `reward`, `order_sha256`, the four
`*_deadline_ms`, `artifact_sha256`, `status`, `pending_attempt_id`, `publication_consent`
(boolean). It records what one RPC node answered at one block; it is not a proof.

**`forecast-near-run-log/v1`**: `schema_version`, `network`, `contract_id`, `entries`. Each entry
of a sent call has `step`, `method`, `args`, `signer`, `key` (which near-cli key store signed),
`deposit_yocto`, `tx_hash`, `explorer`, `succeeded`, and optional context such as `job_id`,
`job_ref`, `previous_status`, `verified`. A `job_created` entry (`step`, `job_id`, `job_ref`,
`tx_hash`) maps the contract's job id to the order's `job_id`. Receipts v2 take their
transaction IDs from this log.

## Contract event envelope

Contract v2 logs NEP-297 events as `EVENT_JSON:` followed by
`{"standard":"forecast_jobs","version":"1.0.0","event":<name>,"data":[<one object>]}`.
Numbers (job and attempt ids, yoctoNEAR amounts, millisecond deadlines) are strings. The event
names and their fields are listed in [NEAR_CONTRACT.md](NEAR_CONTRACT.md#events).
