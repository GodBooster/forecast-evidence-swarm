# Validation log

> **This is a chronological log.** Each section records what was executed on that date,
> with the test counts of that moment; earlier counts (35, 41, 44, 84, 154, 157, 8 Rust tests) are historical.
> **Current totals: 162 Python tests (`tests/`), 30 encyclopedia tests
> (`tests_encyclopedia/`), 14 native Rust contract unit tests and 2 sandbox integration tests.**
> The latest entry is [2026-11-13: one-page demo](#2026-11-13-one-page-demo).
> Re-verify with the commands in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Offline milestone validation — 2026-11-06

Local run: 2026-11-06, Python 3.14.7. Only synthetic fixtures were used.

## Executed commands and results

```sh
python3 -m forecast_swarm
python3 -m unittest discover -s tests -v
python3 -m forecast_swarm --out artifacts/replay
git diff --check
```

All **35 tests passed** (the count at that time): 16 evidence/schema/quality tests, 16 budget and transition
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
The initial browser check could not open `file://`. A subsequent local HTTP preview
on 2026-11-06 completed desktop visual QA in the embedded browser:
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

`python3 -m unittest discover -s tests -v` passed **41 tests** (then), including six new
consent/receipt/export tests. `python3 -m unittest discover -s tests_encyclopedia -v`
passed **30 tests** against the current independently developed encyclopedia module.
`python3 -m forecast_swarm.knowledge_demo --fixture-consent --out artifacts/knowledge-demo`
generated the landing page, encyclopedia history and two consented paid SIMULATION
entries. Refunded imported claims stayed private. These runs confirm the offline
integration and do not establish that a NEAR transfer occurred.

## Contract follow-up — 2026-11-07

The independent `contracts/forecast_jobs/` crate compiled using Rust 1.99.1 and
cached dependencies. Eight native unit tests passed and a release wasm build
succeeded. The output was 230,688 bytes (superseded wasm: first-generation contract, replaced
on 2026-11-09; current hash below), SHA-256 `1ac693ee9f3a44b230cc6cfc076d90f557209938adc122e10b4de6bfd0ea6c3c`.
See [contract specification](NEAR_CONTRACT.md) for the actual API and transfer recovery
limits. Sandbox tests remain uncompiled/unexecuted because dependency setup through
Docker was blocked by an automatic approval account usage limit. No sandbox receipt
or chain transfer is part of this validation. Rustfmt was unavailable locally.

## Sandbox follow-up — 2026-11-08

`FORECAST_DOCKER_MEMORY=3500m bash sandbox/run.sh` completed end to end on an Intel Mac
with Docker Desktop 29.9.2. The runner image `forecast-near-runner:1.99` (Debian trixie,
rustc 1.99.1) compiled `sandbox/` with the committed `Cargo.lock` (near-workspaces 0.24.0,
near-sandbox 0.4.0 / node 2.14.0) and ran **1 integration test: passed in 95.05 s**.
Native checks on the same code still passed at that time: 41 + 30 Python tests, 8 Rust unit tests;
the wasm hash was unchanged (`1ac693ee…0ea6c3c`, superseded wasm).

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
python3 -m unittest discover -s tests -q            # Ran 44 tests ... OK (count at that time; now 79)
python3 -m unittest discover -s tests_encyclopedia -q   # Ran 30 tests ... OK
cargo +1.99.1 test --manifest-path contracts/forecast_jobs/Cargo.toml --locked --offline   # 8 passed
python3 -m forecast_swarm.walkthrough               # All walkthrough checks passed.
python3 -m forecast_swarm.walkthrough --receipts docs/evidence/sandbox-2026-11-09/near-receipts.json --out artifacts/walkthrough-sandbox   # path as of 2026-11-09; was sandbox-2026-11-08 (superseded)
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
- Wasm unchanged that day: SHA-256 `1ac693ee9f3a44b230cc6cfc076d90f557209938adc122e10b4de6bfd0ea6c3c` (superseded wasm).
- The recorded receipts/diagnostics were copied to `docs/evidence/sandbox-2026-11-08/` (superseded path: removed on 2026-11-09, replaced by `docs/evidence/sandbox-2026-11-09/`) and
  replayed through the walkthrough (1 public paid claim; refunded claim private).
- A scan of the full Git history for private-key, token and NEAR secret-key patterns found
  no matches (pattern scan, not a guarantee).
- Synthetic screenshots of the generated pages are in `docs/screenshots/`.

Still not covered: callback out-of-gas recovery, initialization takeover, gas measurement,
testnet/mainnet, rustfmt, mobile visual QA, any LLM inference.

## Bounded AI worker, offline verification — 2026-11-08

Commands executed on the reference Intel Mac (Python 3.14.7), no network, no key:

```sh
python3 -m unittest discover -s tests -q                 # Ran 79 tests ... OK (44 existing + 15 + 20 new)
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

At that point **no live provider call had been made**, so no real model output, token
usage, latency, cost or attestation existed yet. The owner-approved live run that followed
the same day is recorded in the next section.

## Bounded AI worker, one live run — 2026-11-08

Approved by the owner in the Claude Code session on 2026-11-08: provider "other
OpenAI-compatible" (OpenAI API), model `gpt-6.1-terra`, hard ceiling **$1 per run**,
operator prices **$1 per million input tokens / $5 per million output tokens**. The owner
placed the key in a Git-ignored local `.env.local` (mode 600); it was never printed,
committed or written to any trace or cassette (a byte search of the cassette and all run
outputs for the key found nothing).

```sh
python3 -m forecast_swarm.walkthrough --roles llm --live --env-file .env.local \
  --max-cost-usd 0.30 --max-run-cost-usd 1 --max-output-tokens 4000 \
  --input-price-nano-usd-per-token 1000 --output-price-nano-usd-per-token 5000 \
  --record artifacts/live-cassette-2026-11-08.json --out artifacts/walkthrough-live
# All walkthrough checks passed. (exit 0)
```

Configuration: `api_base` `https://api.openai.com/v1`, `max_completion_tokens` field,
no reasoning effort and no temperature sent, one call per order, 60 s timeout.

| Order | Evidence | Call | Tokens in/out (provider) | Cost estimate | Model output | Gate | Delivery |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `valid_wrong` | 15/20 YES | OK, `finish_reason=stop`, model reported `gpt-6.1-terra` | 512 / 230 | $0.001662 | 7273 bps, interval 5200–8800, cites `batch-01` | VALID | VALID, `68241e6609272610e3f4787de141160c3dd8a75805e47ecf734b1520ac40615b` |
| `future_data` | published after cutoff | none (evidence gate) | — | $0 | — | NOT_RUN | INVALID |
| `missing_data` | missing counts/source | none (evidence gate) | — | $0 | — | NOT_RUN | INSUFFICIENT_DATA |
| `unresolved` | 15/20 YES | OK, `stop` | 512 / 190 | $0.001462 | 7273 bps, interval 5000–9000 | VALID | VALID |
| `zero_successes` | 0/20 YES | OK, `stop` | 512 / 204 | $0.001532 | 455 bps, interval 10–1610 | VALID | VALID |

- **Actual run cost estimate: $0.004656** for 3 calls, 1,536 input and 624 output tokens,
  computed from the owner-supplied prices. This is not an invoice; the provider's billing
  page is authoritative. Ceiling was $1; the worst case allowed by the limits was $0.066.
- All three outputs were bare JSON objects (`output_format: json`) and passed every gate.
  The model used a uniform-prior (Laplace) estimate, (yes+1)/(n+2), in each case.
- Synthetic evaluation, for completeness only: `valid_wrong` incorrect direction
  (Brier 0.5290), `zero_successes` correct direction (Brier 0.0207). Two synthetic
  outcomes say nothing about forecasting skill.
- No attestation was requested or received (`attestation: null`). Latency was not recorded.
- Offline replay of the recorded cassette with sockets disabled reproduced **identical
  deliveries and hashes** for all five scenarios, and every live bundle passes
  `validate_bundle`.

Defect found and fixed during this run: the first recorded cassette did not store the
request options (`max_tokens_field`), so replay built a different request and failed with
a cassette miss. Cassettes now carry `temperature_milli` and `options`, and replay uses
them. The recorded file was migrated by adding exactly those two fields, copied from the
committed trace (`{"max_tokens_field": "max_completion_tokens"}`, `null`); model text and
usage were not touched, and the identical replay hashes above confirm the migration.
Files (Git-ignored, not published): `artifacts/live-cassette-2026-11-08.json`
(SHA-256 `97d563885960e44daf2ef922904eebe74a687732b5e2d0981ec5ed8b4ed59171`, migrated) and
`artifacts/live-cassette-2026-11-08.original.json`
(`2a0bf925a9647f59fdb20a1668b3e9a055f004899c173691bd110347da87bfda`, as recorded).
Whether to commit the recorded cassette is the owner's decision.

## Pre-publication review fixes — 2026-11-08 (evening)

A review before making the repository public found no code or test defects but several
documentation problems: private process files with absolute local paths, stale "planned"
statements about the contract, overclaims ("never be rewritten", "gates decide payment"),
stale test counts, a test that hard-coded `/private/tmp` and cargo instructions that fail on
a cold cache. The fixes are documentation-only except for three small code changes:
`forecast_encyclopedia/render.py` and `forecast_swarm/knowledge_demo.py` label a chain-paid
page "Customer acceptance · local NEAR Sandbox receipt" (one new test), and the new
`forecast_swarm/verify.py` implements the customer's pre-`accept` check (four new tests).
Commands executed on the reference Intel Mac (Python 3.14.7, Rust 1.99.1) after the change:

```sh
python3 -m unittest discover -s tests -q                 # Ran 84 tests ... OK
python3 -m unittest discover -s tests_encyclopedia -q    # Ran 30 tests ... OK
python3 -m forecast_swarm.walkthrough                    # All walkthrough checks passed.
python3 -m forecast_swarm.walkthrough --receipts docs/evidence/sandbox-2026-11-09/near-receipts.json --out artifacts/walkthrough-sandbox   # path as of 2026-11-09; was sandbox-2026-11-08 (superseded)
python3 -m forecast_swarm.walkthrough --roles llm --replay fixtures/llm_cassettes/hand_authored_analyst.json --out artifacts/walkthrough-llm
python3 -m forecast_swarm.verify --bundle artifacts/walkthrough --expect-sha256 ba7aa4bf1e5ae00ac6a1a124f042c9dab37ab0bae903671ad640451066db816d   # exit 0
cargo +1.99.1 test --manifest-path contracts/forecast_jobs/Cargo.toml --locked   # 8 passed
# plus a scan of all tracked files for absolute local home-directory paths: no matches
```

The contract source, wasm and sandbox harness were not changed; the sandbox run was not
repeated. Scripted delivery hashes are unchanged (focus `ba7aa4bf…816d`).

## 2026-11-09: contract v2, chain layer, testnet run

Changes since the entries above: contract v2 (order hash in `create_job`, a 0.01 NEAR
non-refundable storage deposit per job instead of the ten-job cap, NEP-297 events, on-chain
publication consent, NEP-330 metadata view, new views), a read-only RPC client and chain tooling
in Python (`forecast_swarm/near_rpc.py`, `chain.py`, chain mode of `verify.py`), receipts v2 and
chain snapshots for the knowledge demo, and `scripts/testnet_demo.sh`. Documentation:
[NEAR_CONTRACT.md](NEAR_CONTRACT.md), [SANDBOX.md](SANDBOX.md), [TESTNET.md](TESTNET.md).

Native checks (reference Intel Mac, Python 3.14.7, Rust 1.99.1):

```sh
python3 -m unittest discover -s tests -q                 # Ran 154 tests ... OK
python3 -m unittest discover -s tests_encyclopedia -q    # Ran 30 tests ... OK
cargo +1.99.1 test --manifest-path contracts/forecast_jobs/Cargo.toml --locked --offline   # test result: ok. 14 passed; 0 failed
python3 -m forecast_swarm.walkthrough                    # All walkthrough checks passed.
python3 -m forecast_swarm.walkthrough --receipts docs/evidence/sandbox-2026-11-09/near-receipts.json --out artifacts/walkthrough-sandbox
python3 -m forecast_swarm.verify --bundle artifacts/walkthrough --expect-sha256 ba7aa4bf1e5ae00ac6a1a124f042c9dab37ab0bae903671ad640451066db816d   # result: SAFE TO ACCEPT, exit 0
```

The scripted delivery hash of the focus scenario is unchanged (`ba7aa4bf…816d`). The release
wasm is 301,209 bytes, SHA-256 `cfb2e8649877b6d1c9424a46231c815c31f5487e4b0393633725a30a9f52a089`.
The worst-case job record measured in a unit test is 390 bytes (0.0039 NEAR) against the
0.01 NEAR storage deposit.

Local NEAR Sandbox, `FORECAST_DOCKER_MEMORY=3500m bash sandbox/run.sh` (Docker runner), both
tests passed against that wasm:

```text
test real_local_chain_escrow_and_transfer_recovery ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 104.80s
test real_local_chain_dispute_resolve_timeout_and_cancel ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 97.01s
```

Five jobs in each test, final reward liability 0. Beyond the 2026-11-08 assertions the tests now
check the order hash (recomputed independently in Rust), the NEP-297 events of every transition,
storage-deposit accounting and the worst-case record, publication consent and its revocation, the
NEP-330 view and callback gas: the 12 `on_transfer_complete` receipts burnt 1.736 to 1.768 TGas
against the 10 TGas allowance (5.7 times the maximum; the harness requires 2 times). The recorded
files and their hashes are in
[`docs/evidence/sandbox-2026-11-09/`](evidence/sandbox-2026-11-09/README.md).

NEAR testnet, `scripts/testnet_demo.sh` with parent account `forecast-evidence-swarm.testnet` on
2026-11-09: contract `escrow.forecast-evidence-swarm.testnet`, deployed and initialized in one
transaction; the on-chain code hash `EymcyzFbW1UKzjmeNzrtKfhTMmbENzXgDt17a91Gx73v` equals the
local wasm SHA-256 above (`deployment.json`). Three synthetic jobs of 0.1 NEAR with scripted roles:
accept and payout followed by on-chain publication consent; customer silence followed by a
permissionless `timeout` refund; a dispute decided by the resolver's rule (chain-mode `verify`).
Transactions, explorer links and the snapshot are in
[`docs/evidence/testnet-2026-11-09/README.md`](evidence/testnet-2026-11-09/README.md) and are
described in [TESTNET.md](TESTNET.md). Re-check without keys (needs network access):

```sh
python3 -m forecast_swarm.verify --bundle docs/evidence/testnet-2026-11-09/deliveries/a.json --near-contract escrow.forecast-evidence-swarm.testnet --job-id 0
python3 -m forecast_swarm.knowledge_demo --core-report docs/evidence/testnet-2026-11-09/core-report.json --receipts docs/evidence/testnet-2026-11-09/near-receipts.json --chain-snapshot docs/evidence/testnet-2026-11-09/chain-snapshot.json --out artifacts/testnet-knowledge
```

Not covered: a callback that runs out of gas or never executes, an adversarial test of
initialization takeover (the testnet deployment avoids it with a single deploy-and-initialize
transaction), gas measurement on testnet (gas figures are from the local sandbox), mainnet,
`rustfmt`, a security audit, any LLM inference on the chain path (testnet roles are scripted),
and mobile visual QA. The testnet reads trust one RPC node; testnet NEAR has no value and the
network can be reset.

## 2026-11-13: failed-transfer exit code

`forecast_swarm/chain.py` treated `PAYOUT_READY` and `REFUND_READY` (the transfer receipt
failed; nothing was paid yet) like a finished payment and exited 0. It now prints
`TRANSFER NOT COMPLETED` and exits 3, and a new `retry-transfer` subcommand repeats the
transfer for the fixed beneficiary. Three tests cover a failed payout followed by a retry,
a failed refund after timeout, and a refused retry. The contract is unchanged. README
Limitations now also name two known gaps: chain snapshots are read in several calls, not
at one block, and `resolver-check` judges whatever copy of the delivery it is given.

```sh
python3 -m unittest discover -s tests -q                 # Ran 157 tests ... OK
python3 -m unittest discover -s tests_encyclopedia -q    # Ran 30 tests ... OK
```

## 2026-11-13: one-page demo

`docs/demo/` is a static page (HTML, CSS, browser JavaScript; no wallet, key or RPC) with
three parts: the recorded AI forecast of the 2026-11-08 live run (`valid_wrong`, 72.73% YES,
model range 52–88%, outcome NO; numbers from the table above), the paid NEAR testnet job 0
from `docs/evidence/testnet-2026-11-09/` (a separate run with the scripted analyst), and a
hash check: the browser recomputes the delivery commitment with Web Crypto using the same
rule as `forecast_swarm/evidence.py`. The original delivery gives
`ebb69f520eba9d71005afb006b731b251f41e4511fe10657263b96ef39509319`, equal to the accepted
on-chain digest; changing `yes_count` 15 → 16 gives
`e757b2cf109a904140b2518e90a20572fe0702e78285f6766d9241ee3af6de75`. The page checks the hash
only; the full replay of the evidence rules stays in Python. `tests/test_demo_page.py` pins
the page data to the committed evidence and, when Node.js is installed, runs the page's
JavaScript against both values. Checked in a browser at 1280×720 and 375×812.

```sh
python3 -m unittest discover -s tests -q                 # Ran 162 tests ... OK
```
