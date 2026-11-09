# NEAR Contract

`contracts/forecast_jobs/` is a NEAR escrow contract (v2) for forecast delivery jobs. It does not read the Python demo output, validate source evidence, run analyst roles, or determine whether a forecast is true. Acceptance is a customer decision over the exact submitted artifact hash; a trusted named resolver can resolve a dispute. A hash binds bytes, not their truth.

## Status and build

The contract uses `near-sdk = 5.17.2`, pinned in `Cargo.toml`. It is verified by native unit tests, a local NEAR Sandbox harness ([SANDBOX.md](SANDBOX.md)) and a run on NEAR testnet.

- **Deployed on NEAR testnet** as `escrow.forecast-evidence-swarm.testnet` (deployed and initialized in one transaction; the on-chain code hash equals the SHA-256 of the wasm built from this source). See [TESTNET.md](TESTNET.md) and the recorded run in [evidence/testnet-2026-11-09/README.md](evidence/testnet-2026-11-09/README.md).
- **Not deployed on mainnet.** Testnet NEAR has no value, the network can be reset, and nothing here has been audited.

Install the toolchain once (`rustup toolchain install 1.99.1`,
`rustup target add wasm32-unknown-unknown --toolchain 1.99.1`), then:

```sh
cargo +1.99.1 test --manifest-path contracts/forecast_jobs/Cargo.toml --locked
cargo +1.99.1 build --manifest-path contracts/forecast_jobs/Cargo.toml --locked --target wasm32-unknown-unknown --release
```

The first run downloads the crates pinned in `Cargo.lock`; after that `--offline` may be
added (the sandbox wrapper builds the host wasm with `--offline` and therefore needs this
one-time fetch).

The wasm output is `contracts/forecast_jobs/target/wasm32-unknown-unknown/release/forecast_jobs.wasm`. These commands need no account, wallet, endpoint or transaction.

### Verified locally

- 14 native unit tests pass (`cargo +1.99.1 test`, no doc tests).
- Release wasm: 301,209 bytes, SHA-256 `cfb2e8649877b6d1c9424a46231c815c31f5487e4b0393633725a30a9f52a089`. This is the code hash deployed on testnet.
- `bash sandbox/run.sh` on 2026-11-09 (Docker runner, ephemeral local NEAR Sandbox): both integration tests passed against this wasm, `real_local_chain_escrow_and_transfer_recovery` and `real_local_chain_dispute_resolve_timeout_and_cancel`, 5 jobs each, final reward liability 0. They cover exact payout and refund balances, wrong-caller and duplicate rejection, failed payout/refund receipts recovered by retry, dispute and resolution both ways, cancel and timeouts, plus the v2 additions: order hash cross-check, NEP-297 events, storage-deposit accounting, on-chain publication consent, the NEP-330 view and measured callback gas. Details and file hashes: [SANDBOX.md](SANDBOX.md) and [evidence/sandbox-2026-11-09/README.md](evidence/sandbox-2026-11-09/README.md).
- `rustfmt`/`cargo-fmt` is not installed in the available toolchains, so formatting checks were not run.
- The first-generation contract (8 unit tests, 230,688-byte wasm, no order hash, ten-job cap) is superseded; its 2026-11-08 sandbox evidence directory was replaced by the 2026-11-09 one.

## Roles and funding

- **Customer** creates and funds a job, assigns one worker, accepts a submitted artifact, or disputes it. Only the customer can grant or revoke publication consent.
- **Worker** is assigned by the customer, submits a 64-character lowercase SHA-256 digest, or disputes a submission.
- **Resolver** is fixed at initialization and alone chooses pay or refund for a dispute. Customer, worker, and resolver must be distinct.
- Anyone may call `timeout` after the relevant deadline or `retry_transfer` for a previously decided failed transfer. Neither call changes the entitlement.

`new(resolver)` is payable and requires at least 1 NEAR as a fixed contract-level reserve. The reserve is not a reward and has no withdrawal method. Deployment and initialization must be one account-controlled batch so another account cannot initialize the contract first (the testnet deployment did this in a single transaction).

`create_job(order_sha256, decision_deadline_ms, delivery_deadline_ms, acceptance_deadline_ms, dispute_deadline_ms)` is payable. The attached deposit is **reward plus a fixed, non-refundable storage deposit of 0.01 NEAR** (`JOB_STORAGE_DEPOSIT`); the reward is the deposit minus 0.01 NEAR and must be positive. The reward is recorded as an escrow liability until a transfer callback confirms it left; the storage deposit is added to a separate counter and is never paid out. It stakes the job's permanent record: a unit test measures the worst-case record (64-character customer and worker account IDs, both hashes, all options set) at 390 bytes, which is 0.0039 NEAR at 10^19 yoctoNEAR per byte, so the 0.01 NEAR deposit has a 2.56x margin (the sandbox re-measures this on chain, including after consent is granted and revoked). Because every job pays for its own storage, there is **no cap on the number of jobs**. After every call that adds a liability or storage the contract asserts that its balance covers escrowed rewards plus the 1 NEAR reserve plus all storage deposits, and that the account's storage stake never draws on escrowed rewards.

## Methods

| Method | Authorization and behavior |
|---|---|
| `new(resolver)` | One-time payable initialization; records the resolver and the reserve (at least 1 NEAR). |
| `create_job(order_sha256, decision_deadline_ms, delivery_deadline_ms, acceptance_deadline_ms, dispute_deadline_ms)` | Payable; deposit = reward + 0.01 NEAR storage deposit. `order_sha256` must be 64 lowercase hex characters. Creates `OPEN`; creation must occur no later than the decision deadline; the caller must differ from the resolver; deadlines must strictly increase. Returns the job id. |
| `assign(job_id, worker)` | Customer only, while `OPEN`, before delivery deadline; worker must differ from customer and resolver. |
| `cancel(job_id)` | Customer only, while `OPEN` and before delivery; begins asynchronous refund. |
| `submit(job_id, artifact_sha256)` | Assigned worker only, at/after decision deadline and strictly before delivery. The contract validates digest syntax only. |
| `accept(job_id, artifact_sha256)` | Customer only, while `SUBMITTED`, before acceptance deadline, and only for the submitted digest; begins payout to worker. |
| `dispute(job_id)` | Customer or assigned worker only, while `SUBMITTED` and before acceptance deadline. |
| `resolve(job_id, pay_worker)` | Named resolver only, while `DISPUTED` and before dispute deadline; begins the chosen transfer. |
| `timeout(job_id)` | Permissionless refund trigger: `OPEN`/`ASSIGNED` at or after delivery; `SUBMITTED` at or after acceptance; `DISPUTED` at or after dispute deadline. This is a call, not an automatic timer. |
| `retry_transfer(job_id)` | Permissionless retry only from `PAYOUT_READY` or `REFUND_READY`; retries the fixed beneficiary and cannot change pay into refund or vice versa. |
| `consent_publication(job_id, artifact_sha256)` | Customer only, only while the job is `ACCEPTED`, only for the accepted digest, once. Sets `publication_consent` to true. Consent never carries over to another digest. |
| `revoke_publication(job_id)` | Customer only, while consent is granted. Sets `publication_consent` to false; copies already published elsewhere cannot be recalled by the contract. |
| `on_transfer_complete(job_id, attempt_id)` | Private callback; accepts only the current pending attempt and records success or the recoverable ready state after a known transfer failure. |
| `get_job(id)` | View: `id`, `customer`, `worker`, `reward`, `order_sha256`, the four deadlines, `artifact_sha256`, `status`, `pending_attempt_id`, `publication_consent`. |
| `get_config()` | View: `resolver`, `storage_reserve`, `job_storage_deposit`, `storage_deposits`, `escrowed_rewards`, `callback_gas`, `job_count`, `event_standard`, `event_version`. |
| `job_count()`, `get_resolver()`, `get_storage_reserve()`, `get_storage_deposits()`, `get_escrowed_rewards()` | Read-only views; `get_escrowed_rewards` exposes unsettled reward liabilities, `get_storage_deposits` the kept per-job deposits. |
| `contract_source_metadata()` | NEP-330 view generated by `near-sdk`; the sandbox checks that it responds and that its link is this repository. |

The first version's view of the storage reserved for jobs no longer exists: its per-job allocation and job ceiling were replaced by the per-job storage deposit.

All time checks use `env::block_timestamp_ms()`; callers cannot submit a timestamp as proof. Action boundaries do not overlap: customer actions must be strictly before their deadline, while timeout is legal at or after it. Thus acceptance can win only before the acceptance boundary; timeout wins at the boundary.

## Events

Every state change logs a [NEP-297](https://nomicon.io/Standards/EventsFormat) event. The log line is `EVENT_JSON:` followed by

```json
{"standard":"forecast_jobs","version":"1.0.0","event":"job_created","data":[{"job_id":"0", "...":"..."}]}
```

`data` has exactly one object. All numbers (job and attempt IDs, yoctoNEAR amounts, millisecond deadlines) are strings; `job_id` is a decimal string.

| Event | Emitted by | Data fields besides `job_id` |
|---|---|---|
| `job_created` | `create_job` | `customer`, `reward`, `storage_deposit`, `order_sha256`, the four `*_deadline_ms` |
| `job_assigned` | `assign` | `customer`, `worker` |
| `artifact_submitted` | `submit` | `worker`, `artifact_sha256`, `order_sha256` |
| `job_accepted` | `accept` | `customer`, `worker`, `artifact_sha256`, `reward` |
| `job_disputed` | `dispute` | `by`, `artifact_sha256` |
| `dispute_resolved` | `resolve` | `resolver`, `pay_worker` (boolean) |
| `job_timeout` | `timeout` | `by`, `previous_status` |
| `job_cancelled` | `cancel` | `customer` |
| `transfer_retried` | `retry_transfer` | `by`, `kind` (`payout` or `refund`) |
| `transfer_settled` | `on_transfer_complete`, transfer succeeded | `attempt_id`, `kind`, `recipient`, `amount`, `status` |
| `transfer_failed` | `on_transfer_complete`, transfer failed | same as `transfer_settled` |
| `publication_consent_granted` | `consent_publication` | `customer`, `artifact_sha256` |
| `publication_consent_revoked` | `revoke_publication` | `customer`, `artifact_sha256` |

The decision events (`job_accepted`, `dispute_resolved`, `job_timeout`, `job_cancelled`, `transfer_retried`) are logged in the same transaction as the transfer they start; `transfer_settled` or `transfer_failed` is logged later in the callback receipt. Events are log lines, not state: read state through the views.

## Order binding

A job is bound to the customer's order, not just to a delivery. `order_sha256` is the SHA-256 of `"forecast-evidence-swarm/v1:terms
"` followed by the project's canonical JSON of the order `terms` (sorted keys, compact separators, integers only; see [SCHEMA.md](SCHEMA.md)). It is `order_commitment(terms)` in `forecast_swarm/evidence.py`. The prefix is always the v1 one, so a scripted and an LLM delivery of the same order share one order hash.

Every delivery bundle contains its own terms (`content.inputs.terms`), so anyone holding the bundle can recompute the order hash from the delivered bytes and compare it with `get_job(id).order_sha256`. The four on-chain deadlines are the terms' `decision_at`, `delivery_deadline`, `acceptance_deadline` and `dispute_deadline` converted to epoch milliseconds (UTC, whole seconds times 1000); `resolution_at` is not on chain. The sandbox tests recompute the order hash independently in Rust from the core report and require the contract to return the same value. The contract itself only checks that the order hash is 64-character hex: it does not know what the terms say.

## Customer verification before `accept`

`submit` validates digest syntax only, and `accept` pays the worker for whatever digest the
customer names. The contract never sees the delivered bytes, so the customer performs the
validity check off chain, immediately before accepting. In chain mode the tool reads the job itself:

```sh
python3 -m forecast_swarm.verify --bundle <bundle.json> --near-contract <escrow> --job-id <n>
```

For testnet, `<escrow>` is `escrow.forecast-evidence-swarm.testnet`; `--bundle` also accepts a core report JSON or a directory holding `report.json`. The command makes a read-only RPC view call to `get_job` and requires all of:

1. the job already has a submitted `artifact_sha256`, and the replayed bundle's recomputed SHA-256 equals it (the replay is `validate_bundle`: role outputs, evidence gate, commitment);
2. the bundle's delivery validity is `VALID`;
3. `order_commitment` of the bundle's own terms equals the on-chain `order_sha256` (`order vs chain: MATCH`);
4. the four on-chain deadlines equal the terms' deadlines (`deadlines vs chain: MATCH`).

It prints the chain context (`chain: …` with the block height, `chain status: …`), the replay lines, then `result: SAFE TO ACCEPT (bytes match the committed hash and the order; truth is not proven)` and exits 0, or prints `result: DO NOT ACCEPT` and exits 1. Only then call `accept(job_id, artifact_sha256)` with that exact digest, or `dispute(job_id)`.

**This exact check is the resolver's decision rule for a dispute:** the resolver pays the worker when it passes and refunds the customer when it does not (`forecast_swarm.chain resolver-check`). The contract does not enforce that rule; the resolver remains a trusted party. The check trusts the answer of one RPC node (no light-client or state proof), and a pass proves byte agreement with the committed artifact and order, not that the forecast is true. A tampered bundle, a non-VALID delivery, a different order or a digest mismatch all end in `DO NOT ACCEPT`.

For a hash alone, without chain access, `--expect-sha256 <artifact_sha256>` (and optionally `--expect-order-sha256`) performs the same replay against values you supply.

The Python simulator ([PAYMENT_STATE_MACHINE.md](PAYMENT_STATE_MACHINE.md)) performs the replay inside
`submit`; the contract deliberately does not, which keeps it independent of the Python
roles and of any evidence format.

## State and payment recovery

```text
OPEN ─assign→ ASSIGNED ─submit→ SUBMITTED ─accept→ PAYOUT_PENDING ─success→ ACCEPTED
  │                 │                ├─dispute→ DISPUTED ─resolve(pay)→ PAYOUT_PENDING
  ├─cancel→ REFUND_PENDING           │                         └resolve(refund)→ REFUND_PENDING
  └─timeout→ REFUND_PENDING          └─timeout→ REFUND_PENDING
ASSIGNED ─timeout→ REFUND_PENDING
PAYOUT_PENDING ─known failure→ PAYOUT_READY ─retry_transfer→ PAYOUT_PENDING
REFUND_PENDING ─known failure→ REFUND_READY ─retry_transfer→ REFUND_PENDING
REFUND_PENDING ─success→ REFUNDED
```

The reward remains a liability until a transfer callback confirms success. A known failed payout preserves the worker's entitlement; a known failed refund preserves the customer's. Only the callback for the current attempt can settle a transfer, and duplicate or stale callbacks are rejected. A timeout cannot reverse an accepted payout decision after it enters `PAYOUT_PENDING` or `PAYOUT_READY`.

This design cannot safely recover if the callback itself never executes or runs out of gas: the transfer outcome may then be unknown, so the contract deliberately does not allow another transfer from a pending state. Such a job would remain `PAYOUT_PENDING` or `REFUND_PENDING`. The static callback allowance is 10 TGas and the measured burn is about 1.7 TGas (see "Callback gas" below), but a callback that never runs has not been tested; this contract does not claim recovery from it.

The resolver is a trusted single party; this is not trustless arbitration. The worker's hash is not an on-chain evidence proof. Forecast correctness and eventual outcome do not trigger payment. The customer explicitly accepts an artifact, or the resolver chooses an entitlement after dispute. If the customer neither accepts nor disputes, the job is refunded to the customer at the acceptance deadline (the same rule as expiry in ERC-8183); this is a deliberate customer-protective policy and a nonpayment risk for the worker, who can `dispute` before that deadline.

## Callback gas

`on_transfer_complete` runs with a static allowance of 10 TGas. In the 2026-11-09 sandbox run the callback receipts burnt between 1.736 and 1.768 TGas (7 receipts in the first test, 5 in the second), so the allowance is 5.7 times the measured maximum; the harness fails if the allowance is below 2 times. The figures come from the local sandbox runtime. They are measurements of the callback that did run, not a bound on every possible state.

Before deployment on a shared network, deploy and initialize in one atomic batch. The harness itself uses separate `dev_deploy` and initialization calls, so it does not test protection against initialization takeover.

## Next verification

Native tests cover permissions, hash matching, deadline boundaries, duplicate state transitions, stale attempt rejection, failed payout/refund callbacks, fixed-entitlement retries, the order hash, the storage deposit and worst-case record size, consent, and the emitted events. The sandbox runs of 2026-11-09 exercised real receipts and balances for the paths listed above; the testnet run exercised acceptance with payout and on-chain consent, a timeout refund after customer silence, and a dispute decided by the resolver's rule.

Still untested:

- **Callback out-of-gas, or a callback that never executes.** Such a job would stay pending; no recovery is claimed and none was exercised.
- **Initialization takeover.** On testnet it is avoided by deploying and initializing in one transaction, but no attack on an uninitialized contract was tried.
- Anything adversarial against the resolver, a multi-party or bonded resolver, mainnet behavior, and a security audit.
