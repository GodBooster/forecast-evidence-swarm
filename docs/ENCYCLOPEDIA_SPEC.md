# Encyclopedia module: parallel implementation contract

Authorized by the owner on 2026-11-06. This is a module of Forecast Evidence Swarm: one product, one repository and one planned hackathon submission.

## File ownership

The encyclopedia implementation owns only:

- `forecast_encyclopedia/`
- `fixtures_encyclopedia/`
- `tests_encyclopedia/`
- `docs/ENCYCLOPEDIA_SPEC.md`
- `docs/ENCYCLOPEDIA.md`

The core implementation in the other chat owns `forecast_swarm/`, `fixtures/`, `tests/`, root README and other existing files. Read these as needed; do not modify them. Do not modify the shared core schema for this module. Build a read-only adapter for the core report and version its supported input contract. If that contract is still changing, use a clearly labelled fixture snapshot until actual integration passes.

Use explicit file paths when staging. Do not stage or commit another chat's changes. Before a commit check for an occupied shared index; defer the commit if another task has staged changes. Never reset someone else's index or checkout. Local commits are authorized; no push or publication is authorized.

## First deliverable

One offline command, proposed `python3 -m forecast_encyclopedia --out artifacts/encyclopedia`, creates an index, readable claim pages and machine-readable version records without credentials, network or LLM calls. The exact command must be documented after implementation.

Use synthetic fixtures for at least three cases: a future event with a forecast, a resolved event retaining a wrong forecast, and insufficient/disputed evidence. Include a changed page with an inspectable earlier version. Display synthetic/template generation prominently; do not call it live AI inference or a live prediction market.

## Page and version model

Each claim has a stable ID, exact question/scope, resolution rule and source, resolution time where applicable, publication permission and append-only version history. A changed question or changed resolution rule creates a distinct claim linked to the prior one. Define a canonical encoding and versioned hashes.

Each page version has an explicit as-of time, evidence references, the model forecast if available, criticism and reasons, outcome/dispute status, previous-version hash and change reason. Validate strictly increasing version times and evidence availability at the applicable forecast cutoff. Later evaluation must not mutate or leak into the historical forecast commitment.

Delivery validity, customer acceptance, forecast accuracy and claim resolution are different fields. A valid delivery can contain a wrong forecast. A proposed/disputed result is not final. Unknown evidence is not a negative outcome. No threshold of model agreement turns a claim into a fact.

Publication is private by default and needs explicit permission in the input record. Private records and their content must not appear in public HTML, indexes, exported JSON, filenames or search metadata. A public record referencing a private record must not expose its content. Demonstration fixtures can explicitly opt in. Revocation prevents current public export; document that previously downloaded copies cannot be recalled and that local audit retention differs from public visibility.

## Evidence and rendering

Use deterministic templates for the initial offline text. Each factual sentence must point to selected evidence IDs or a supplied excerpt. Validate references and disclose that syntactic citation checks do not prove semantic support or source truth. Do not fabricate external citations. Synthetic source identifiers must render as labelled text rather than working public URLs.

Escape all untrusted strings in HTML, restrict link schemes to safe supported HTTP(S) URLs and prevent path traversal through claim/version IDs. Test hostile text and URLs. User-facing pages should focus on the question, evidence, disagreement and uncertainty, with technical commitments available in details.

Show market information only when actually supplied and validated: exact contract identity, timestamp, bid/ask and source; do not infer it from model probability. The first milestone may omit market data and mark market integration as planned. No AMM, real-money bets, wallets, oracle deployment, paid inference or mainnet integration is part of this milestone.

## Required verification

Meaningful tests must cover prior-version preservation, revision of question/rules, later-data rejection, unresolved/disputed outcomes, private-by-default exports and revocation, wrong-but-valid forecasts, unsafe HTML/links/paths, tamper detection and reproducible outputs. Run the demo and inspect generated pages. Test the adapter against the actual core report when available; report integration as pending if only a snapshot was exercised.

Write `docs/ENCYCLOPEDIA.md` with commands, actual test results, ownership, limitations and next integration step. Commit only owned files after checking the shared index. Do not modify root README during parallel work.

## Local background

The independent feasibility review is at `../near-hackathon/ENCYCLOPEDIA_PARALLEL_DECISION_2026-11-06_UK.md`. It is internal context; do not copy private research into the public module. NEAR contracts, payment handling and swarm execution remain the core chat's responsibility. This module publishes permitted research artifacts and preserves their history.

## Implemented v1 decisions (2026-11-06)

The executable is `python3 -m forecast_encyclopedia --out artifacts/encyclopedia`.
Implementation and verification details are in `docs/ENCYCLOPEDIA.md`.

- Identity includes exact question, scope, resolution rule/source/time; its digest
  is the claim ID. `revise_claim` creates a linked distinct claim.
- Forecasts stay frozen for the entire claim history. Later evidence and outcomes
  enter new page snapshots without altering the forecast commitment.
- Final outcomes cannot be reversed in-place in v1. Corrections require linked
  claims, so an earlier final declaration remains inspectable.
- Local consent explicitly covers the complete history. Private-to-public links
  are filtered during export. Revocation rebuilds the dedicated export directory,
  while local audit retention remains separate.
- Actual core v1 reports are replay-validated by a read-only adapter. Imported
  claims remain private unless per-delivery-hash consent is supplied. The fixture
  grant file covers only the five known synthetic core deliveries.
- HTML/JSON and link validation passed. Visual browser inspection is outstanding
  because the embedded browser blocked local file URLs; no visual QA claim is made.
