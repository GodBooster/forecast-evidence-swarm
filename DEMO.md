# Demo: order → research → evidence checks → acceptance/payment → knowledge page

One scenario, followed end to end. Every command below was run on the reference machine
(Intel macOS, Python 3.14.7, Rust 1.99.1, Docker Desktop 29.9.2) on 2026-11-08; outputs
are quoted from those runs. All data is **synthetic**; all roles are **scripted**.

The focus case is job `synthetic-01`: *"Will the next synthetic registry event be YES?"*.
The analyst forecasts 75% YES from 15 YES in 20 synthetic observations; the event later
resolves NO. It is the case that shows why validity, correctness, payment and publication
must be separate: the delivery is valid, the forecast is wrong, the customer still pays,
and the public page keeps the original 75% forever.

## Path A — offline, any machine with Python 3.10+ (≈1 s)

```sh
python3 -m forecast_swarm.walkthrough
```

Expected output (abridged; hashes are deterministic and identical on every run):

```text
1. ORDER  A customer commissions a binary forecast with a source, cutoff, deadlines and budget.
   job=synthetic-01  question='Will the next synthetic registry event be YES?'
   cutoff=2026-11-01T12:00:00Z  delivery<2026-11-01T13:00:00Z  accept<2026-11-01T14:00:00Z  budget=100 synthetic credits

2. RESEARCH  Analyst, critic and verifier roles (scripted functions, labelled as such).
   analyst=75.00% YES  critic=CAUTION (3 findings)  verifier=VALID

3. EVIDENCE CHECKS  Deterministic gates decide delivery validity before anyone is paid.
   valid_wrong     VALID
   future_data     INVALID
   missing_data    INSUFFICIENT_DATA
   unresolved      VALID
   zero_successes  VALID
   Focus delivery is VALID but the outcome was NO: direction_correct=False, Brier=0.5625. ...
   delivery sha256=ba7aa4bf1e5ae00ac6a1a124f042c9dab37ab0bae903671ad640451066db816d

4. ACCEPTANCE / PAYMENT  receipts: SIMULATION (derived SIMULATION receipts)
   job synthetic-01: PAID for exactly this delivery hash; 0 transaction IDs recorded
   refunded deliveries kept private: 2; public paid claims: 2
   SIMULATION receipts are derived from the synthetic ledger; no NEAR transfer occurred.

5. KNOWLEDGE PAGE  Only a paid, VALID delivery with hash-bound consent becomes public.
   claim=claim-43c6dc2d27294da59fc829683b7979b7b4c02515c6fb16099c03c057a61f1df3
   v1 as_of=2026-11-01T12:00:00Z outcome=UNRESOLVED sha256=9e2f6d31b2f2072d…
   v2 as_of=2026-11-03T12:00:00Z outcome=FINAL sha256=eec7e91609795719…

All walkthrough checks passed.
```

What each step demonstrates, and where to look:

| Step | Do | See | Rule being shown |
| --- | --- | --- | --- |
| 1. Order | read step 1 or `artifacts/walkthrough/walkthrough.json` → `order` | question, source, cutoff and three deadlines, budget | the customer fixes the terms before research |
| 2. Research | open `artifacts/walkthrough/core/report.html`, first card | analyst 75%, critic findings, verifier VALID — each labelled *scripted* | roles are separate and their mode is disclosed |
| 3. Evidence checks | same page, scenarios 2 and 3 | evidence published one second after cutoff → INVALID; missing source → INSUFFICIENT_DATA; both refunded in the simulator | invalid work is never paid |
| 3b. Validity ≠ correctness | scenario 1 "Later forecast quality" | EVALUATED, incorrect direction, Brier 0.5625 | an honest wrong forecast is still a valid delivery |
| 4. Payment | `artifacts/walkthrough/knowledge/payment-provenance.json` | the receipt for hash `ba7aa4bf…816d` with `receipt_mode` | payment binds the exact delivered bytes |
| 5. Knowledge page | `artifacts/walkthrough/knowledge/encyclopedia/claim-43c6dc2d….html` and its `-v1.html` | v1 shows 75% YES, unresolved; v2 adds outcome NO with the same forecast; `previous_sha256` links them | history is append-only; the forecast is never rewritten |
| 5b. Privacy | `artifacts/walkthrough/knowledge/encyclopedia/index.json` | invalid and refunded deliveries are absent | publication needs VALID + PAID + hash-bound consent |

To view the HTML over local HTTP (some embedded browsers block `file://`):

```sh
python3 -m http.server 8873 --bind 127.0.0.1 --directory artifacts
```

Then open `http://127.0.0.1:8873/walkthrough/core/report.html` and
`http://127.0.0.1:8873/walkthrough/knowledge/encyclopedia/index.html`. Stop the server
before rebuilding (the exporter is single-writer, not an atomic deployment).

## Path B — replay receipts recorded from the local NEAR Sandbox (≈1 s)

```sh
python3 -m forecast_swarm.walkthrough --receipts docs/evidence/sandbox-2026-11-08/near-receipts.json --out artifacts/walkthrough-sandbox
```

Expected difference in step 4:

```text
4. ACCEPTANCE / PAYMENT  receipts: LOCAL_NEAR_SANDBOX (docs/evidence/sandbox-2026-11-08/near-receipts.json)
   job 0: PAID for exactly this delivery hash; 6 transaction IDs recorded
   refunded deliveries kept private: 1; public paid claims: 1
   LOCAL_NEAR_SANDBOX receipts come from an ephemeral local chain; not a public explorer record.
```

On chain, the customer of the `zero_successes` delivery never accepted, so the contract
refunded it at the acceptance deadline; therefore only one claim is public here (the
simulator in Path A accepts both). The transaction IDs include the rejected wrong-caller
and duplicate-acceptance calls. The receipt file is a copy of real runner output, but the
chain was ephemeral: the IDs cannot be looked up anywhere. The encyclopedia page still says
"Customer acceptance · simulation" because its history is built from the core report's
simulated ledger; chain payment provenance is kept separately in
`artifacts/walkthrough-sandbox/knowledge/payment-provenance.json`. See
[docs/evidence/sandbox-2026-11-08](docs/evidence/sandbox-2026-11-08/README.md).

## Path C — fresh run on a local NEAR Sandbox (Docker, ≈5–10 min)

Requires Docker running and the cached Rust 1.99.1 toolchain with the
`wasm32-unknown-unknown` target. On hosts with less than ~6 GiB for Docker, limit memory:

```sh
FORECAST_DOCKER_MEMORY=3500m bash sandbox/run.sh
```

The script regenerates the core report, builds the contract wasm, starts one container
(no wallet mounts, no published ports), and runs two integration tests, each in its own
process against its own local NEAR Sandbox node. The first run compiles dependencies for
several minutes; on 2026-11-08 the tests themselves took 113 s and 94 s. Expected output
(excerpt):

```text
test real_local_chain_escrow_and_transfer_recovery ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 113.15s
test real_local_chain_dispute_resolve_timeout_and_cancel ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 93.54s
Public paid receipts: 1
Local NEAR receipt: .../artifacts/near-sandbox-run.XXXXXX/near-receipts.json
Dispute/cancel diagnostics: .../artifacts/near-sandbox-run.XXXXXX/near-dispute-cancel-diagnostics.json
Integration report: .../artifacts/near-sandbox-run.XXXXXX/knowledge-demo/index.html
```

Then feed the fresh receipts to the walkthrough:

```sh
python3 -m forecast_swarm.walkthrough --receipts artifacts/near-sandbox-run.XXXXXX/near-receipts.json --out artifacts/walkthrough-fresh
```

What the chain tests assert (by balances and the contract's outstanding liability, not
status labels alone): exact payout after acceptance; wrong caller and duplicate rejected;
exact refund at the acceptance deadline; failed payout/refund receipts recovered by a
permissionless retry to the *same* beneficiary; dispute decided only by the named resolver,
in either direction, exactly once; silent resolver → refund after the dispute deadline;
customer-only cancel of an open job (liability 2 NEAR → 0; the customer's own balance
change is the reward minus its gas); an assigned job cannot be cancelled and refunds at
the delivery deadline. Details: [docs/SANDBOX.md](docs/SANDBOX.md).

If the first node start is slow on a small Docker VM, raise
`FORECAST_NEAR_RPC_TIMEOUT_SECS` (default 60).

## Other commands

```sh
python3 -m forecast_swarm                       # core report only → artifacts/demo/
python3 -m forecast_swarm.knowledge_demo --fixture-consent --out artifacts/knowledge-demo
python3 -m forecast_encyclopedia --core-demo --core-consent fixtures_encyclopedia/core_demo_consent.json --out artifacts/product-demo
cargo +1.99.1 test --manifest-path contracts/forecast_jobs/Cargo.toml --locked --offline
```

## What this demo does not show

No LLM inference, live data source, authenticated customer identity, testnet/mainnet
transaction, real funds, or evidence of forecasting skill. The consent grants in
`fixtures_encyclopedia/core_demo_consent.json` are synthetic fixtures.
