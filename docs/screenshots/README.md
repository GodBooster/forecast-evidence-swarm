# Screenshots — SYNTHETIC DATA

Captured 2026-11-08 at 800×600 in the Claude desktop embedded browser from pages generated
by `python3 -m forecast_swarm.walkthrough` (and its `--receipts` variant), served over
`python3 -m http.server 8873 --bind 127.0.0.1 --directory artifacts`.

Every question, observation, outcome, account and consent shown is a **synthetic fixture**.
Roles are scripted functions; no LLM, live data source or public chain is involved.

| File | Page | Shows |
| --- | --- | --- |
| `synthetic-01-report-overview.jpg` | `walkthrough/core/report.html` | Scenario overview: validity, quality and acceptance as separate columns |
| `synthetic-02-roles-and-evidence.jpg` | `walkthrough/core/report.html#valid_wrong` | Analyst 75% YES, critic findings, verifier VALID (each labelled scripted) and the evidence table |
| `synthetic-03-encyclopedia-v1-unresolved.jpg` | `walkthrough-sandbox/knowledge/encyclopedia/claim-43c6dc2d…-v1.html` | Version 1: 75% YES, outcome unresolved |
| `synthetic-04-encyclopedia-v2-final.jpg` | `walkthrough-sandbox/knowledge/encyclopedia/claim-43c6dc2d….html` | Version 2: same 75% YES forecast, outcome FINAL · NO, incorrect direction retained |

The "Customer acceptance · simulation" label on encyclopedia pages comes from the core
report's simulated ledger, which the page history is built from. Chain payment provenance
for the sandbox variant is kept separately in `payment-provenance.json`.
