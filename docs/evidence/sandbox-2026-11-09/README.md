# Recorded local NEAR Sandbox output — 2026-11-09

**What these files are:** unmodified copies of the JSON written by
`FORECAST_DOCKER_MEMORY=3500m bash sandbox/run.sh` on 2026-11-09 (UTC) against contract v2
(order hash, per-job storage deposit, NEP-297 events, on-chain publication consent). The
run directory under `artifacts/` is Git-ignored. They are committed so that judges without
Docker can replay the receipt path:

```sh
python3 -m forecast_swarm.walkthrough --receipts docs/evidence/sandbox-2026-11-09/near-receipts.json --out artifacts/walkthrough-sandbox
```

**What they are not:** the chain was a local, ephemeral NEAR Sandbox node inside a Docker
container. It no longer exists. The transaction IDs and `dev-…test.near` accounts cannot be
looked up on any explorer, and nothing here is a cryptographic proof of payment. The data
being paid for is synthetic. Treat these files as a runner's record of what its assertions
observed; to obtain fresh evidence, run `bash sandbox/run.sh` yourself (see `docs/SANDBOX.md`).
For transactions that can be looked up, see the testnet run under `docs/evidence/`.

| File | SHA-256 | Contents |
| --- | --- | --- |
| `near-receipts.json` | `9a2472854ca76282667bf2b72d826d3a9411bf1267976d1f86eadd04a8e773cb` | `forecast-near-receipts/v1`, mode `LOCAL_NEAR_SANDBOX`: job 0 PAID (10 tx IDs incl. rejected calls), job 1 REFUNDED at the acceptance deadline (4 tx IDs) |
| `near-diagnostics.json` | `7c8f4cb172103666eb2b429e7626db470df825ef04742330aa06f053f3ae344b` | Test `real_local_chain_escrow_and_transfer_recovery`: 5 jobs, order hash stored and cross-checked, exact payout/refund deltas, failed payout/refund receipts and retries, events, consent, NEP-330 metadata view, final reward liability 0 |
| `near-dispute-cancel-diagnostics.json` | `d48965546df62c610551f14bfaa613783f8abd450900ba53137a9df22bd341ee` | Test `real_local_chain_dispute_resolve_timeout_and_cancel`: 5 jobs, dispute/resolve both ways, silent-resolver timeout, cancel, assigned-job delivery timeout, final reward liability 0 |

Both tests used contract wasm SHA-256
`cfb2e8649877b6d1c9424a46231c815c31f5487e4b0393633725a30a9f52a089` (301,209 bytes) and a 2 NEAR reward per job plus the 0.01 NEAR
per-job storage deposit.

**Callback gas, measured.** Across 7 + 5 `on_transfer_complete` receipts the
gas burnt was between 1.736 and 1.768 TGas; the contract's static
allowance is 10 TGas (5.7x the measured maximum; the harness
asserts at least 2x). These figures are from the local sandbox runtime.

Test summary lines from that run:

```text
test real_local_chain_escrow_and_transfer_recovery ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 104.80s
test real_local_chain_dispute_resolve_timeout_and_cancel ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 97.01s
```
