# Forecast Evidence Swarm

Commission a binary forecast, get an evidence bundle checked by analyst, critic and
verifier roles, pay the worker through a NEAR escrow contract only when the customer
accepts the exact delivered artifact hash, and publish the permitted result as an
encyclopedia page with an append-only, hash-linked forecast history (tampering is
detectable against a retained copy). Deterministic gates decide whether a delivery is
valid; the customer's acceptance of the exact hash decides payment; the contract itself
binds hashes and deadlines and does not inspect validity.

> **Status (2026-11-08): working prototype, synthetic data only.** The Python product
> runs offline; the NEAR contract is unit-tested and was exercised end to end on a
> local, ephemeral NEAR Sandbox. By default analyst/critic/verifier are **scripted
> functions**. `--roles llm` swaps the analyst for a **bounded LLM worker** inside the same
> deterministic gates (provider-neutral adapter, per-order budget, committed call trace);
> it is verified offline with a **hand-authored** replay cassette and was exercised in **one
> owner-approved live run** (OpenAI `gpt-6.1-terra`, 3 calls, ≈$0.005; all outputs passed the
> gates — see [docs/VALIDATION.md](docs/VALIDATION.md)). No testnet/mainnet deployment, real funds or live data source is
> used. Forecast accuracy and trading profitability are **not** established.

**Who it is for.** A customer who wants to commission research from a worker they do not
know (a person or an AI agent) and pay only for the exact artifact they inspected; a worker
who wants a payment promise that does not depend on the customer's goodwill after delivery.

**Why NEAR.** The escrow contract gives trustless custody between the customer and an
anonymous worker, hash-bound acceptance anyone can verify against the delivered bytes,
permissionless timeout refund and transfer retry driven by block time, and a public
liability counter (`get_escrowed_rewards`) that must return to zero. The optional LLM
analyst can run on NEAR AI Cloud through the same OpenAI-compatible adapter.

"Swarm" names the analyst, critic and verifier **roles in a fixed pipeline**, not a market
of many autonomous agents.

## The problem

Paid forecasting and research work has three failure modes that usually get blurred
together:

1. **Invalid evidence** — data published after the decision cutoff, missing sources or
   observations, or an outcome that is still provisional.
2. **Wrong but honest forecasts** — a properly evidenced 75% YES that resolves NO.
3. **Payment and publication disputes** — who accepted what, whether a refund was owed,
   and whether a later "updated" page silently replaced the original forecast.

Forecast Evidence Swarm keeps these as separate, inspectable facts: *delivery validity*,
*forecast quality*, *customer acceptance*, *payment provenance* and *publication consent*
are distinct fields, each checked by its own rule. A valid delivery can be wrong and still
be paid; an invalid one is refused by the simulator at submission and is never published;
on chain, the customer re-runs the validator before accepting the hash (see
"Customer verification before `accept`" below). A page update appends a version and never edits the
original forecast.

## Try it in 30 seconds (Python 3.10+, standard library only)

From the repository root. No install, network, credentials or wallet needed.

1. **Run the walkthrough.**

   ```sh
   python3 -m forecast_swarm.walkthrough
   ```

   **See:** five numbered steps — ORDER → RESEARCH → EVIDENCE CHECKS →
   ACCEPTANCE / PAYMENT → KNOWLEDGE PAGE — ending with `All walkthrough checks passed.`
   The command exits non-zero if any invariant fails. Step 3 shows `future_data INVALID`
   and `missing_data INSUFFICIENT_DATA`; step 4 shows a `PAID` receipt bound to delivery
   hash `ba7aa4bf…816d`; step 5 shows the claim's v1 (`UNRESOLVED`, 75% YES) preserved
   next to v2 (`FINAL`, outcome NO).

2. **Replay the recorded local-chain receipts instead of simulated ones.**

   ```sh
   python3 -m forecast_swarm.walkthrough --receipts docs/evidence/sandbox-2026-11-08/near-receipts.json --out artifacts/walkthrough-sandbox
   ```

   **See:** step 4 reports `receipts: LOCAL_NEAR_SANDBOX`, one `PAID` job with transaction
   IDs, and the chain-refunded `zero_successes` delivery kept private
   (`public paid claims: 1`). These receipts were produced by the local sandbox run
   recorded in [docs/evidence](docs/evidence/sandbox-2026-11-08/README.md); that chain no
   longer exists, so the IDs cannot be checked on an explorer.

3. **Run the same flow with the LLM analyst, offline.**

   ```sh
   python3 -m forecast_swarm.walkthrough --roles llm --replay fixtures/llm_cassettes/hand_authored_analyst.json --out artifacts/walkthrough-llm
   ```

   **See:** step 2 names `analyst=llm fixture/hand-authored-synthetic-analyst`, the cited
   evidence, the model's uncertainty interval, `output gate=VALID` and the call trace
   (request/response SHA-256, tokens, cost estimate); step 3 notes that the model is not
   called when the evidence gate fails. The cassette answers were **written by hand**, not
   by a model — the label appears in the output, report and encyclopedia page. With a key
   and the owner's approval the same command runs `--live` against Anthropic or any
   OpenAI-compatible endpoint (e.g. NEAR AI Cloud); see [docs/AI_WORKER.md](docs/AI_WORKER.md).

4. **Look at the pages.**

   ```sh
   python3 -m http.server 8873 --bind 127.0.0.1 --directory artifacts
   ```

   **See:** `http://127.0.0.1:8873/walkthrough/core/report.html` (five scenarios with
   role cards, evidence tables, simulated ledgers and hashes) and
   `http://127.0.0.1:8873/walkthrough/knowledge/encyclopedia/index.html` (public claims;
   open the "next synthetic registry event" claim and its v1 link). Pre-captured synthetic
   screenshots are in [docs/screenshots](docs/screenshots/README.md).

5. **Run the tests.**

   ```sh
   python3 -m unittest discover -s tests -q
   python3 -m unittest discover -s tests_encyclopedia -q
   ```

   **See:** `Ran 84 tests … OK` and `Ran 30 tests … OK`. No test needs network or a key.

The full scripted demo, with expected output and the optional fresh chain run, is in
[DEMO.md](DEMO.md).

## How it works

```
customer order ──► analyst ─► critic ─► verifier ──► delivery bundle (canonical JSON, SHA-256;
 (question, source,  scripted, or a bounded LLM         │   includes the LLM call trace in llm mode)
  cutoff, deadlines, analyst (one call) inside the      │
  budget)            deterministic evidence and         ▼
                     output gates               NEAR escrow: create_job → assign → submit(hash)
                                                 → accept(hash) | dispute → resolve | timeout
                                                 → async transfer + callback (retry on failure)
                                                            │ receipt bound to the same hash
                                                            ▼
                             encyclopedia: published only if VALID + PAID + hash-bound consent;
                             append-only, hash-linked versions (forecast never edited in place)
```

| Component | Path | What it does |
| --- | --- | --- |
| Evidence pipeline | `forecast_swarm/evidence.py`, `demo.py` | Five synthetic scenarios; cutoff, completeness and finality gates; canonical integer-only JSON; domain-separated SHA-256 commitments; HTML/JSON report |
| Budget simulator | `forecast_swarm/payments.py` | Synchronous model of the escrow states (labelled SIMULATION) |
| Knowledge gate | `forecast_swarm/knowledge_demo.py` | Strict receipt schema; publishes only paid, valid, consented deliveries; payment provenance sidecar |
| Walkthrough | `forecast_swarm/walkthrough.py` | The end-to-end "do X, see Y" command with self-checks; `--roles scripted\|llm` |
| Customer verifier | `forecast_swarm/verify.py` | Replays a delivered bundle, requires VALID and compares its SHA-256 with the on-chain digest before `accept` |
| AI worker | `forecast_swarm/inference.py`, `llm_roles.py`, `llm_cli.py` | Provider-neutral adapter (OpenAI-compatible incl. NEAR AI Cloud, Anthropic Messages), per-order call/token/time/cost limits, committed call trace, record/replay cassettes, LLM analyst behind evidence and output gates |
| Encyclopedia | `forecast_encyclopedia/` | Private-by-default claim pages, append-only hash-linked history, core report adapter |
| NEAR contract | `contracts/forecast_jobs/` | `near-sdk` 5.17.2 escrow: bounded jobs, deadlines, hash-bound acceptance, disputes with a named resolver, timeouts, cancel, async payout/refund with fixed-beneficiary retry |
| Sandbox harness | `sandbox/` | `near-workspaces` 0.24 integration tests against a local NEAR Sandbox in Docker |

## Customer verification before `accept`

The contract pays whoever delivered the digest the customer accepts; it never looks at
the bytes. So the customer's own check is part of the protocol. Before calling
`accept(job_id, artifact_sha256)`:

1. Read the submitted digest from the contract: `get_job(job_id).artifact_sha256`.
2. Replay the delivered bundle with the same deterministic validator the worker used and
   compare the recomputed commitment with that digest:

   ```sh
   python3 -m forecast_swarm.verify --bundle artifacts/walkthrough --expect-sha256 ba7aa4bf1e5ae00ac6a1a124f042c9dab37ab0bae903671ad640451066db816d
   ```

   **See:** `replay: OK`, `hash: MATCH`, `delivery validity: VALID`, exit code 0. Any
   tampering, a non-VALID delivery or a different digest prints `DO NOT ACCEPT` and exits 1.
   `--bundle` takes a bundle JSON, a core `report.json` or a directory holding one.
3. Only then call `accept` with exactly that digest. A match proves byte agreement with
   the committed artifact and that the evidence gates passed; it does not prove the
   forecast is right.

## Verification status

| Claim | Evidence | How to reproduce |
| --- | --- | --- |
| Evidence gates, commitments, simulator, knowledge gate, walkthrough, customer verifier, AI worker (adapters, budgets, gates, provider failures, tampering, offline LLM walkthrough) | 84 Python tests | `python3 -m unittest discover -s tests -q` |
| Encyclopedia history, consent, adapter | 30 Python tests | `python3 -m unittest discover -s tests_encyclopedia -q` |
| Contract state machine and transfer recovery | 8 native Rust tests | `cargo +1.99.1 test --manifest-path contracts/forecast_jobs/Cargo.toml --locked` (first run downloads crates; add `--offline` once they are cached) |
| Real local-chain payout, timeout refund, failed-transfer retry, dispute/resolve, cancel | 2 sandbox integration tests, checked by balances and liabilities | `FORECAST_DOCKER_MEMORY=3500m bash sandbox/run.sh` (Docker, ~5–10 min) — see [docs/SANDBOX.md](docs/SANDBOX.md) |

Details and exact recorded values: [docs/VALIDATION.md](docs/VALIDATION.md).

Rust prerequisites for the contract and sandbox rows (one-time):

```sh
rustup toolchain install 1.99.1
rustup target add wasm32-unknown-unknown --toolchain 1.99.1
cargo +1.99.1 fetch --manifest-path contracts/forecast_jobs/Cargo.toml
```

## Limitations (read before judging)

- **Minimal live AI inference.** The LLM analyst path is tested offline with a hand-authored
  cassette and was run live once (three calls on synthetic inputs); the recorded live cassette
  is not published. Critic and verifier
  stay deterministic by design. A model's probability is a judgement, not a calibrated
  estimate; gates check structure and citations, not semantic truth. See
  [docs/AI_WORKER.md](docs/AI_WORKER.md).
- **Synthetic data only.** Sources such as `synthetic://event-registry/v1` are fixture labels,
  not authenticated feeds. A SHA-256 commitment proves byte agreement, not truth.
- **Local chain only.** No testnet or mainnet deployment. Sandbox transaction IDs come from
  an ephemeral chain and are runner evidence, not public anchoring.
- **Contract prototype limits.** Single trusted resolver; a callback that fails to execute
  (e.g. out of gas) can leave a pending transfer with unknown outcome, which is deliberately
  not retryable, and the 10 TGas callback allowance has not been measured; deploy and `new`
  must be one atomic batch on a public network (the local harness separates them). The
  ten-job limit is a **lifetime** cap per deployment: any account can exhaust it with ten
  1-yoctoNEAR jobs, after which the contract accepts no more work. `retry_transfer` always
  pays the originally fixed beneficiary, so if a named beneficiary account is deleted the
  funds stay locked in the contract. See [docs/NEAR_CONTRACT.md](docs/NEAR_CONTRACT.md).
- **Customer free-ride risk.** If the customer stays silent after a valid submission, the
  acceptance deadline refunds the customer; the worker's only recourse is `dispute`, which
  depends on the single named resolver acting before the dispute deadline. The contract
  does not inspect the delivery, so the customer's validation before `accept` is the only
  check that an accepted hash is a VALID bundle.
- **LLM gate limits.** The post-cutoff date gate recognises only ISO `YYYY-MM-DD` dates in
  the model text; other date formats pass. The HTTP timeout applies per socket operation,
  not to the whole call, and the response size is not bounded before it is read.
- **No claims of forecasting skill or profitability.** One synthetic Brier score proves nothing.

## Documentation map

- [DEMO.md](DEMO.md) — scripted demo with expected output.
- [docs/AI_WORKER.md](docs/AI_WORKER.md) — LLM analyst: architecture, gates, trace format, costs, limits.
- [docs/BUILD_SPEC.md](docs/BUILD_SPEC.md), [docs/SCHEMA.md](docs/SCHEMA.md), [docs/PAYMENT_STATE_MACHINE.md](docs/PAYMENT_STATE_MACHINE.md) — product, commitments, simulator.
- [docs/NEAR_CONTRACT.md](docs/NEAR_CONTRACT.md), [docs/SANDBOX.md](docs/SANDBOX.md) — contract API and chain harness.
- [docs/ENCYCLOPEDIA.md](docs/ENCYCLOPEDIA.md), [docs/KNOWLEDGE_DEMO.md](docs/KNOWLEDGE_DEMO.md) — history, consent and receipt gate.
- [docs/VALIDATION.md](docs/VALIDATION.md) — what was actually executed, when, with what result.
- [docs/PRIOR_WORK.md](docs/PRIOR_WORK.md), [docs/NEAR_REUSE.md](docs/NEAR_REUSE.md) — prior work and relationship to BUMM Guard.
- [CONTRIBUTING.md](CONTRIBUTING.md) — scope, invariants to preserve, verification commands.

The encyclopedia (`forecast_encyclopedia/`) is a module of this product, not a separate
project or submission.

## Prior work and disclosure

The ideas (timestamped forecast journals, outcome finality, deterministic replay, fixed
evaluation rules) come from the owner's private InvariFi prediction-market research. That
research is background, not evidence of forecasting skill or profitability, and none of
its code, strategies or data is in this repository. All code here was written for this
hackathon starting 2026-11-06 (see Git history).

- **Other project by the same owner:** [BUMM Guard](https://github.com/GodBooster/bumm-guard)
  — an independent NEAR HACKATHON entry for NEAR contract-code security review, in its own
  repository. No BUMM source was copied; design lessons are documented in
  [docs/NEAR_REUSE.md](docs/NEAR_REUSE.md).
- **AI-written code:** the code and documentation were written with AI coding agents —
  OpenAI Codex and Anthropic Claude Code — under the owner's direction (commit authors
  `Codex` and `Claude Code`).
- **Libraries and services:** Rust `near-sdk` 5.17.2, `near-workspaces` 0.24, `near-sandbox`,
  `serde_json`, `sha2`, `anyhow`, `tokio` (MIT and/or Apache-2.0). Python uses only the
  standard library. The optional live analyst (`--roles llm --live`) calls an external
  model API chosen by the operator (one run used the OpenAI API).
- **License:** `MIT OR Apache-2.0` ([LICENSE-MIT](LICENSE-MIT), [LICENSE-APACHE](LICENSE-APACHE)).

See [docs/PRIOR_WORK.md](docs/PRIOR_WORK.md).

## License

Licensed under either of [Apache License, Version 2.0](LICENSE-APACHE) or
[MIT license](LICENSE-MIT) at your option (`MIT OR Apache-2.0`), the same terms as
`near-sdk` and most dependencies. Unless you explicitly state otherwise, any contribution
you intentionally submit for inclusion in this work, as defined in the Apache-2.0 license,
shall be dual licensed as above, without any additional terms or conditions.
