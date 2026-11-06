# Offline milestone validation

Local run: 2026-11-06, Python 3.14.7. Only synthetic fixtures were used.

## Executed commands and results

```sh
python3 -m forecast_swarm
python3 -m unittest discover -s tests -v
python3 -m forecast_swarm --out artifacts/replay
git diff --check
```

All **35 tests passed**: 16 evidence/schema/quality tests, 16 budget and transition
tests, and 3 end-to-end/report tests. The CLI test runs in fresh subprocesses with
different hash seeds, a credential-free environment and Python socket networking
disabled. It verifies that both output files are byte-identical. This checks the
implemented Python path; it is not an operating-system network isolation audit.

The demo produced the five documented scenarios. The valid-but-wrong case recorded
a 75% YES forecast, final NO outcome, Brier score 0.56250000 and an explicit customer
acceptance for 100 synthetic credits. Future publication was rejected; missing data
caused abstention; the unresolved outcome remained insufficient for evaluation while
delivery was valid and payment awaited customer acceptance. Known zero successes
produced a valid 0% forecast.

Independent comparison of default output and replay output confirmed:

| File | Bytes | SHA-256 of entire generated file |
| --- | --- | --- |
| `report.json` | 21458 | `f0592c871a9915d437fb1eabdb79cef8038cee5356aee1352f217b8f5230ce1a` |
| `report.html` | 19023 | `9f8c648668d55fe1e497357c6e6851a7bcb63287c888c966ee6b8bd43c2833ee` |

These are file hashes, distinct from the embedded canonical delivery commitments.
Generated output remains under Git-ignored `artifacts/` and is rebuilt by the command.

The report test parses HTML, checks five scenario sections, internal navigation,
required status labels, absence of script/external assets, and escaped untrusted text.
Browser visual QA is **not completed**: the embedded browser was verified working for
an HTTPS page, but its URL policy rejected opening this local `file://` report. No
visual rendering or responsive-layout claim is made from the HTML parser checks.

## Limits

No NEAR contract, sandbox transaction, external forecast evaluation, authenticated
source, real funds, LLM or paid API was exercised. Budget transitions are synchronous
simulations, not asynchronous receipt tests. The BUMM comparison is a read-only source
review; its tests and CI success were not independently rerun in this milestone.
