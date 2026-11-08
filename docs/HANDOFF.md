# Forecast Evidence Swarm: engineering handoff

Prepared for Claude Code on **2026-11-08**. This is a continuation handoff, not a
new product specification. Code baseline: `main` at `52fa1ef`; the handoff itself
is committed afterward. No sandbox run or live inference was performed for this handoff.

## Product and owner decisions

Forecast Evidence Swarm commissions binary forecasts with inspectable evidence.
A customer defines a question, source, cutoff/deadlines and budget. Analyst, critic
and verifier produce an artifact. The customer accepts the exact artifact. Permitted
research becomes an encyclopedia page with preserved historical versions.

The owner explicitly wants **two independent projects**:

1. **Forecast Evidence Swarm** — forecasting / prediction-market research, based on
   ideas from private InvariFi research. Its encyclopedia is a module of this product,
   in this repository, for one planned submission.
2. **BUMM Guard** — security/deployment review of NEAR contract-code work. Separate
   repository, users, validation domain, demo and planned submission.

Reuse architectural lessons with attribution and license review; no BUMM source was
copied into this implementation. InvariFi's private experiments are prior work, not
proof of forecasting skill or profitability. No real betting market is implemented.
Initial planned tracks were AI Swarms and Agent Economy; confirm official current
track names and eligibility before submission.

## Current implementation and verification

| Component | Implemented | Actual verification |
| --- | --- | --- |
| `forecast_swarm/` | Five synthetic scenarios, three labelled scripted roles, strict evidence checks, deterministic commitments and HTML/JSON | 41 Python tests pass, including six knowledge-flow tests |
| `forecast_swarm/payments.py` | Synchronous budget/state-machine SIMULATION | Permissions, deadline boundaries, duplicate settlement, conservation |
| `forecast_encyclopedia/` | Consent-gated pages, append-only history, core adapter, one-command product demo | 30 Python tests pass |
| `forecast_swarm/knowledge_demo.py` | Paid-receipt/hash/consent export gate, separate payment provenance | Two consented SIMULATION entries exported; refunded imports excluded |
| `contracts/forecast_jobs/` | Independent NEAR escrow with async payout/refund and immutable entitlement on retry | Eight native Rust tests pass; release wasm built |
| `sandbox/` | Local-chain harness, runner image and Docker wrapper | Executed 2026-11-08: 2 integration tests (escrow/recovery; dispute/resolve/timeout/cancel) passed on ephemeral NEAR Sandbox nodes (see `docs/SANDBOX.md`) |
| `forecast_swarm/walkthrough.py` | One-command end-to-end demo with self-checks | 3 tests; documented in `DEMO.md`; submission draft in `docs/SUBMISSION_DRAFT.md` |
| UI | Standalone generated HTML | Desktop HTTP preview checked in embedded browser; mobile visual QA pending |
| LLM agents / live sources | Planned | No inference, authenticated source or model API exercised |

Fresh handoff check on 2026-11-08: **41 + 30 Python tests and 8 native Rust tests
passed**. Python 3.14.7, Rust 1.99.1. The previously built wasm is still present,
230,688 bytes, SHA-256:
`1ac693ee9f3a44b230cc6cfc076d90f557209938adc122e10b4de6bfd0ea6c3c`.
Its release build was verified on November 7; the handoff rechecked its bytes/hash.
Rustfmt was unavailable in the previous environment.

Update 2026-11-08 (Claude Code): the sandbox harness was compiled and run; local-chain
payout, timeout refund and failed-transfer recovery receipts exist under
`artifacts/near-sandbox-run.*`. No testnet/mainnet deployment or authenticated
publication consent has been established. Local JSON with a sandbox
mode label is a runner assertion, not a cryptographic payment proof.

## Read in this order

1. `AGENTS.md` and this file — scope, decisions and current truth.
2. `README.md`, `docs/BUILD_SPEC.md`, `docs/PRIOR_WORK.md` — product and disclosure.
3. `docs/SCHEMA.md`, `docs/PAYMENT_STATE_MACHINE.md` — commitments and simulator.
4. `docs/NEAR_CONTRACT.md`, `docs/SANDBOX.md` — implemented contract and unrun harness.
5. `docs/ENCYCLOPEDIA.md`, `docs/ENCYCLOPEDIA_SPEC.md` — history, consent, adapter ownership.
6. `docs/KNOWLEDGE_DEMO.md`, `docs/VALIDATION.md` — integration and actual check records.
7. `docs/NEAR_REUSE.md` — historical read-only assessment of BUMM patterns.

## Commands from the repository root

Use the nested repository as the working directory:

```sh
cd /Users/vika-mac/Downloads/InvariFi/forecast-evidence-swarm
git status --short
python3 -m forecast_swarm
python3 -m forecast_encyclopedia --core-demo --core-consent fixtures_encyclopedia/core_demo_consent.json --out artifacts/product-demo
python3 -m forecast_swarm.knowledge_demo --fixture-consent --out artifacts/knowledge-demo
python3 -m unittest discover -s tests -q
python3 -m unittest discover -s tests_encyclopedia -q
cargo +1.99.1 test --manifest-path contracts/forecast_jobs/Cargo.toml --locked --offline
cargo +1.99.1 build --manifest-path contracts/forecast_jobs/Cargo.toml --locked --target wasm32-unknown-unknown --release --offline
bash -n sandbox/run.sh
```

The Python commands use only the standard library. Rust commands require the
specified installed toolchain/target and cached dependencies. Portability to another
machine may require downloading toolchains and dependencies through normal permissions.

Preview only generated, explicitly permitted outputs on the local computer:

```sh
python3 -m http.server 8873 --bind 127.0.0.1 --directory artifacts
```

Open `/demo/report.html`, `/product-demo/index.html` or `/knowledge-demo/index.html`
at that HTTP origin. Stop serving before rebuilding encyclopedia exports: its
single-writer exporter is not an atomic web deployment. `file://` was blocked by the
previous embedded browser; explicit local HTTP preview worked.

## First priority: run the actual sandbox flow (completed 2026-11-08)

**Done.** Fixes needed: three `near-workspaces` 0.24 API mismatches in the test
(`outcome().transaction_hash`, `Block::timestamp()`, `Account::delete_account`), a
moved-value error, a runner image with `pkg-config`/`libssl-dev`, and a Debian trixie
base because the `near-sandbox` 2.14.0 binary needs glibc 2.39. Results, versions and
limits are in `docs/SANDBOX.md` and `docs/VALIDATION.md`. The text below is kept as the
original specification of the milestone.

Inspect `sandbox/run.sh` and `sandbox/tests/near_sandbox.rs`, then run:

```sh
bash sandbox/run.sh
```

Previous blocker: dependency setup through a Docker command was rejected before
execution because **Codex automatic approval review hit an account usage limit**.
This was not a contract test failure. Docker Desktop and the official
`rust:1.99-slim-bookworm` image were available at the time. `near-workspaces` was
missing from the host's offline cache. Current Docker state/quota was not rechecked
during this handoff. Under Claude Code, use current normal permissions and report
new failures accurately; do not inherit assumptions about the old quota.

The harness is a draft. Expect to compile and fix SDK/API/build/runtime mismatches;
shell syntax and source review do not prove it runs. It intentionally has no
hand-edited/seeded lockfile. Generate `sandbox/Cargo.lock` through Cargo on the first
successful dependency resolution, inspect it and commit it afterward.

The wrapper creates a unique run directory, uses a task-local Cargo cache, starts
one bounded container, mounts no owner wallets and exposes no host ports. It builds
the contract on the host with the offline toolchain. Failed runs remove their new
temporary run directory; capture console diagnostics when debugging.

Required evidence of success:

- Customer funds a job; worker submits the exact core artifact hash; customer accepts;
  the worker's balance increases by exactly the reward, and the callback settles it.
- A separate submitted-but-unaccepted job refunds the customer at the acceptance
  deadline. Silence by customer/resolver must have a bounded timeout path.
- Wrong caller, duplicate payout/refund, pending-state retries and stale callbacks
  cannot release funds twice. Verify receipt results and balances, not status alone.
- Known failed payout/refund receipts preserve the original beneficiary. Recreate only
  ephemeral local accounts, retry safely, and check outstanding liabilities reach zero.
- Export two distinct artifact hashes: paid `valid_wrong` and refunded `zero_successes`.
  Recovery scenarios stay in diagnostics because the receipt schema rejects duplicate
  artifact hashes. Encode yoctoNEAR diagnostics as decimal strings (u128 exceeds JSON
  number handling in the current Rust configuration).
- The resulting paid, consented artifact opens in the generated encyclopedia. Keep
  actual chain provenance separate from the original core simulator ledger.

On full success, the wrapper should print paths under `artifacts/near-sandbox-run.*`
for `near-receipts.json`, `near-diagnostics.json` and `knowledge-demo/index.html`.
Do not fabricate these artifacts or mark the milestone complete before a real run.

## Interfaces and invariants to preserve

- Canonical integer-only, domain-separated SHA-256 format is versioned. Delivery
  commitments exclude later outcomes/evaluation/payment history; evidence order is
  normalized by ID. `validate_bundle` deterministically replays role outputs.
- Known zero observations/successes differ from missing information; future
  publication is rejected. Provisional/disputed outcomes cannot be scored as final.
- A valid delivery can be wrong and still be accepted for payment. Correctness,
  validity, acceptance, resolution, public permission and payment are separate fields.
- Private is the default. Consent binds the exact delivery hash; a new artifact does
  not inherit it. Revocation rebuilds current public output; old downloaded copies
  cannot be recalled. History validation does not authenticate a source or identity.
- The current encyclopedia adapter validates core v1 simulator report wrappers.
  An actual async NEAR result does not replace that ledger merely by renaming fields.
  Knowledge export uses a separate strict receipt/provenance sidecar.
- Contract callbacks confirm settlement. A failed accepted payout becomes
  `PAYOUT_READY`; failed refund becomes `REFUND_READY`. Retry cannot change beneficiary.
  Pending attempts are not retryable when the transfer outcome is unknown.
- Contract is deliberately bounded to ten jobs, with at least 1 NEAR initialization
  reserve and an internal 0.1 NEAR allocation per job, separate from rewards. This is
  a prototype storage policy, not a measured production cost model.

Known contract limitations: callback failure/out-of-gas can leave a pending transfer
with unknown outcome; recovery from that condition is not implemented. Resolver is
a single trusted party. The initializer is first-caller sensitive: public use must
deploy+initialize atomically; the isolated draft harness currently separates them.
The contract stores hashes and schedules, not source evidence or a proof of truth.

## After sandbox success

1. Record actual commands, SDK/runtime versions, receipt hashes, wasm hash, balance
   assertions and failure/retry results. Replace pending labels only for verified work.
2. Verify/review the real payment-to-knowledge adapter contract and history preservation.
3. Add a genuine bounded AI worker when the owner supplies approved inference access.
   Retain deterministic evidence gates, explicit uncertainty, critic/verifier roles and
   customer acceptance. Scripted functions are not autonomous inference agents.
4. Prepare the complete demo: order → research → verification → acceptance/payment →
   permitted knowledge page. Confirm official tracks/rules/deadline, choose a license,
   disclose prior work/BUMM relationship and obtain explicit publication/submission approval.

Historical deadline in local research: **2026-11-14 23:59 UTC / November 15 01:59 Kyiv**.
It was not reverified on November 8. Rules reference: `https://nearhackathon.com/HACKATHON.md`.
No license has been selected; no LICENSE file exists. Do not invent owner contact details.

## Git state and milestones

At handoff inspection, working tree was clean on `main`, code HEAD `52fa1ef`.
Configured remote: `https://github.com/GodBooster/forecast-evidence-swarm.git`.
Cached `origin/main` was `4435a9d`; local main was ahead by three commits before the
handoff commit. No fetch was performed, so this is not a fresh remote-state check.
Do not assume cloning GitHub alone contains the local NEAR work. The transfer bundle
contains local main and its full reachable history; no push was performed for handoff.

| Commit | Work |
| --- | --- |
| `2a6864a` | Initial scope and prior-work documentation |
| `bfd7f35` | Offline evidence pipeline, synthetic cases, simulator, 35 initial tests |
| `3f87f80` | Encyclopedia: private defaults and immutable history |
| `4435a9d` | Product-demo command and append-only report updates |
| `3ee43a3` | Paid/consented knowledge integration |
| `124d223` | Compiled, unit-tested NEAR escrow contract |
| `52fa1ef` | Draft sandbox harness and explicit verification limits |

Technical author for local commits if Git identity remains unset:
`git -c user.name=Codex -c user.email=codex@localhost commit ...`.
Do not change global Git identity or imply that technical author is the owner.

## Optional local context (read-only, outside the transferable source)

- Parent `near-hackathon/FIT_AND_MVP_2026-11-06_UK.md`: feasibility/product research.
- Parent `near-hackathon/ENCYCLOPEDIA_PARALLEL_DECISION_2026-11-06_UK.md`: encyclopedia decision.
- `/Users/vika-mac/Downloads/WOOF/NEAR/bumm-guard`: separate BUMM repository; the prior
  `swarm-jobs` branch/worktree was reviewed read-only. Its state may have changed.

Those local paths are pointers, not permission to copy private research, strategies,
credentials or deployment settings into this product. All runnable fixtures here
are synthetic. The portable handoff includes this repository, selected generated
synthetic outputs and Git history; no parent research or BUMM code is bundled.
