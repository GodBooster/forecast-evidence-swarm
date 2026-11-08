# Recorded local NEAR Sandbox output — 2026-11-08

**What these files are:** unmodified copies of the JSON written by
`FORECAST_DOCKER_MEMORY=3500m bash sandbox/run.sh` on 2026-11-08 (run directory
`artifacts/near-sandbox-run.h0OzqV/`, which is Git-ignored). They are committed so that
judges without Docker can replay the receipt path:

```sh
python3 -m forecast_swarm.walkthrough --receipts docs/evidence/sandbox-2026-11-08/near-receipts.json --out artifacts/walkthrough-sandbox
```

**What they are not:** the chain was a local, ephemeral NEAR Sandbox node inside a Docker
container. It no longer exists. The transaction IDs and `dev-…test.near` accounts cannot be
looked up on any explorer, and nothing here is a cryptographic proof of payment. The data
being paid for is synthetic. Treat these files as a runner's record of what its assertions
observed; to obtain fresh evidence, run `bash sandbox/run.sh` yourself (see `docs/SANDBOX.md`).

| File | SHA-256 | Contents |
| --- | --- | --- |
| `near-receipts.json` | `68b7aed82ee9158285bd3dbf547b561c3a9ade841ab0069e8634cd08bb80cafc` | `forecast-near-receipts/v1`, mode `LOCAL_NEAR_SANDBOX`: job 0 PAID (`valid_wrong`, 6 tx IDs incl. rejected wrong-caller and duplicate calls), job 1 REFUNDED at the acceptance deadline (`zero_successes`) |
| `near-diagnostics.json` | `aedb7f144ebbbf91a370640941265708503b23aad4a6277445a545ed4260dd16` | Test `real_local_chain_escrow_and_transfer_recovery`: 4 jobs, exact payout/refund deltas, failed payout/refund receipts and retries, final liability 0 |
| `near-dispute-cancel-diagnostics.json` | `73904d9ce57b5e12439e3b722e89969b1eceb39236cd4641d0acf7daea65a40f` | Test `real_local_chain_dispute_resolve_timeout_and_cancel`: 5 jobs, dispute/resolve both ways, silent-resolver timeout, cancel, assigned-job delivery timeout, final liability 0 |

Both tests used contract wasm SHA-256
`1ac693ee9f3a44b230cc6cfc076d90f557209938adc122e10b4de6bfd0ea6c3c` and a 2 NEAR reward per
job. Test summary lines from that run:

```text
test real_local_chain_escrow_and_transfer_recovery ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 113.15s
test real_local_chain_dispute_resolve_timeout_and_cancel ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 93.54s
```
