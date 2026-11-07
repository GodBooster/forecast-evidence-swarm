# Forecast Evidence Swarm

A NEAR hackathon prototype for commissioning forecasts with evidence, criticism and reproducible validation.

**Status: runnable offline product and compiled NEAR contract prototype.** Five synthetic scenarios, three explicitly scripted roles, deterministic evidence commitments, HTML/JSON reports, consent-gated knowledge pages and a local budget simulator. The contract passes native unit tests and builds to wasm; actual NEAR sandbox transfers remain unverified. Forecast quality and trading profitability have not been established.

A customer defines a question, resolution source, deadline and budget. Analyst, critic and verifier roles produce a forecast and evidence bundle. Deterministic checks evaluate data timing, completeness and acceptance rules. A planned NEAR contract records the job, budget and artifact commitment; the customer accepts delivery.

## Run the offline demo

From this repository directory, with Python 3.10+ (verified locally with Python 3.14.7):

```sh
python3 -m forecast_swarm
```

No installation, network, credentials, LLM calls or nonstandard packages are required.
Open `artifacts/demo/report.html` directly in a browser; its companion
`artifacts/demo/report.json` contains inputs, role outputs, hashes, quality and the
simulated job ledger. Both outputs are deterministic and ignored by Git.
Choose another directory with `python3 -m forecast_swarm --out artifacts/replay`.

```sh
python3 -m unittest discover -s tests -v
```

The examples make three independent statuses visible:

| Synthetic scenario | Delivery validity | Later forecast quality | Customer acceptance |
| --- | --- | --- | --- |
| Valid evidence, 75% YES, final outcome NO | VALID | EVALUATED, incorrect direction | Explicitly ACCEPTED |
| Published one second after cutoff | INVALID | INSUFFICIENT_DATA | Submission rejected, budget REFUNDED at timeout |
| Missing source and observations | INSUFFICIENT_DATA | INSUFFICIENT_DATA | Submission rejected, budget REFUNDED at timeout |
| Provisional/unknown outcome | VALID | INSUFFICIENT_DATA | AWAITING_CUSTOMER; budget held |
| Zero successes in 20 observations | VALID | EVALUATED, correct direction | Explicitly ACCEPTED |

Zero known successes are different from missing observations. Unresolved outcomes
cannot receive a positive quality verdict. A valid delivery can be wrong and still
be accepted for payment. The unresolved case intentionally shows an open review;
tests also exercise its acceptance timeout and dispute timeout refund paths.

## What is implemented

- Independent scripted analyst, critic and verifier functions, explicitly labelled
  in every report. This is a sequential deterministic pipeline, not autonomous agents.
- Strict versioned synthetic inputs, pre-decision publication checks, outcome finality
  checks and separate retrospective scores. Source strings are fixture labels, not
  authenticated external records.
- Canonical integer-only JSON with domain-separated SHA-256 evidence and delivery
  commitments. Later outcomes and payment history are excluded from the delivery hash.
  Repeating the demo produces identical files. A hash proves byte agreement, not truth.
- A synchronous escrow **SIMULATION** with explicit customer acceptance, named dispute
  resolver, finite timeout rules, permissions and full-budget payout/refund conservation.
  No real balances or transactions are involved.

See [schema and commitments](docs/SCHEMA.md), [payment state machine](docs/PAYMENT_STATE_MACHINE.md)
and the original [build specification](docs/BUILD_SPEC.md). Tests cover timing boundaries,
missing data, finality, tampering, deterministic replay, permissions and duplicate settlement.
The [validation record](docs/VALIDATION.md) lists 35 passing tests, replay hashes and
the completed desktop browser check through a local HTTP preview.

## NEAR integration

The consent-gated knowledge flow can already be run locally:

```sh
python3 -m forecast_swarm.knowledge_demo --fixture-consent --out artifacts/knowledge-demo
```

Open `artifacts/knowledge-demo/index.html`. Only valid deliveries with matching paid
receipts and explicit hash-bound consent are imported publicly. The default receipts
are labelled SIMULATION; refunds never grant publication. An optional strict local
sandbox receipt input is described in [knowledge integration](docs/KNOWLEDGE_DEMO.md).
Receipt JSON is a local runner assertion, not an authenticated payment proof.

The independent contract in `contracts/forecast_jobs/` implements bounded job
budgets, deadlines, artifact submission, customer acceptance, disputes and
asynchronous payout/refund states with fixed-entitlement retry after a known failed
transfer. Eight native Rust tests pass and a release wasm builds successfully:

```sh
cargo +1.99.1 test --manifest-path contracts/forecast_jobs/Cargo.toml --locked --offline
cargo +1.99.1 build --manifest-path contracts/forecast_jobs/Cargo.toml --locked --target wasm32-unknown-unknown --release --offline
```

These commands use the installed toolchain/target and cached dependencies. See
[contract specification and validation](docs/NEAR_CONTRACT.md). The bounded prototype
supports ten jobs and requires a separate initialization storage reserve; job rewards
do not fund arbitrary worker spending.

The [sandbox harness](docs/SANDBOX.md) is prepared but has **not been compiled or
executed**: dependency setup through Docker was blocked by an automatic approval
account usage limit. No actual sandbox payment, refund, receipt or onchain anchoring
is claimed. A callback that fails to execute can leave an unknown pending transfer;
the contract does not permit unsafe retries from that state. Real LLM workers,
inference budgets, live data adapters and marketplace integrations remain planned.

[NEAR reuse assessment](docs/NEAR_REUSE.md) describes the adjacent BUMM Guard
`swarm_jobs` / `review-job` implementation and potential mutual value. BUMM checks
contract-code work; this project checks forecast evidence. Shared escrow/testing
patterns are candidates for explicit reuse, not a claim that either product provides
the other's domain validation. No BUMM source code was copied into this milestone.

## Prior work and disclosure

See [prior work](docs/PRIOR_WORK.md). The baseline predates this repository; only new features and integration are presented as hackathon work. Related project: BUMM, an independently developed security project; its public link and exact overlap must be confirmed before submission.

## License

License selection is pending. A LICENSE file must be added before publication or submission.
