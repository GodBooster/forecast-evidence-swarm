# Offline forecast knowledge integration

Run the end-to-end synthetic core and encyclopedia flow from the repository root:

```sh
python3 -m forecast_swarm.knowledge_demo --out artifacts/knowledge-demo --fixture-consent
```

The command runs the actual `forecast_swarm.demo.run_demo()` generator, creates a
simulated paid acceptance and an expired refund, replays the core bundles through
the read-only encyclopedia adapter, and writes a deterministic local export:

- `artifacts/knowledge-demo/index.html` links the encyclopedia and receipt JSON.
- `artifacts/knowledge-demo/encyclopedia/` contains the adapter's pages and
  machine-readable version history.
- `artifacts/knowledge-demo/payment-provenance.json` contains only matching paid
  receipts for claims with explicit consent. Refunded claims are not published.

Without `--fixture-consent` or `--consent path/to/grants.json`, imported core
claims stay private. The fixture grants are explicitly synthetic, keyed by the
exact delivery SHA-256, and do not authorize other jobs. A changed delivery hash
does not inherit consent. The already-public synthetic encyclopedia examples
remain in its export.

To import a saved core report and receipt document:

```sh
python3 -m forecast_swarm --out artifacts/core-demo
python3 -m forecast_swarm.knowledge_demo \
  --core-report artifacts/core-demo/report.json \
  --receipts path/to/receipts.json \
  --consent path/to/grants.json \
  --out artifacts/knowledge-demo
```

The receipt input is strict JSON with this v1 shape:

```json
{
  "schema_version": "forecast-near-receipts/v1",
  "mode": "LOCAL_NEAR_SANDBOX",
  "jobs": [
    {
      "job_id": "sandbox-job-123",
      "artifact_sha256": "<64 lowercase hex digits>",
      "customer": "customer.sandbox",
      "worker": "worker.sandbox",
      "status": "PAID",
      "transaction_ids": ["<sandbox transaction hash>"]
    }
  ]
}
```

In v1, `mode` is either `LOCAL_NEAR_SANDBOX` or `SIMULATION`; status is `PAID` or
`REFUNDED`. Sandbox receipts require at least one transaction ID. `artifact_sha256`
must match exactly one delivery in the supplied core report. The receipt `job_id`
is retained as provenance and is not assumed to equal the synthetic core job ID.
Unknown fields, duplicate receipt job IDs or artifact hashes, malformed digests,
and unmatched hashes are rejected. A paid receipt cannot publish an invalid or
insufficient delivery. Publication still requires a separate grant keyed by that
delivery hash. A refund never grants publication.

The payment provenance JSON is a **local runner assertion**, not a signature or
cryptographic verification of payment, transaction finality, or customer and
worker identities. The file preserves the receipt fields and binds each published receipt
to the exact core artifact hash, encyclopedia claim ID, and version-chain tip. The
adapter independently replays the core report and retains the core delivery hash
inside the historical forecast method. On the exported HTML page, the "Customer
acceptance" card shows the replayed simulator state under the label `simulation` by
default; for a claim whose paid receipt has mode `LOCAL_NEAR_SANDBOX` it is labelled
`local NEAR Sandbox receipt` and shows the receipt summary instead (status, receipt job
ID, transaction count). The stored claim JSON, version hashes and history are not
changed by this; the receipt fields live in `payment-provenance.json`. Neither the receipt nor its hash changes
the core report, forecast commitment, or append-only history. Keep the original
core report and the receipt input as local audit material.

This flow is offline and deterministic by default. Roles and credits are
simulated; receipt identity and truth are not authenticated. It does not use a
market, live LLM, wallet, mainnet, or external publication service. It makes no
claim of predictive skill or profitability. The first-generation adapter supports
core v1 report wrappers whose acceptance ledger is replayed from the simulator;
future asynchronous NEAR outputs require their own versioned, verified report
contract before they can replace that wrapper.

## NEAR testnet receipts (v2) and the chain snapshot

Receipts of a run on NEAR testnet use `forecast-near-receipts/v2`, mode `NEAR_TESTNET`
(field lists in [SCHEMA.md](SCHEMA.md)). In this mode the receipt file is **not trusted on its
own**: the command also needs a recorded chain snapshot, `forecast-near-chain-snapshot/v1`,
which holds the contract's `get_config` and `get_job` answers for the jobs concerned together
with the block height, block hash and RPC endpoint they were read at. The `chain` subcommand
`snapshot` of `forecast_swarm.chain` writes it (see [TESTNET.md](TESTNET.md)).

```sh
python3 -m forecast_swarm.knowledge_demo \
  --core-report docs/evidence/testnet-2026-11-09/core-report.json \
  --receipts docs/evidence/testnet-2026-11-09/near-receipts.json \
  --chain-snapshot docs/evidence/testnet-2026-11-09/chain-snapshot.json \
  --out artifacts/testnet-knowledge
```

This runs offline: it reads only the three recorded files. For every receipt the demo requires
the snapshot's job to agree with it: the customer, the worker and the order hash must match, a
`REFUNDED` receipt needs a `REFUNDED` job, and a `PAID` receipt needs a job that is `ACCEPTED`
with the same artifact hash, and the delivery's own terms must hash to the on-chain
`order_sha256` and produce the on-chain deadlines (the same checks as chain-mode `verify`). A
mismatch aborts the export.

**Publication consent comes from the contract in this mode.** A claim is published only if its
paid job's `publication_consent` flag is true in the snapshot, i.e. the customer called
`consent_publication` on chain for that exact artifact hash. A local consent file (`--consent`,
`--fixture-consent`) is rejected with `NEAR_TESTNET` receipts, and a snapshot is rejected with
v1 receipts. Refunded jobs never publish. The provenance sidecar records the snapshot's block
height, block hash and capture time, and the exported page is labelled `NEAR testnet receipt`.
The check is only as strong as the snapshot: it was read through one RPC node, with no
light-client or state proof, and a digest still binds bytes, not their truth. v1 receipts
(`SIMULATION`, `LOCAL_NEAR_SANDBOX`) behave exactly as described above.

## Verification

Run all standard-library tests with:

```sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s tests_encyclopedia -v
```

On 2026-11-07, `python3 -m unittest discover -s tests -v` passed **41 tests** (154 today; see `VALIDATION.md`) and
`python3 -m unittest discover -s tests_encyclopedia -v` passed **30 tests**. Both
the in-memory core report and a report generated by `python3 -m forecast_swarm`
were integrated successfully with explicit synthetic grants. The fixture-consent
command produced 28 encyclopedia HTML/JSON files and two consented `SIMULATION`
payment entries; refunded jobs were absent from public records and provenance.
This did not exercise a NEAR Sandbox deployment or establish a payment proof.
On 2026-11-08 `sandbox/run.sh` fed real `LOCAL_NEAR_SANDBOX` receipts (two jobs, one
`PAID`, one `REFUNDED`) through this command: the paid `valid_wrong` delivery was
published with its local transaction IDs in `payment-provenance.json`, the refunded
`zero_successes` delivery stayed private. See `docs/SANDBOX.md`. Those IDs come from an
ephemeral local chain and remain runner evidence, not a cryptographic payment proof.

On 2026-11-09 `python3 -m unittest discover -s tests -q` reported `Ran 154 tests ... OK` and the
encyclopedia suite `Ran 30 tests ... OK`; see [VALIDATION.md](VALIDATION.md).

`tests/test_knowledge_demo.py` covers private-by-default imports, hash-matched
consent, refund exclusion, invalid and mismatched receipts, local sandbox
transaction ID requirements, and byte-identical exports. The core suite also
covers evidence and escrow boundaries. The encyclopedia adapter and history
behavior are covered by its independent suite.
