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
The initial browser check could not open `file://`. A subsequent owner-authorized
HTTP preview on 2026-11-06 completed desktop visual QA in the embedded browser:
the overview and scenario detail are readable at its default 1280×720 viewport;
the overview link opens the expected scenario; role cards and the evidence table
fit without overlap. The integrated encyclopedia's valid-but-wrong forecast page
also renders correctly, and its version-1 link retains the original unresolved
forecast while version 2 shows final NO. Screenshots are local artifacts at
`artifacts/demo/visual-desktop.png` and `artifacts/demo/visual-encyclopedia.png`.
Mobile widths have not been visually checked.

Preview command (binds only to the local computer and serves generated artifacts):

```sh
python3 -m http.server 8873 --bind 127.0.0.1 --directory artifacts
```

Open `http://127.0.0.1:8873/demo/report.html` or
`http://127.0.0.1:8873/encyclopedia-integrated/index.html` after generating the
respective outputs. Stop the server before rebuilding encyclopedia exports; the
exporter is single-writer and does not provide an atomic live deployment.

## Limits

No NEAR contract, sandbox transaction, external forecast evaluation, authenticated
source, real funds, LLM or paid API was exercised. Budget transitions are synchronous
simulations, not asynchronous receipt tests. The BUMM comparison is a read-only source
review; its tests and CI success were not independently rerun in this milestone.

## Knowledge integration follow-up — 2026-11-07

`python3 -m unittest discover -s tests -v` passed **41 tests**, including six new
consent/receipt/export tests. `python3 -m unittest discover -s tests_encyclopedia -v`
passed **30 tests** against the current independently developed encyclopedia module.
`python3 -m forecast_swarm.knowledge_demo --fixture-consent --out artifacts/knowledge-demo`
generated the landing page, encyclopedia history and two consented paid SIMULATION
entries. Refunded imported claims stayed private. These runs confirm the offline
integration and do not establish that a NEAR transfer occurred.

## Contract follow-up — 2026-11-07

The independent `contracts/forecast_jobs/` crate compiled using Rust 1.99.1 and
cached dependencies. Eight native unit tests passed and a release wasm build
succeeded. The output is 230,688 bytes; SHA-256:
`1ac693ee9f3a44b230cc6cfc076d90f557209938adc122e10b4de6bfd0ea6c3c`.
See [contract specification](NEAR_CONTRACT.md) for the actual API and transfer recovery
limits. Sandbox tests remain uncompiled/unexecuted because dependency setup through
Docker was blocked by an automatic approval account usage limit. No sandbox receipt
or chain transfer is part of this validation. Rustfmt was unavailable locally.

## Sandbox follow-up — 2026-11-08

`FORECAST_DOCKER_MEMORY=3500m bash sandbox/run.sh` completed end to end on an Intel Mac
with Docker Desktop 29.9.2. The runner image `forecast-near-runner:1.99` (Debian trixie,
rustc 1.99.1) compiled `sandbox/` with the committed `Cargo.lock` (near-workspaces 0.24.0,
near-sandbox 0.4.0 / node 2.14.0) and ran **1 integration test: passed in 95.05 s**.
Native checks on the same code still pass: 41 + 30 Python tests, 8 Rust unit tests;
the wasm hash is unchanged (`1ac693ee…0ea6c3c`).

Verified on the ephemeral local chain with a 2 NEAR reward per job: exact worker payout
after customer acceptance (wrong caller and duplicate rejected), exact customer refund of
an unaccepted submission at the acceptance deadline, one failed payout receipt and one
failed refund receipt (recipient accounts deleted) preserved as `PAYOUT_READY` /
`REFUND_READY` and settled by permissionless `retry_transfer` with the original
beneficiary, and `get_escrowed_rewards` = 0 after every settlement and at the end.
The two exported receipts flowed through `forecast_swarm.knowledge_demo`; the paid
`valid_wrong` claim was published with its transaction IDs, the refunded claim was not.
Evidence: `artifacts/near-sandbox-run.nzgFCx/` (Git-ignored). Details and limits: `docs/SANDBOX.md`.

Not covered: dispute/resolve/cancel on chain, callback out-of-gas recovery,
initialization takeover, gas measurement, testnet/mainnet, rustfmt.
