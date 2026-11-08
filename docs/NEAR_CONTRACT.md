# NEAR Contract Milestone

This crate is an independent, local NEAR escrow prototype for forecast delivery jobs. It does not read the Python demo output, validate source evidence, run analyst roles, or determine whether a forecast is true. Acceptance is a customer decision over the exact submitted artifact hash; a trusted named resolver can resolve a dispute. A hash binds bytes, not their truth.

## Status and build

The contract source is in `contracts/forecast_jobs/`, uses `near-sdk = 5.17.2`, and pins the SDK version in `Cargo.toml`. The prototype is intended for native unit tests and local NEAR sandbox scenarios. It has not been deployed to testnet or mainnet.

Use the cached Rust 1.99.1 toolchain and offline dependencies:

```sh
cargo +1.99.1 test --manifest-path contracts/forecast_jobs/Cargo.toml --offline
cargo +1.99.1 build --manifest-path contracts/forecast_jobs/Cargo.toml --target wasm32-unknown-unknown --release --offline
```

The wasm output is `contracts/forecast_jobs/target/wasm32-unknown-unknown/release/forecast_jobs.wasm`. The sandbox milestone is described separately in `docs/SANDBOX.md` when available. No account, wallet, endpoint, or transaction is part of these commands.

### Verified locally on 2026-11-07

- `cargo +1.99.1 test --manifest-path contracts/forecast_jobs/Cargo.toml --offline` — passed, 8 unit tests; no doc tests.
- `cargo +1.99.1 build --manifest-path contracts/forecast_jobs/Cargo.toml --target wasm32-unknown-unknown --release --offline` — passed.
- Built wasm size: 230,688 bytes. SHA-256: `1ac693ee9f3a44b230cc6cfc076d90f557209938adc122e10b4de6bfd0ea6c3c`.
- `bash sandbox/run.sh` — passed on 2026-11-08 (1 integration test, 95 s) against an ephemeral local NEAR Sandbox in the Docker runner: exact payout, timeout refund, wrong-caller and duplicate rejection, failed payout/refund receipts recovered by retry, liability 0. Details in `docs/SANDBOX.md`.
- Same day, run 2: a second integration test passed on chain for dispute → resolver pay, dispute → resolver refund, silent-resolver timeout, customer cancel and assigned-job delivery timeout, with exact balances and final liability 0.
- `rustfmt`/`cargo-fmt` is not installed in the available toolchains, so formatting checks were not run. No install or network access was attempted.

## Roles and funding

- **Customer** creates and funds a job, assigns one worker, accepts a submitted artifact, or disputes it.
- **Worker** is assigned by the customer, submits a 64-character lowercase SHA-256 digest, or disputes a submission.
- **Resolver** is fixed at initialization and alone chooses pay or refund for a dispute. Customer, worker, and resolver must be distinct.
- Anyone may call `timeout` after the relevant deadline or `retry_transfer` for a previously decided failed transfer. Neither call changes the entitlement.

`new(resolver)` is payable and requires at least 1 NEAR as a fixed contract-level storage reserve. Deployment and initialization must be included in the same account-controlled deployment batch so another account cannot initialize the contract first. `create_job(decision_deadline_ms, delivery_deadline_ms, acceptance_deadline_ms, dispute_deadline_ms)` is payable; its entire attached deposit is the positive reward, separately recorded as an escrow liability. The reserve is not a reward and has no withdrawal method. Each job consumes a conservative internal allocation of 0.1 NEAR from the 1 NEAR reserve ceiling, giving a maximum of ten jobs. This is a bounded accounting policy, not a protocol guarantee that every future storage price or job record will cost exactly that amount. The contract also checks aggregate reward liabilities plus the reserve against its account balance before adding a job.

## Methods

| Method | Authorization and behavior |
|---|---|
| `new(resolver)` | One-time payable initialization; records the resolver and reserve. |
| `create_job(decision_deadline_ms, delivery_deadline_ms, acceptance_deadline_ms, dispute_deadline_ms)` | Payable; attached deposit is reward. Creates `OPEN`; creation must occur no later than the decision deadline. Deadlines must strictly increase. |
| `assign(job_id, worker)` | Customer only, while `OPEN`, before delivery deadline; worker must differ from customer and resolver. |
| `cancel(job_id)` | Customer only, while `OPEN` and before delivery; begins asynchronous refund. |
| `submit(job_id, artifact_sha256)` | Assigned worker only, at/after decision deadline and strictly before delivery. The contract validates digest syntax only. |
| `accept(job_id, artifact_sha256)` | Customer only, while `SUBMITTED`, before acceptance deadline, and only for the submitted digest; begins payout to worker. |
| `dispute(job_id)` | Customer or assigned worker only, while `SUBMITTED` and before acceptance deadline. |
| `resolve(job_id, pay_worker)` | Named resolver only, while `DISPUTED` and before dispute deadline; begins the chosen transfer. |
| `timeout(job_id)` | Permissionless refund trigger: `OPEN`/`ASSIGNED` at or after delivery; `SUBMITTED` at or after acceptance; `DISPUTED` at or after dispute deadline. This is a call, not an automatic timer. |
| `retry_transfer(job_id)` | Permissionless retry only from `PAYOUT_READY` or `REFUND_READY`; retries the fixed beneficiary and cannot change pay into refund or vice versa. |
| `on_transfer_complete(job_id, attempt_id)` | Private callback; accepts only the current pending attempt and records success or the recoverable ready state after a known transfer failure. |
| `get_job(id)`, `job_count()`, `get_resolver()`, `get_storage_reserve()`, `get_storage_reserved_for_jobs()`, `get_escrowed_rewards()` | Read-only views; the latter exposes unsettled reward liabilities for sandbox conservation checks. |

All time checks use `env::block_timestamp_ms()`; callers cannot submit a timestamp as proof. Action boundaries do not overlap: customer actions must be strictly before their deadline, while timeout is legal at or after it. Thus acceptance can win only before the acceptance boundary; timeout wins at the boundary.

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

This design cannot safely recover if the callback itself never executes or runs out of gas: transfer outcome may be unknown, so the contract deliberately does not allow another transfer from a pending state. Such a job can remain `PAYOUT_PENDING` or `REFUND_PENDING`. Callback gas and execution need to be checked in sandbox tests; this prototype does not claim recovery from callback failure.

The resolver is a trusted single party; this is not trustless arbitration. The worker's hash is not an on-chain evidence proof. Forecast correctness and eventual outcome do not trigger payment. The customer explicitly accepts an artifact, or the resolver chooses an entitlement after dispute.

Before deployment on a shared network, deploy and initialize in one atomic batch.
The prototype's initializer can be called by the first caller after deployment; the
isolated sandbox harness uses separate `dev_deploy` and initialization calls and
does not test protection against initialization takeover. No public deployment is
authorized by this milestone.

## Next verification

Native tests exercise permissions, hash matching, deadline boundaries, duplicate state transitions, stale attempt rejection, failed payout/refund callbacks, and fixed-entitlement retries. The two 2026-11-08 sandbox runs exercised real receipts and balances for accept-payout, timeout refund, two real transfer failures with retries, wrong-caller and duplicate rejection, `dispute`/`resolve` in both directions, silent-resolver timeout, `cancel` and outstanding liabilities (see `docs/SANDBOX.md` and `docs/evidence/sandbox-2026-11-08/`). Still untested on chain: callback out-of-gas (unknown transfer outcome), initialization takeover and gas measurement (the 10 TGas callback allowance is a guess). The contract remains a local prototype.
