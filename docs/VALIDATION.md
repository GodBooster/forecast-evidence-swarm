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

Not covered by that run: dispute/resolve/cancel on chain (added below), callback
out-of-gas recovery, initialization takeover, gas measurement, testnet/mainnet, rustfmt.

## Submission-readiness follow-up — 2026-11-08 (later the same day)

Commands executed on the reference Intel Mac (Python 3.14.7, Rust 1.99.1, Docker 29.9.2):

```sh
python3 -m unittest discover -s tests -q            # Ran 44 tests ... OK
python3 -m unittest discover -s tests_encyclopedia -q   # Ran 30 tests ... OK
cargo +1.99.1 test --manifest-path contracts/forecast_jobs/Cargo.toml --locked --offline   # 8 passed
python3 -m forecast_swarm.walkthrough               # All walkthrough checks passed.
python3 -m forecast_swarm.walkthrough --receipts docs/evidence/sandbox-2026-11-08/near-receipts.json --out artifacts/walkthrough-sandbox
FORECAST_DOCKER_MEMORY=3500m bash sandbox/run.sh     # 2 chain tests ok (separate processes)
git diff --check
```

- New `forecast_swarm/walkthrough.py` runs order → research → evidence checks →
  acceptance/payment → encyclopedia page in one command and fails non-zero if an invariant
  breaks. Three new tests (`tests/test_walkthrough.py`) cover the simulation path, a
  sandbox-style receipt document (only the paid delivery published; refunded kept private)
  and a failing case without a PAID receipt. Python total: 44.
- New chain test `real_local_chain_dispute_resolve_timeout_and_cancel` passed on a local
  NEAR Sandbox: resolver-only dispute decisions in both directions with exact balances,
  silent-resolver refund after the dispute deadline, customer-only cancel with liability
  2 NEAR → 0, assigned job not cancellable and refunded at the delivery deadline. The
  existing escrow/recovery test passed again in the same run. Two failed attempts before
  the passing run, their causes and fixes are recorded in `docs/SANDBOX.md`.
- Wasm unchanged: SHA-256 `1ac693ee9f3a44b230cc6cfc076d90f557209938adc122e10b4de6bfd0ea6c3c`.
- The recorded receipts/diagnostics were copied to `docs/evidence/sandbox-2026-11-08/` and
  replayed through the walkthrough (1 public paid claim; refunded claim private).
- A scan of the full Git history for private-key, token and NEAR secret-key patterns found
  no matches (pattern scan, not a guarantee).
- Synthetic screenshots of the generated pages are in `docs/screenshots/`.

Still not covered: callback out-of-gas recovery, initialization takeover, gas measurement,
testnet/mainnet, rustfmt, mobile visual QA, any LLM inference.

## Bounded AI worker, offline verification — 2026-11-08

Commands executed on the reference Intel Mac (Python 3.14.7), no network, no key:

```sh
python3 -m unittest discover -s tests -q                 # Ran 78 tests ... OK (44 existing + 14 + 20 new)
python3 -m unittest discover -s tests_encyclopedia -q    # Ran 30 tests ... OK
python3 -m forecast_swarm.fixture_cassette --check       # Cassette matches the current prompt builder
python3 -m forecast_swarm.walkthrough --roles llm --replay fixtures/llm_cassettes/hand_authored_analyst.json --out artifacts/walkthrough-llm
                                                         # All walkthrough checks passed.
git diff --check
```

- `--roles scripted` (default) outputs were compared byte for byte with outputs generated
  from commit `59975b9` before the change: `python3 -m forecast_swarm`,
  `python3 -m forecast_swarm.walkthrough` (files and console text),
  `python3 -m forecast_swarm.knowledge_demo --fixture-consent` and
  `python3 -m forecast_encyclopedia --core-demo …` were all identical. Scripted delivery
  hashes are unchanged (focus `ba7aa4bf…816d`).
- `--roles llm --replay` runs the real prompt builder, output gate, budget checks, trace
  and commitments against **hand-authored** cassette answers (provider `fixture`, prices
  zero). Focus delivery `956437d3b9ec35c0495b64edaf34263f32f07ad370117483e945ea8edb309b3a`;
  three analyst calls answered from the cassette; `future_data` and `missing_data` made no
  call. The test suite also runs this walkthrough in subprocesses with sockets disabled and
  two hash seeds, with identical `report.json` bytes.
- New tests cover adapter request/response shapes (OpenAI-compatible, Anthropic API
  version `2026-10-21` without sampling parameters), refusal/HTTP/malformed/timeout
  failures with key redaction, budget refusal before sending, worst-case charging,
  record→replay equality, each output-gate rule, tampering detection, and CLI misuse.
- Contract, sandbox harness and wasm were not changed; Rust tests and the sandbox run were
  not repeated for this change.
- A pattern scan of the working tree for API-key and bearer-token shapes found only the
  explicit fake test key (pattern scan, not a guarantee).

Not done: **no live provider call**; therefore no real model output, token usage, latency,
cost or attestation exists. The live run awaits the owner's provider/model/limit decision
and a locally supplied key; its result will be appended here.
