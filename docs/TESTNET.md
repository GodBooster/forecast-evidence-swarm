# Run the escrow on NEAR testnet

One command runs the whole flow on NEAR testnet with synthetic orders: it creates four
sub-accounts (escrow contract, customer, worker agent, resolver), deploys the contract,
runs three jobs (payout, timeout refund, dispute then payout) and writes the evidence.
Testnet NEAR has no value; nothing here touches mainnet (the script and `chain.py` refuse
any account that does not end in `.testnet`).

A recorded run is in [evidence/testnet-2026-11-09](evidence/testnet-2026-11-09/README.md).
You can check it without keys (section 5) before running anything yourself.

## 1. Prerequisites

1. **Install** [near-cli-rs](https://github.com/near/near-cli-rs) (`near`) and Python 3.10+.
2. **Build the contract wasm** (Rust 1.99.1 with the `wasm32-unknown-unknown` target, see
   [NEAR_CONTRACT.md](NEAR_CONTRACT.md)):

   ```sh
   cargo +1.99.1 build --manifest-path contracts/forecast_jobs/Cargo.toml --locked --target wasm32-unknown-unknown --release
   ```

   **See:** `contracts/forecast_jobs/target/wasm32-unknown-unknown/release/forecast_jobs.wasm`
   (301,209 bytes, SHA-256 `cfb2e864…a089` for the recorded run).
3. **Create a funded testnet account** (the faucet gives 10 NEAR; a run needs about 6.5).
   Replace `<name>`:

   ```sh
   near account create-account sponsor-by-faucet-service <name>.testnet autogenerate-new-keypair save-to-keychain network-config testnet create
   ```

   **See:** the account in your OS keychain. This is the *parent*; the script creates the
   role accounts below it.

## 2. Dry run first

```sh
FES_PARENT=<name>.testnet bash scripts/testnet_demo.sh --dry-run
```

**See:** the plan (accounts, funding, deadlines, evidence directory) and every command
that would run, with `DRY RUN: nothing is sent`. No account is created, no transaction sent.

## 3. The run

```sh
FES_PARENT=<name>.testnet bash scripts/testnet_demo.sh
```

| Stage | What it prints | Open on the explorer |
| --- | --- | --- |
| Preflight | parent balance, check that the wasm exists | — |
| Setup | four `create-account` calls; one deploy-and-`new` transaction; the deployed code hash compared with your local wasm; the worker agent's restricted key | `https://testnet.nearblocks.io/address/escrow.<name>.testnet` (code hash, calls) |
| Orders | three synthetic orders with fresh deadlines; `create_job` for each, binding its order hash and escrowing 0.1 NEAR + 0.01 NEAR storage deposit | the `create_job` transactions and their `job_created` events |
| Worker agent | for each job: refuses to work unless the order hashes to the chain's `order_sha256`, builds the delivery, waits for the decision time, submits the hash | the `submit` transactions (signed by the restricted key) |
| Job A | customer re-checks the bundle against the chain, `accept` → worker paid, then `consent_publication` | `accept`, the transfer receipt to the worker, `publication_consent_granted` |
| Job C | customer `dispute`; resolver applies the same check and `resolve` → worker paid | `dispute`, `resolve`, the transfer receipt |
| Job B | customer stays silent; after the acceptance deadline the parent account calls `timeout` → refund to the customer | `timeout`, the refund receipt |
| Evidence | chain snapshot, core report, verify run, knowledge export | files in `docs/evidence/testnet-<date>/` |

Final lines: `Evidence: docs/evidence/testnet-<date>/README.md` and the contract's explorer URL.

**Time.** About 16 minutes: the deadlines are +120 s (decision), +480 s (delivery),
+780 s (acceptance) and +1380 s (dispute) from order creation. `FES_TIMERS="120 480 780 1380"`
sets them (decision, delivery, acceptance, dispute, seconds); shorten them for a quicker
run (transactions need time to land, so very small values fail) or lengthen them on a slow
connection.

**Cost.** About 6.4 testnet NEAR move from the parent to the run's own sub-accounts
(escrow 4.5, customer 1, worker 0.5, resolver 0.3) plus the parent's own gas. The contract
account holds its 1 NEAR reserve, the code storage and the escrowed rewards. Testnet NEAR has no value.

**Rerun.** `FES_RUN=2` makes the accounts `escrow-2.<name>.testnet` and so on and writes
`docs/evidence/testnet-<date>-2/`. Existing accounts and keys are reused; the script
refuses to overwrite an existing run log. `FES_OUT`, `FES_WASM` and `FES_REWARD_YOCTO`
override the evidence directory, wasm path and reward.

## 4. How the worker agent holds its key

The agent (`python3 -m forecast_swarm.chain worker-run`) is meant to run unattended, so it
does not get the worker account's full-access key.

- **What it has:** a function-call access key on the worker account, restricted to the escrow
  contract and the methods `submit` and `dispute`, with a 0.25 NEAR gas allowance. near-cli
  stores it in its legacy file store (`~/.near-credentials`), where a background process can
  read it. The worker's full-access key and every other account's keys stay in the OS
  keychain; this repository's code never reads, prints or copies key material.
- **What it can do:** read its job and the order from the chain, commit a delivery hash
  (`submit`) and open a dispute. It refuses to work unless the order it was given hashes to
  the `order_sha256` the customer stored and the deadlines agree.
- **What it cannot do without the operator:** transfer NEAR (not even its own earnings),
  deploy or replace contract code, add or remove keys, or call any other contract or method.
  The payout goes to the worker account, which only the operator's full-access key can
  spend.
- **Honest caveat:** the restricted key is a plaintext file on the operator's disk. If it
  leaks, an attacker can submit or dispute on the worker's jobs until the key is deleted or
  its allowance is spent; the restriction bounds the damage, it does not make the file safe.

## 5. Re-check the recorded run without keys

Needs network (the first command reads the testnet contract through one RPC node, read-only):

```sh
python3 -m forecast_swarm.verify --bundle docs/evidence/testnet-2026-11-09/deliveries/a.json --near-contract escrow.forecast-evidence-swarm.testnet --job-id 0
python3 -m forecast_swarm.knowledge_demo --core-report docs/evidence/testnet-2026-11-09/core-report.json --receipts docs/evidence/testnet-2026-11-09/near-receipts.json --chain-snapshot docs/evidence/testnet-2026-11-09/chain-snapshot.json --out artifacts/testnet-knowledge
```

**See:** `chain status: ACCEPTED`, `order vs chain: MATCH`, `deadlines vs chain: MATCH`,
`result: SAFE TO ACCEPT (bytes match the committed hash and the order; truth is not
proven)`; then `Public paid receipts: 1`. The second command works offline: in testnet mode
a receipt is accepted only if it matches the snapshot (status, artifact hash, order hash,
deadlines, customer, worker), and publication consent comes only from the contract's
`publication_consent` flag, not from a local file. A single RPC node is trusted for the
first command; the snapshot is only a copy of what the node returned. Compare the code hash
yourself: `python3 -m forecast_swarm.chain deployment --contract
escrow.forecast-evidence-swarm.testnet --wasm contracts/forecast_jobs/target/wasm32-unknown-unknown/release/forecast_jobs.wasm`
equals your own build only if you build with the same toolchain.

## 6. `python3 -m forecast_swarm.chain` subcommands

Every subcommand is a dry run unless `--execute` is given: it reads the chain, checks what
it can and prints the exact `near` command. Common flags: `--contract`, `--rpc-url`,
`--log`.

| Subcommand | Who | What it does |
| --- | --- | --- |
| `order` | customer | Writes a synthetic order with fresh deadlines and prints its order hash |
| `create-job` | customer | Funds a job bound to the order hash and the four deadlines |
| `assign` | customer | Assigns the worker account |
| `worker-run` | worker agent | Checks the order against the chain, builds the delivery, submits its hash |
| `customer-check` | customer | Verifies the delivery against the chain; accepts if it passes |
| `dispute` | customer or worker | Disputes a submission |
| `resolver-check` | resolver | Applies the same verification rule to a disputed job and resolves it |
| `timeout` | anyone | Waits for the applicable deadline and triggers the refund |
| `consent` | customer | Records publication consent for the accepted delivery on chain |
| `snapshot` | anyone | Records `get_job` / `get_config` (and receipts with `--log`) for offline re-checking |
| `deployment` | anyone | Checks that the deployed code hash equals a local wasm build |
| `report` | anyone | Builds the core report for order cases (input of the knowledge demo) |

## Limits

Testnet only, synthetic data, scripted roles (no LLM analyst on this path), a single RPC
node trusted by the reading tools, single trusted resolver, and a customer who stays silent
is refunded. See the Limitations in the [README](../README.md).
