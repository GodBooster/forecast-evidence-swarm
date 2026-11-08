# Forecast Encyclopedia — offline milestone

Implemented on 2026-11-06 as a module of Forecast Evidence Swarm, in the same
repository and one planned NEAR submission. This is a local synthetic demonstration,
not live AI inference, an authenticated knowledge service or a prediction market.

## Run

From the repository root, using Python 3.10+ (tested with Python 3.14.7):

```sh
python3 -m forecast_encyclopedia --out artifacts/encyclopedia
python3 -m unittest discover -s tests_encyclopedia -v
```

No installation, credentials, network calls or third-party packages are required.
Open `artifacts/encyclopedia/index.html` locally. The command produces 16 HTML/JSON
files plus an export manifest: three public claims, four version pages, individual
claim/version JSON and an index. Every page prominently labels synthetic data and
deterministic template generation. The three examples are:

| Example | Forecast | Delivery | Resolution | Acceptance |
| --- | --- | --- | --- | --- |
| Event A, due November 10 | 75% YES | VALID | UNRESOLVED | AWAITING_CUSTOMER |
| Event B, November 2 | Original 75% YES retained | VALID | FINAL NO | ACCEPTED |
| Event C, conflicting excerpts | Abstained | INSUFFICIENT_DATA | DISPUTED, unknown | AWAITING_CUSTOMER |

Event B includes its original unresolved version. Its wrong forecast remains
inspectable and has the same forecast commitment after resolution. Accuracy is
computed only for a known final outcome and an available forecast. The tie rule is
YES for probability >= 5000 basis points. Brier is stored as an integer scaled by
100,000,000. One synthetic example proves no forecasting skill.

Use `--input path/to/claims.json` for another explicitly synthetic fixture list in
the format of `fixtures_encyclopedia/claims.json`. Unknown fields, duplicate JSON
keys, floats, malformed dates and unsupported schema states are rejected. The input
contains identities, snapshots and optional publication consent; the builder
creates and verifies complete version records. No public permission is inferred.

## One-command product demonstration

```sh
python3 -m forecast_encyclopedia --core-demo \
  --core-consent fixtures_encyclopedia/core_demo_consent.json \
  --out artifacts/product-demo
```

This runs the current core generator in memory, replays its evidence, quality and
acceptance checks, applies the exact synthetic consent grants, and writes the
combined encyclopedia. It produced 8 public claims and 46 HTML/JSON files. No raw
private core report is written into the public export. Without `--core-consent`,
core claims stay private and only the three permitted encyclopedia fixtures appear.
`--core-demo` and `--core-report` are mutually exclusive.

The three encyclopedia-producing commands are intentionally different demonstrations:

| Command | Expected result | Publication policy |
| --- | --- | --- |
| `python3 -m forecast_encyclopedia` | 3 claims, 16 HTML/JSON files | Explicit encyclopedia fixture grants |
| `python3 -m forecast_encyclopedia --core-demo --core-consent …` | 8 claims, 46 HTML/JSON files | All five exact synthetic core deliveries granted, including invalid/refunded examples for inspection |
| `python3 -m forecast_swarm.knowledge_demo --fixture-consent` | 5 public claims, 28 encyclopedia HTML/JSON files plus landing/provenance files | Only the 2 paid, valid, consented core deliveries plus the 3 encyclopedia fixtures |

Do not mistake the broad inspection gallery for a payment-gated publication policy.
Without grants, imported core claims remain private in both import paths.

The repository is now available privately at
[GodBooster/forecast-evidence-swarm](https://github.com/GodBooster/forecast-evidence-swarm).
The owner authorized repository creation and upload after the original offline
milestone. Private repository hosting does not make this a deployed website or
constitute a public hackathon submission. Generated artifacts remain excluded.

See [the demonstration script](../forecast_encyclopedia/DEMO.md) for a short guided
walkthrough and a draft product description with explicit implementation limits.

## Actual core integration

The read-only adapter supports **`forecast-evidence-swarm/v1`**, specifically the
report wrapper emitted by `forecast_swarm.demo.run_demo()`. It was exercised against
both that actual generator and the existing `artifacts/demo/report.json`, not a
copied adapter snapshot. At verification the file matched the generator exactly
under canonical JSON; its raw file SHA-256 was:

```text
f0592c871a9915d437fb1eabdb79cef8038cee5356aee1352f217b8f5230ce1a
```

If a fresh checkout has no core report, generate it with the existing core command:

```sh
python3 -m forecast_swarm --out artifacts/demo
```

Read and verify a core report while keeping its imported claims private:

```sh
python3 -m forecast_encyclopedia \
  --core-report artifacts/demo/report.json \
  --out artifacts/encyclopedia-core-private
```

This command was run successfully and still exported only the three permitted
encyclopedia examples (16 HTML/JSON files). To include the five specific synthetic
core deliveries for which this repository supplies explicit fixture consent:

```sh
python3 -m forecast_encyclopedia \
  --core-report artifacts/demo/report.json \
  --core-consent fixtures_encyclopedia/core_demo_consent.json \
  --out artifacts/encyclopedia-integrated
```

This command was run successfully: **8 public claims, 14 versions, 46 HTML/JSON
files**, plus the export manifest. Grants are keyed by the exact core delivery
SHA-256. A changed delivery requires a new grant; unknown grant hashes fail. These
synthetic grants do not authorize publication of arbitrary user records.

Adapter validation and mapping:

- Replays `validate_bundle`, so forged role results fail even if their hash was
  recomputed. Scenario and title must match the committed core input.
- Revalidates the core case, recomputes retrospective quality, and compares the
  complete simulated customer-acceptance ledger with `simulate`. This validates
  the present demo algorithm, not a real customer's signature or real payment.
- Maps core question, source and resolution time into an identity; job ID and
  scenario title form the scope. The resolution rule explicitly describes the
  current core binary-outcome policy. No production resolution policy is inferred.
- Retains the original core delivery hash in the frozen forecast method. Core
  probability and validity stay unchanged. The encyclopedia's own forecast hash
  commits to its normalized identity, forecast, selected evidence and validity.
- Only complete evidence available at cutoff becomes forecast citations. Excluded
  invalid/missing batches are explicitly named in criticism with core verifier
  reasons; an invalid delivery stays INVALID and abstains. The original core
  report remains the detailed audit source, rather than being republished whole.
- Adds later outcome and simulated acceptance as a subsequent version. Unknown or
  invalid outcome timing stays unresolved; a mismatched source is disputed; a
  provisional result is not final. Final resolution is independent of whether a
  valid forecast exists. No quality score is given for an abstention.

The next integration step is a separately versioned report/export contract with
explicit resolution-policy identity, source authentication, authenticated consent,
and real acceptance provenance. Changes to the core demo algorithm can invalidate
this adapter's exact replay and must be reviewed with contract tests. The adapter
imports core validation functions; the standalone encyclopedia demo does not.

## Updating a core report without losing history

Use `update_core_history(report, previous_records, grants)` from
`forecast_encyclopedia.adapter` when refreshing an already imported report. The
stateless `adapt_report` remains compatible with the initial import contract.

```python
from forecast_encyclopedia.adapter import adapt_report, update_core_history

history = adapt_report(first_report, explicit_grants)
history = update_core_history(later_report, history, explicit_grants)
```

The caller stores the complete returned history in private local audit storage.
`export(history, destination)` produces only the currently permitted public subset.
The updater validates both histories, retains the trusted prefix, rejects older or
changed same-time reports, and is idempotent for an identical report. A changed
initial forecast version fails instead of rewriting trusted history.

A provisional outcome becoming final retains its earlier evidence. Revised outcome
excerpts receive a new ID using the `outcome-evidence` hash domain; existing baseline
v1 import IDs stay compatible. Final declarations still cannot reverse in place.
Previously known claims absent from the latest report stay in the returned audit
collection but become private. Current grants must be supplied explicitly on each
update; neither a prior public export nor past acceptance implies renewed consent.
This conservative import rule is separate from editing a local claim whose existing
consent declaration explicitly covers its full history.

The update API is deliberately an in-memory operation: no audit database, concurrent
writer coordination or authenticated consent service is claimed.

## History and canonical commitments

`forecast-encyclopedia/v1` permits JSON null, booleans, integers, strings, lists and
string-keyed objects. Canonical bytes are UTF-8 JSON, Unicode preserved without
normalization, object keys sorted in Python Unicode order, compact separators,
no trailing newline, no floats/NaN/Infinity. This is a project format, not RFC 8785.
List order is retained except snapshot evidence is sorted by ID when appended and
selected evidence is sorted for the forecast commitment.

A digest is SHA-256 of `UTF8(schema + ':' + domain + '\n') || canonical_bytes`.
Domains are `identity`, `forecast`, and `version`:

- Claim ID is `claim-` plus the identity digest. Exact question, scope, resolution
  rule, source and resolution time are immutable identity fields. Changing any
  creates another claim. `revise_claim` records a link to the previous claim.
- Every version commits to claim ID, number, previous-version hash, forecast hash
  and full snapshot. Strictly increasing as-of timestamps are mandatory.
- Forecast commitment excludes later outcome, evaluation, acceptance and new
  non-forecast evidence. Every version must reproduce the original forecast hash.
  Existing evidence cannot be removed or rewritten. Evidence supporting a
  forecast must have been available by its fixed cutoff, inclusively.
- `append_version` returns a deep copy and validates the old chain first.
  `verify_extension(trusted, candidate)` detects rewriting or truncation against
  retained trusted history. Rehashing an entirely fabricated history cannot be
  detected from that history alone. Keep trusted prior records or tips separately.
- FINAL requires a known binary value, source-matched evidence and valid resolution
  timing. FINAL is irreversible within a v1 history; a correction needs a new linked
  claim. PROPOSED/DISPUTED do not become final through model agreement.

Version JSON preserves the exact old snapshot. Old version HTML has navigation to
all currently public versions, so its navigation can evolve without rewriting the
historical snapshot or forecast. Source truth, authorship and timestamp authenticity
are not established by these unsigned local hashes. No NEAR anchoring is implemented.

## Privacy and revocation

Absent publication settings mean private. A public record needs:

```json
{
  "allowed": true,
  "consent": {
    "by": "synthetic demo owner",
    "at": "2026-11-06T00:00:00Z",
    "statement": "Publish this claim and its complete version history"
  }
}
```

The demo owner is a fictional fixture label, not a claimed human identity. The
permission is a local input declaration; there is no authentication UI or signature.
Consent applies to the complete history, including subsequent versions. Revoke by
setting `publication` to `{"allowed": false, "consent": null}` or removing it, then
export the full current collection again to the same output directory.

For example, this reproducible local API demonstration removes all public versions
of the first record without deleting the in-memory audit history:

```python
from forecast_encyclopedia.demo import load_demo
from forecast_encyclopedia.render import export

records = load_demo()
export(records, "artifacts/encyclopedia-revocation")
records[0]["publication"] = {"allowed": False, "consent": None}
export(records, "artifacts/encyclopedia-revocation")
```

Private claim content and identifiers are omitted from public pages, JSON, indexes,
filenames and export manifests. A structured previous-claim link to a private or
missing record is omitted entirely. Local consent actor names are withheld from
public exports. Publication metadata and previous-claim links are not forecast or
version commitments; visibility can change without changing history hashes.

The exporter does not inspect arbitrary prose for secrets copied into a separately
permitted claim. A publisher must not paste private text into public input. This is
not an access-control server, DLP system or encrypted audit database. Original local
fixtures and trusted histories remain local audit material. Revocation updates this
export directory only; other export directories and previously downloaded copies
cannot be recalled. No artifacts were uploaded or published by this milestone.

## Rendering and filesystem safety

Evidence notes require valid selected evidence IDs. Source excerpts, criticism and
all other untrusted strings are HTML-escaped. Citation validation is syntactic; it
does not establish that a sentence is supported or that a source is true. Criticism
is clearly labelled supplied commentary. Synthetic identifiers are text, not public
links. Optional links accept only absolute HTTP(S) without credentials, whitespace
or backslashes; unsafe URLs are rejected. A restrictive CSP disables scripts and
remote resource loading. There are no remote fonts, images or scripts.

Claim filenames come only from identity hashes; version suffixes are validated
positive sequence numbers. Evidence IDs have a restricted alphabet. The exporter
requires an empty directory or its own manifest and refuses foreign files,
directories, symlinks (including path ancestors), and unsafe manifest entries.
On macOS use real paths such as `/private/tmp/...` rather than symlinked `/tmp/...`.
Revoked files are removed before replacement indexes are written. Generated files
are reproducible and live under the repository's already ignored `artifacts/`.

This local exporter is single-writer: directory updates are not a transactional
web deployment and are not hardened against a concurrent hostile filesystem
process. Do not serve a directory while rebuilding it. Filesystem races, crash-safe
publication, authenticated history storage and multi-user editing remain future work.

## Verification performed

On 2026-11-06 with Python 3.14.7:

- `python3 -m unittest discover -s tests_encyclopedia -v`: **30 tests passed**.
  Covers immutable prior versions and forecasts, identity revisions, cutoff equality
  and rejection, strict times, finality, wrong-but-valid/accepted forecasts,
  abstention versus zero, privacy default, explicit permission, revocation cleanup,
  private links, escaped HTML, safe URLs/paths, symlinks, manifest tampering, forged
  roles, quality/acceptance substitution, canonical JSON, trusted-history comparison,
  deterministic file bytes, every local page link and citation anchor.
- Seven additional adapter/update tests cover actual-core one-command execution,
  idempotent refresh, preserved history, proposed-to-final source records, stale
  evaluation rejection, omitted claims and explicit renewed publication grants.
- Both standalone and combined CLIs ran twice with socket construction/connections blocked in tests and
  produced byte-identical exports. Separate ordinary CLI executions also succeeded.
- `python3 -m unittest discover -s tests -v`: **35 existing core tests passed**.
  Core source and tests were not modified by this module.
- Basic, private-import and explicitly permitted integrated demos ran successfully.
  Generated HTML/JSON, page counts, statuses, version links and citation anchors were
  inspected programmatically. The actual disk core report matched the current
  generator, and adapter tests exercise the current generator directly.
- **Visual browser inspection was not completed**: the embedded browser security
  policy rejected local `file://` navigation. No alternate browser or serving
  workaround was attempted. Responsive CSS is present, but desktop/mobile visual
  layout still needs a permitted manual browser check.

## Invariants to preserve

1. Exact question, scope, resolution rule, source and resolution time form a claim's
   identity. Changing them creates a distinct linked claim. New evidence creates a later
   snapshot, not a silent rewrite. Each v1 claim has one frozen historical forecast.
2. Every forecast evidence item must have been available by the fixed cutoff. Later
   outcome data never enters the original forecast commitment.
3. VALID delivery, customer ACCEPTED state, correct prediction and FINAL outcome are
   different dimensions. Unknown is not NO; PROPOSED or DISPUTED is not FINAL.
4. Prior evidence and versions cannot be rewritten or deleted through append/update.
   Provisional-to-final outcomes retain both source records. A final declaration cannot
   reverse in place in v1; use a linked correction claim.
5. Publication defaults to private. Imports require explicit grants keyed by the exact
   delivery hash. Private content, IDs and references to private claims stay out of the
   public export. The exporter cannot detect secrets pasted into independently public prose.
6. Revocation rebuilds the target export; it does not recall downloaded copies or erase a
   separately retained private audit history.
7. Hashes are unsigned commitments to bytes, not identity, truth or trusted timestamps.
   History is append-only and hash-linked; tampering is detectable only against a retained
   copy of a trusted prior history or tip, so keep one.
8. Untrusted text is escaped, URLs and IDs validated, symlinked or foreign output paths
   rejected. The exporter is single-writer, not a transactional multi-user web service.

The supported import contract is `forecast-evidence-swarm/v1` (and its
`llm-analyst/v1` variant). The adapter verifies the committed bundle, role replay,
retrospective score and the complete simulated acceptance ledger; it does not replace
that ledger with authenticated chain events. Chain receipt provenance is attached
separately by `forecast_swarm.knowledge_demo` (see `KNOWLEDGE_DEMO.md`).

## Ownership and remaining scope

This implementation owns only `forecast_encyclopedia/`, `fixtures_encyclopedia/`,
`tests_encyclopedia/`, `docs/ENCYCLOPEDIA_SPEC.md` and this document. Core schemas,
core code, root README and other projects are unchanged by this work.

Own betting market, market data integration, authenticated source adapters,
production consent, live web hosting and real-money flows remain planned. (Since this
section was written, the core added a NEAR escrow contract with a local sandbox harness
and a bounded LLM analyst; see `NEAR_CONTRACT.md` and `AI_WORKER.md`. This module itself
still runs no inference and executes no payments.) No market odds are invented from a model probability. This milestone
uses no paid APIs, accounts, keys, mainnet, external publication or submission.
