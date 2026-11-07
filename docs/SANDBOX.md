# Local NEAR Sandbox integration

**Harness status: written, not compiled or executed.** The repository contains a draft real-chain integration test in `sandbox/tests/near_sandbox.rs`. It is intended to deploy the `forecast_jobs` WASM to a fresh, local NEAR Sandbox, create ephemeral accounts, and check onchain job state and account balances. API compatibility and runtime assertions remain unverified. No Testnet or Mainnet is used.

## Run it

From the repository root:

```sh
bash sandbox/run.sh
```

The wrapper first regenerates the synthetic core report, builds `contracts/forecast_jobs` for `wasm32-unknown-unknown`, then starts one resource-limited Linux container from `rust:1.99-slim-bookworm`. The container sees this repository and a task-specific Cargo cache. It has no wallet/config mounts and exposes no ports. On first run it resolves `near-workspaces = 0.24.0` and writes `sandbox/Cargo.lock`; the test command uses `--locked`. The sandbox runtime is provided by NEAR's `near-sandbox` crate.

Each successful run publishes into its own unique directory under `artifacts/near-sandbox-run.*`:

- `near-receipts.json` has exactly the `forecast-near-receipts/v1` receipt fields expected by the knowledge demo.
- `near-diagnostics.json` records contract WASM hash, local network mode, assertions, transaction IDs from recovery scenarios, balance deltas and final escrowed liabilities.
- `knowledge-demo/` is generated from the two exported chain receipts and the explicit synthetic-fixture consent setting.

The receipt file exports two distinct core artifact hashes: one paid `valid_wrong` delivery and one `zero_successes` delivery refunded at the acceptance deadline. Transfer-failure recovery jobs stay in diagnostics so one artifact commitment is not listed as multiple customer receipts. Failed runs remove their temporary run directory; the wrapper does not delete or overwrite prior successful runs.

## Chain assertions

The test checks that the customer funds a fixed reward, assigns a worker, and the worker submits the hash from the generated core report. Customer acceptance transfers exactly the reward once. A stranger cannot accept, a second acceptance fails, and the job reaches `ACCEPTED` only after the transfer callback. The test separately submits a `zero_successes` delivery, advances sandbox block time to the acceptance boundary, and checks the customer receives the exact refund and the job reaches `REFUNDED`.

Two additional jobs exercise asynchronous failure recovery. The test deletes and recreates only ephemeral accounts on the local sandbox so the payout and refund transfer receipts fail. It checks `PAYOUT_READY` and `REFUND_READY`, then retries each fixed entitlement and verifies the exact balance increase. It also checks that outstanding reward liability reaches zero after each successful callback and at the end. These recovery cases appear in diagnostics, not the exported receipt list.

All deadlines come from the sandbox's current block timestamp. The harness advances blocks until the requested timestamp is reached, with a bounded loop. It does not sleep against wall-clock time.

## Current verification and limitation

No NEAR Sandbox integration test has been executed and no local-chain receipt has been generated in this workspace. The host has Docker Desktop and the official Rust image cached. The runner's first dependency-lock attempt was blocked before execution: automatic approval review reported an account usage limit, and the system instruction prohibited retrying or bypassing that review. The local Cargo cache does not contain `near-workspaces`, so an offline compile could not replace the actual sandbox run. The lockfile is intentionally absent until Cargo can resolve and write it; the BUMM lock was inspected only for the official near-workspaces runner version, and no BUMM test source was copied.

The integration demo must be described as **planned** until `bash sandbox/run.sh` completes and writes a successful run directory. Offline simulation or a generated receipt-shaped JSON is not a substitute.

## Upstream references

- [NEAR Workspaces for Rust](https://github.com/near/near-workspaces-rs) documents deploy, transact and local sandbox workflows.
- [NEAR Sandbox](https://github.com/near/near-sandbox) describes the local node runtime used by the harness.
