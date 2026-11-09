# Contributing

Forecast Evidence Swarm is a hackathon prototype. These notes keep changes consistent
with what the product claims and does not claim.

## Scope and boundaries

- Forecast Evidence Swarm and its encyclopedia (`forecast_encyclopedia/`) are **one
  product** in this repository. BUMM Guard is a separate product with its own repository;
  no code is shared between them (see `docs/NEAR_REUSE.md`).
- All fixtures are synthetic. Do not add private research data, strategies, credentials,
  deployment settings or absolute local paths to tracked files.
- Public documentation is written in English and states clearly which capabilities are
  implemented, simulated or planned. Do not claim forecasting skill or profitability.
- Nothing in this repository authorizes a public deployment, a paid inference run or a
  real-money transaction; those are decisions for the operator who runs the commands.
  `chain.py` and `scripts/testnet_demo.sh` are testnet-only and never read key material.

## Invariants to preserve

- Delivery validity, forecast quality, customer acceptance, payment provenance and
  publication consent are distinct fields, each checked by its own rule. A valid delivery
  can be wrong and still be paid; an invalid one is never paid or published.
- The canonical integer-only, domain-separated SHA-256 format is versioned
  (`docs/SCHEMA.md`). Delivery commitments exclude later outcomes, evaluation and payment
  history. `validate_bundle` must deterministically replay role outputs.
- Known zero observations differ from missing information; evidence available after the
  cutoff is rejected; provisional or disputed outcomes are never scored as final.
- Publication is private by default. Consent binds the exact delivery hash; a new
  artifact does not inherit it. History is append-only and hash-linked; a page update
  appends a version and never edits the original forecast.
- Contract callbacks confirm settlement. A failed transfer becomes `PAYOUT_READY` or
  `REFUND_READY`; a retry cannot change the beneficiary; a pending attempt whose outcome
  is unknown is not retryable (`docs/NEAR_CONTRACT.md`).
- Native Rust tests and the Python simulator do not establish on-chain payment success;
  only a fresh sandbox run (`docs/SANDBOX.md`) or the testnet run (`docs/TESTNET.md`) does.
- The order hash and the four deadlines stored on chain must equal the order's terms
  (`order_commitment`, `chain_deadlines`); the customer verifier and the resolver apply the
  same rule.

## Verify before you commit

From the repository root:

```sh
python3 -m unittest discover -s tests -q
python3 -m unittest discover -s tests_encyclopedia -q
python3 -m forecast_swarm.walkthrough
cargo +1.99.1 test --manifest-path contracts/forecast_jobs/Cargo.toml --locked
git diff --check
```

To re-check the recorded testnet run (network, no key), see the README's step 6 or
`docs/TESTNET.md`.

The Python commands need only the standard library (3.10+). The first cargo run downloads
dependencies; add `--offline` only once they are cached. Generated output belongs under
the Git-ignored `artifacts/` directory. Inspect `git status` before committing and keep
each commit scoped to one change. Record what was actually executed, with its result, in
`docs/VALIDATION.md`.
