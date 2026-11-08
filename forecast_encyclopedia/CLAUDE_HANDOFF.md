# Claude Code handoff — encyclopedia and report integration

Prepared 2026-11-08. This supplements the repository-level `CLAUDE.md`,
`docs/HANDOFF.md` and `docs/CLAUDE_CODE_START.md` when present. It is not a second
project or a separate hackathon submission. Read the repository handoff first.

## Current result

Forecast Evidence Swarm combines commissioned research, evidence checks, explicit
customer acceptance and consented knowledge pages. This module is implemented with
Python's standard library. Its roles/text are scripted and data synthetic; it does
not run live LLM inference. All 30 encyclopedia tests passed again on 2026-11-08.
The same verification session passed 41 core tests and 8 native Rust contract tests.
Native unit tests and a compiled WASM are not evidence of actual chain payments.
The NEAR sandbox harness is written but still uncompiled/unrun as of this handoff.

The key commits for this module are:

- `3f87f80`: immutable histories, private exports, HTML/JSON, initial core adapter.
- `4435a9d`: actual-core one-command demo and append-only report updates.
- `3ee43a3` (core-owned): payment-provenance adapter and consented knowledge demo.
- `124d223` / `52fa1ef` (core-owned): NEAR contract and unrun sandbox harness.

At the explicit GitHub API check on 2026-11-08, the private repository
`https://github.com/GodBooster/forecast-evidence-swarm` had main at `4435a9d`.
The implementation baseline locally was `52fa1ef`; use the local source/bundle to
retain the three newer implementation commits. A fresh remote check supersedes this
snapshot. Handoff-only commits may follow the baseline.

## Start and verify

Work in the nested repository, not the surrounding InvariFi research folder.
On the original machine it is `/Users/vika-mac/Downloads/InvariFi/forecast-evidence-swarm`.

```sh
python3 -m unittest discover -s tests_encyclopedia -v
python3 -m unittest discover -s tests -v
python3 -m forecast_encyclopedia --out artifacts/encyclopedia
python3 -m forecast_encyclopedia --core-demo \
  --core-consent fixtures_encyclopedia/core_demo_consent.json \
  --out artifacts/product-demo
python3 -m forecast_swarm.knowledge_demo --fixture-consent \
  --out artifacts/knowledge-demo
```

These are intentionally different demonstrations:

| Command | Expected result | Publication policy |
| --- | --- | --- |
| `forecast_encyclopedia` | 3 claims, 16 HTML/JSON files | Explicit encyclopedia fixture grants |
| `forecast_encyclopedia --core-demo` with grants | 8 claims, 46 HTML/JSON files | All five exact synthetic core deliveries granted, including invalid/refunded examples for inspection |
| `forecast_swarm.knowledge_demo --fixture-consent` | 5 public claims, 28 encyclopedia HTML/JSON files plus landing/provenance files | Only 2 paid, valid, consented core deliveries plus 3 encyclopedia fixtures |

Do not mistake the broad inspection gallery for a payment-gated publication policy.
Without grants, imported core claims remain private in both import paths. The
already-permitted three standalone fixtures are still present. No external network,
key or account is needed for these Python demos.

## Code map and contracts

- `model.py`: exact fields/types, UTC timestamps, identity hash, evidence references,
  immutable forecast commitment, chained versions, finality and score calculation.
- `render.py`: escaped static pages, index, safe HTTP(S) links, consent filtering,
  private-reference removal, exporter-owned directory manifest and revocation cleanup.
- `adapter.py`: `adapt_report(report, grants=None)` replays the actual core v1 report;
  `update_core_history(report, previous_records, grants=None)` preserves trusted
  versions on refresh. Missing old records stay in the returned audit collection
  privately. Changed same-time/older reports fail. Identical updates are idempotent.
- `demo.py` and `fixtures_encyclopedia/claims.json`: the 3 initial examples and a
  retained earlier version of the wrong forecast.
- `fixtures_encyclopedia/core_demo_consent.json`: permission for five exact synthetic
  core delivery hashes. Never apply these grants to arbitrary records.
- `tests_encyclopedia/`: 23 original tests plus 7 refresh/combined-demo tests.
- `forecast_swarm/knowledge_demo.py`: separate core-owned receipt/provenance layer.
  Local runner assertions are not cryptographic proof of transaction finality.
- `docs/ENCYCLOPEDIA.md`: canonical formats, trust boundaries, commands and limitations.
- `DEMO.md`: three-minute product demonstration and draft description.

Supported import contract: `forecast-evidence-swarm/v1`. The adapter verifies the
committed bundle, role replay, retrospective score and complete simulated acceptance
ledger. It does not replace that ledger with authenticated chain events. Actual
sandbox receipt provenance is attached separately by the core knowledge demo.

## Invariants to preserve

1. Exact question, scope, resolution rule, source and resolution time form identity.
   Changing them creates a distinct linked claim. New evidence creates a later
   snapshot, not a silent rewrite. Each v1 claim has one frozen historical forecast.
2. Every forecast evidence item must have been available by the fixed cutoff.
   Later outcome data never enters the original forecast commitment.
3. VALID delivery, customer ACCEPTED state, correct prediction and FINAL outcome are
   different dimensions. Unknown is not NO; PROPOSED/DISPUTED is not FINAL.
4. Prior evidence and versions cannot be rewritten or deleted through append/update.
   Provisional-to-final outcomes retain both source records. A final declaration
   cannot reverse in place in v1; use a linked correction claim.
5. Publication defaults to private. Current imports require explicit grants.
   Private content/IDs and references to private claims stay out of public export.
   The exporter cannot detect secrets manually pasted into independently public prose.
6. Revocation rebuilds the target export; it does not recall downloaded copies or
   erase a separately retained private audit history. Keep local audit storage private.
7. Hashes are unsigned commitments to bytes, not identity, truth or trusted timestamps.
   Preserve a trusted prior history/tip to detect completely rehashed substitutions.
8. Escape untrusted text, validate URLs/IDs and reject symlink/foreign output paths.
   The exporter is single-writer and is not a transactional multi-user web service.

## Next steps, in order

1. Complete the core NEAR sandbox harness in an authorized execution environment.
   Read `docs/SANDBOX.md` and `docs/NEAR_CONTRACT.md`. Verify actual payout, refund,
   failed-transfer retry, duplicate prevention and balance/liability conservation.
   The previous runner attempt hit an approval/account-usage restriction, not a
   test assertion failure. Do not bypass execution safeguards or fabricate receipts.
2. Feed successful local-chain receipts and the exact matching core report into
   `forecast_swarm.knowledge_demo`. Keep public export conditional on explicit
   consent. Preserve the forecast hash and original report during this integration.
3. If introducing real asynchronous report state, version the input contract and
   add tests. Do not weaken replay validation to make incompatible reports pass.
4. Finish browser layout review of all three page types, history, long text and
   narrow screens in a permitted environment. This module session's file-URL
   browser route was blocked. Core validation records a separate limited visual
   check of the wrong-forecast page; that is not full responsive QA.
5. Only after the end-to-end payment path works, add an authorized real inference
   adapter with explicit costs and traceable evidence. Keep offline tests and labels.
6. Prepare the final demo, prior-work disclosure and license choice. Check current
   hackathon rules and confirm publication/submission decisions with the owner.

Do not expand scope into a betting exchange, perpetual truth market, real-money
trading, or market quotes inferred from probabilities. These remain planned.

## Permissions and handoff cautions

The owner subsequently authorized creating and uploading to the private GodBooster
repository; the original `AGENTS.md` statement that no remote exists is historical.
This does not authorize switching it public, posting to X, submitting an application,
creating wallets, using paid inference or signing mainnet transactions. Never invent
owner identity, email or payout address. Communicate with the owner in Ukrainian;
public documents/UI may be English. No subagents unless separately authorized.

During the original parallel work this module owned `forecast_encyclopedia/`,
`fixtures_encyclopedia/`, `tests_encyclopedia/`, and its two encyclopedia docs.
Before Claude Code starts editing the whole project, ensure the other active
handoff/editor sessions have finished. Never reset or stage unrelated changes.
The parent InvariFi experiments, strategies, server data and BUMM project are not
part of this codebase and must remain untouched.
