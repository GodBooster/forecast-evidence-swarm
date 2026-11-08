# Forecast Evidence Swarm

Commission a binary forecast, get an evidence bundle checked by analyst, critic and
verifier roles, pay the worker through a NEAR escrow contract only when the customer
accepts the exact delivered artifact, and publish the permitted result as an
encyclopedia page whose forecast history can never be rewritten.

> **Status (2026-11-08): working prototype, synthetic data only.** The Python product
> runs offline; the NEAR contract is unit-tested and was exercised end to end on a
> local, ephemeral NEAR Sandbox. Analyst/critic/verifier are **scripted functions, not
> LLM agents**. No testnet/mainnet deployment, real funds, live data source or model API
> is used. Forecast accuracy and trading profitability are **not** established.

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
be paid; an invalid one is never paid or published; a page update appends a version and
never edits the original forecast.

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

3. **Look at the pages.**

   ```sh
   python3 -m http.server 8873 --bind 127.0.0.1 --directory artifacts
   ```

   **See:** `http://127.0.0.1:8873/walkthrough/core/report.html` (five scenarios with
   role cards, evidence tables, simulated ledgers and hashes) and
   `http://127.0.0.1:8873/walkthrough/knowledge/encyclopedia/index.html` (public claims;
   open the "next synthetic registry event" claim and its v1 link). Pre-captured synthetic
   screenshots are in [docs/screenshots](docs/screenshots/README.md).

4. **Run the tests.**

   ```sh
   python3 -m unittest discover -s tests -q
   python3 -m unittest discover -s tests_encyclopedia -q
   ```

   **See:** `Ran 44 tests … OK` and `Ran 30 tests … OK`.

The full scripted demo, with expected output and the optional fresh chain run, is in
[DEMO.md](DEMO.md).

## How it works

```
customer order ──► analyst ─► critic ─► verifier ──► delivery bundle (canonical JSON, SHA-256)
 (question, source,     scripted roles, deterministic         │
  cutoff, deadlines,    evidence gates                        ▼
  budget)                                         NEAR escrow: create_job → assign → submit(hash)
                                                   → accept(hash) | dispute → resolve | timeout
                                                   → async transfer + callback (retry on failure)
                                                              │ receipt bound to the same hash
                                                              ▼
                               encyclopedia: published only if VALID + PAID + hash-bound consent;
                               append-only, hash-linked versions (forecast never rewritten)
```

| Component | Path | What it does |
| --- | --- | --- |
| Evidence pipeline | `forecast_swarm/evidence.py`, `demo.py` | Five synthetic scenarios; cutoff, completeness and finality gates; canonical integer-only JSON; domain-separated SHA-256 commitments; HTML/JSON report |
| Budget simulator | `forecast_swarm/payments.py` | Synchronous model of the escrow states (labelled SIMULATION) |
| Knowledge gate | `forecast_swarm/knowledge_demo.py` | Strict receipt schema; publishes only paid, valid, consented deliveries; payment provenance sidecar |
| Walkthrough | `forecast_swarm/walkthrough.py` | The end-to-end "do X, see Y" command with self-checks |
| Encyclopedia | `forecast_encyclopedia/` | Private-by-default claim pages, append-only hash-linked history, core report adapter |
| NEAR contract | `contracts/forecast_jobs/` | `near-sdk` 5.17.2 escrow: bounded jobs, deadlines, hash-bound acceptance, disputes with a named resolver, timeouts, cancel, async payout/refund with fixed-beneficiary retry |
| Sandbox harness | `sandbox/` | `near-workspaces` 0.24 integration tests against a local NEAR Sandbox in Docker |

## Verification status

| Claim | Evidence | How to reproduce |
| --- | --- | --- |
| Evidence gates, commitments, simulator, knowledge gate, walkthrough | 44 Python tests | `python3 -m unittest discover -s tests -q` |
| Encyclopedia history, consent, adapter | 30 Python tests | `python3 -m unittest discover -s tests_encyclopedia -q` |
| Contract state machine and transfer recovery | 8 native Rust tests | `cargo +1.99.1 test --manifest-path contracts/forecast_jobs/Cargo.toml --locked --offline` |
| Real local-chain payout, timeout refund, failed-transfer retry, dispute/resolve, cancel | 2 sandbox integration tests, checked by balances and liabilities | `FORECAST_DOCKER_MEMORY=3500m bash sandbox/run.sh` (Docker, ~5–10 min) — see [docs/SANDBOX.md](docs/SANDBOX.md) |

Details and exact recorded values: [docs/VALIDATION.md](docs/VALIDATION.md).

## Limitations (read before judging)

- **No AI inference yet.** The three roles are deterministic scripted functions. A bounded
  LLM worker is planned behind the same evidence gates; it needs approved inference access.
- **Synthetic data only.** Sources such as `synthetic://event-registry/v1` are fixture labels,
  not authenticated feeds. A SHA-256 commitment proves byte agreement, not truth.
- **Local chain only.** No testnet or mainnet deployment. Sandbox transaction IDs come from
  an ephemeral chain and are runner evidence, not public anchoring.
- **Contract prototype limits.** Ten jobs per deployment; single trusted resolver; a callback
  that fails to execute (e.g. out of gas) can leave a pending transfer with unknown outcome,
  which is deliberately not retryable; deploy and `new` must be one atomic batch on a public
  network (the local harness separates them). See [docs/NEAR_CONTRACT.md](docs/NEAR_CONTRACT.md).
- **No claims of forecasting skill or profitability.** One synthetic Brier score proves nothing.

## Documentation map

- [DEMO.md](DEMO.md) — scripted demo with expected output.
- [docs/BUILD_SPEC.md](docs/BUILD_SPEC.md), [docs/SCHEMA.md](docs/SCHEMA.md), [docs/PAYMENT_STATE_MACHINE.md](docs/PAYMENT_STATE_MACHINE.md) — product, commitments, simulator.
- [docs/NEAR_CONTRACT.md](docs/NEAR_CONTRACT.md), [docs/SANDBOX.md](docs/SANDBOX.md) — contract API and chain harness.
- [docs/ENCYCLOPEDIA.md](docs/ENCYCLOPEDIA.md), [docs/KNOWLEDGE_DEMO.md](docs/KNOWLEDGE_DEMO.md) — history, consent and receipt gate.
- [docs/VALIDATION.md](docs/VALIDATION.md) — what was actually executed, when, with what result.
- [docs/PRIOR_WORK.md](docs/PRIOR_WORK.md), [docs/NEAR_REUSE.md](docs/NEAR_REUSE.md) — prior work and relationship to BUMM Guard.

## Prior work and disclosure

The ideas (timestamped forecast journals, outcome finality, deterministic replay, fixed
evaluation rules) come from the owner's private InvariFi prediction-market research. That
research is background, not evidence of forecasting skill or profitability, and none of
its code, strategies or data is in this repository. All code here was written for this
hackathon starting 2026-11-06 (see Git history). BUMM Guard is a separate project by the
same owner (NEAR contract-code review); no BUMM source was copied, and design lessons are
documented in [docs/NEAR_REUSE.md](docs/NEAR_REUSE.md). See [docs/PRIOR_WORK.md](docs/PRIOR_WORK.md).

## License

Licensed under either of [Apache License, Version 2.0](LICENSE-APACHE) or
[MIT license](LICENSE-MIT) at your option (`MIT OR Apache-2.0`), the same terms as
`near-sdk` and most dependencies. Unless you explicitly state otherwise, any contribution
you intentionally submit for inclusion in this work, as defined in the Apache-2.0 license,
shall be dual licensed as above, without any additional terms or conditions.
