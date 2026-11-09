#!/usr/bin/env bash
# One end-to-end run of the escrow on NEAR testnet, with deadlines in minutes.
#
#   FES_PARENT=<your-account>.testnet bash scripts/testnet_demo.sh --dry-run   # print the plan
#   FES_PARENT=<your-account>.testnet bash scripts/testnet_demo.sh             # run it
#
# What it does (testnet NEAR only, synthetic orders only):
#   setup   four sub-accounts of FES_PARENT, one per role (escrow, customer, worker, resolver);
#           contract deployed and initialised in ONE transaction; a function-call access key
#           for the worker agent, restricted to this contract and to `submit` and `dispute`
#   job A   order -> worker agent submits -> customer verifies against the chain -> accept
#           -> worker paid -> customer records publication consent on chain
#   job B   worker submits -> customer stays silent -> anyone triggers the timeout refund
#   job C   worker submits -> customer disputes -> resolver applies the verification rule
#           -> worker paid
#   proof   chain snapshot, receipts, per-transaction explorer links and the deliveries in
#           docs/evidence/testnet-<date>/, then the consent-gated encyclopedia export
#
# Keys: near-cli-rs creates and keeps every key. Full-access keys go to the OS keychain; the
# worker agent's restricted key goes to near-cli's legacy file store (~/.near-credentials),
# which is where an unattended agent process would read it. This script never reads, prints
# or copies key material, and it refuses any account that is not on testnet.
#
# Requirements: near-cli-rs (`near`), python3, the contract wasm (built by the cargo command
# in docs/NEAR_CONTRACT.md), and about 6.5 testnet NEAR on FES_PARENT (the faucet gives 10).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    -h|--help) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

PARENT="${FES_PARENT:-}"
if [[ -z "$PARENT" ]]; then
  echo "Set FES_PARENT to an existing testnet account whose key is in near-cli's keychain." >&2
  exit 2
fi
if [[ "$PARENT" != *.testnet ]]; then
  echo "Refusing: FES_PARENT must end with .testnet (this script never touches mainnet)." >&2
  exit 2
fi

NETWORK=testnet
SUFFIX="${FES_RUN:+-$FES_RUN}"                 # FES_RUN=2 -> escrow-2.<parent>, for a second run
ESCROW="escrow${SUFFIX}.${PARENT}"
CUSTOMER="customer${SUFFIX}.${PARENT}"
WORKER="worker${SUFFIX}.${PARENT}"
RESOLVER="resolver${SUFFIX}.${PARENT}"
WASM="${FES_WASM:-contracts/forecast_jobs/target/wasm32-unknown-unknown/release/forecast_jobs.wasm}"
OUT="${FES_OUT:-docs/evidence/testnet-$(date -u +%Y-%m-%d)${SUFFIX}}"
REWARD_YOCTO="${FES_REWARD_YOCTO:-100000000000000000000000}"      # 0.1 NEAR per job
# Seconds from order creation: decision, delivery, acceptance, dispute deadlines.
read -r T_DECISION T_DELIVERY T_ACCEPTANCE T_DISPUTE <<<"${FES_TIMERS:-120 480 780 1380}"
# Initial balances. The escrow account stakes ~3.1 NEAR for its 301 KiB of code and attaches
# its fixed 1 NEAR reserve to `new`; rewards and gas come from the other accounts.
FUND_ESCROW="4.5 NEAR"; FUND_CUSTOMER="1 NEAR"; FUND_WORKER="0.5 NEAR"; FUND_RESOLVER="0.3 NEAR"
WORKER_KEY_ALLOWANCE="0.25 NEAR"

CHAIN=(python3 -m forecast_swarm.chain)
LOG="$OUT/run-log.json"

say() { printf '\n== %s\n' "$*"; }
# Print a command; run it unless this is a dry run.
run() {
  printf '+'; printf ' %q' "$@"; printf '\n'
  if [[ "$DRY_RUN" != true ]]; then "$@"; fi
}
exists() {  # account exists on testnet? (read-only RPC)
  python3 - "$1" <<'PY'
import sys
from forecast_swarm.near_rpc import NearRpc, RpcError
try:
    NearRpc().view_account(sys.argv[1])
except RpcError as exc:
    sys.exit(1 if "UNKNOWN_ACCOUNT" in str(exc) or "does not exist" in str(exc) else 3)
PY
}
create_account() {  # name, initial balance
  if [[ "$DRY_RUN" != true ]] && exists "$1"; then
    echo "account $1 already exists; reusing it"
    return
  fi
  run near account create-account fund-myself "$1" "$2" \
    autogenerate-new-keypair --signature-scheme ed25519 save-to-keychain \
    sign-as "$PARENT" network-config "$NETWORK" sign-with-keychain send
}
chain() {  # chain.py subcommand with the shared flags; executes unless dry run
  local sub="$1"; shift
  if [[ "$DRY_RUN" == true ]]; then
    printf '+'; printf ' %q' "${CHAIN[@]}" "$sub" --contract "$ESCROW" --log "$LOG" --execute "$@"; printf '\n'
  else
    "${CHAIN[@]}" "$sub" --contract "$ESCROW" --log "$LOG" --execute "$@"
  fi
}
create_job() {  # case file -> prints the new chain job id on the last line
  if [[ "$DRY_RUN" == true ]]; then
    chain create-job --customer "$CUSTOMER" --case "$1" --reward-yocto "$REWARD_YOCTO" >&2
    echo "$2"
    return
  fi
  local output
  output="$(chain create-job --customer "$CUSTOMER" --case "$1" --reward-yocto "$REWARD_YOCTO")"
  echo "$output" >&2
  echo "$output" | awk '/^job id:/ {print $3}' | tail -1
}

say "Plan"
cat <<EOF
network            $NETWORK
parent (pays)      $PARENT
escrow contract    $ESCROW      (funded with $FUND_ESCROW)
customer           $CUSTOMER    ($FUND_CUSTOMER)
worker agent       $WORKER      ($FUND_WORKER; restricted key allowance $WORKER_KEY_ALLOWANCE)
resolver           $RESOLVER    ($FUND_RESOLVER)
planned spend      about 6.4 testnet NEAR moved from the parent to its own sub-accounts
reward per job     $REWARD_YOCTO yoctoNEAR (+ the contract's fixed per-job storage deposit)
deadlines          decision +${T_DECISION}s, delivery +${T_DELIVERY}s, acceptance +${T_ACCEPTANCE}s, dispute +${T_DISPUTE}s
evidence           $OUT/
mode               $([[ "$DRY_RUN" == true ]] && echo "DRY RUN: nothing is sent" || echo "LIVE on testnet")
EOF

if [[ "$DRY_RUN" != true ]]; then
  say "Preflight"
  command -v near >/dev/null || { echo "near-cli-rs (near) is not installed" >&2; exit 2; }
  [[ -f "$WASM" ]] || { echo "Contract wasm not found at $WASM; build it first (docs/NEAR_CONTRACT.md)" >&2; exit 2; }
  [[ ! -e "$LOG" ]] || { echo "$LOG already exists; set FES_OUT or FES_RUN for a new run" >&2; exit 2; }
  python3 - "$PARENT" <<'PY'
import sys
from forecast_swarm.near_rpc import NearRpc
balance = int(NearRpc().view_account(sys.argv[1])["amount"])
print(f"parent balance: {balance / 10**24:.4f} testnet NEAR")
if balance < 65 * 10**23:
    sys.exit("Parent needs at least 6.5 testnet NEAR for a fresh run")
PY
  mkdir -p "$OUT/orders" "$OUT/deliveries"
fi

say "Setup: one account per role"
create_account "$ESCROW" "$FUND_ESCROW"
create_account "$CUSTOMER" "$FUND_CUSTOMER"
create_account "$WORKER" "$FUND_WORKER"
create_account "$RESOLVER" "$FUND_RESOLVER"

say "Setup: deploy and initialise in one transaction"
if [[ "$DRY_RUN" != true ]] && "${CHAIN[@]}" deployment --contract "$ESCROW" --wasm "$WASM" >/dev/null 2>&1; then
  echo "contract code already deployed on $ESCROW; skipping deployment"
else
  run near contract deploy "$ESCROW" use-file "$WASM" \
    with-init-call new json-args "{\"resolver\":\"$RESOLVER\"}" \
    prepaid-gas '30 Tgas' attached-deposit '1 NEAR' \
    network-config "$NETWORK" sign-with-keychain send
fi
run "${CHAIN[@]}" deployment --contract "$ESCROW" --wasm "$WASM" --out "$OUT/deployment.json"

say "Setup: the worker agent's restricted key (this contract, submit and dispute only)"
has_agent_key() {
  python3 - "$WORKER" "$ESCROW" <<'PY'
import sys
from forecast_swarm.near_rpc import NearRpc
keys = NearRpc().view_access_keys(sys.argv[1])["keys"]
for key in keys:
    grant = key["access_key"]["permission"]
    if isinstance(grant, dict) and grant.get("FunctionCall", {}).get("receiver_id") == sys.argv[2]:
        sys.exit(0)
sys.exit(1)
PY
}
if [[ "$DRY_RUN" != true ]] && has_agent_key; then
  echo "worker already has a function-call key for $ESCROW; reusing it"
else
  run near account add-key "$WORKER" grant-function-call-access \
    --allowance "$WORKER_KEY_ALLOWANCE" --contract-account-id "$ESCROW" --function-names 'submit,dispute' \
    autogenerate-new-keypair --signature-scheme ed25519 save-to-legacy-keychain \
    network-config "$NETWORK" sign-with-keychain send
fi

say "Orders: three synthetic orders with fresh deadlines; each job binds its order hash"
JOBS=()
for name in a b c; do
  run "${CHAIN[@]}" order --job-ref "fes-testnet-$name" --out "$OUT/orders/$name.json" \
    --decision-in "$T_DECISION" --delivery-in "$T_DELIVERY" \
    --acceptance-in "$T_ACCEPTANCE" --dispute-in "$T_DISPUTE"
  job="$(create_job "$OUT/orders/$name.json" "<job-$name>")"
  if [[ "$DRY_RUN" != true && ! "$job" =~ ^[0-9]+$ ]]; then
    echo "Could not create the job for order $name; stopping." >&2
    exit 1
  fi
  JOBS+=("$job")
done
JOB_A="${JOBS[0]}"; JOB_B="${JOBS[1]}"; JOB_C="${JOBS[2]}"
for job in "$JOB_A" "$JOB_B" "$JOB_C"; do
  chain assign --customer "$CUSTOMER" --job-id "$job" --worker "$WORKER"
done

say "Worker agent: check each order against the chain, deliver, submit the hash"
chain worker-run --worker "$WORKER" --job-id "$JOB_A" --case "$OUT/orders/a.json" --out "$OUT/deliveries/a.json"
chain worker-run --worker "$WORKER" --job-id "$JOB_B" --case "$OUT/orders/b.json" --out "$OUT/deliveries/b.json"
chain worker-run --worker "$WORKER" --job-id "$JOB_C" --case "$OUT/orders/c.json" --out "$OUT/deliveries/c.json"

say "Job A: customer verifies against the chain, accepts, worker is paid, consent goes on chain"
chain customer-check --customer "$CUSTOMER" --job-id "$JOB_A" --bundle "$OUT/deliveries/a.json"
chain consent --customer "$CUSTOMER" --job-id "$JOB_A"

say "Job C: customer disputes a valid delivery; the resolver applies the verification rule"
chain dispute --account "$CUSTOMER" --job-id "$JOB_C"
chain resolver-check --resolver "$RESOLVER" --job-id "$JOB_C" --bundle "$OUT/deliveries/c.json"

say "Job B: customer stays silent; after the acceptance deadline anyone can trigger the refund"
chain timeout --caller "$PARENT" --job-id "$JOB_B"

say "Evidence"
run "${CHAIN[@]}" snapshot --contract "$ESCROW" --job-ids "$JOB_A,$JOB_B,$JOB_C" \
  --log "$LOG" --out "$OUT/chain-snapshot.json"
run "${CHAIN[@]}" report --cases "$OUT/orders/a.json" "$OUT/orders/b.json" "$OUT/orders/c.json" \
  --out "$OUT/core-report.json"
run python3 -m forecast_swarm.verify --bundle "$OUT/deliveries/a.json" --near-contract "$ESCROW" --job-id "$JOB_A"
run python3 -m forecast_swarm.knowledge_demo --core-report "$OUT/core-report.json" \
  --receipts "$OUT/near-receipts.json" --chain-snapshot "$OUT/chain-snapshot.json" \
  --out artifacts/testnet-knowledge

say "Done"
if [[ "$DRY_RUN" == true ]]; then
  echo "Dry run only: no account was created and no transaction was sent."
else
  echo "Evidence: $OUT/README.md"
  echo "Contract: https://testnet.nearblocks.io/address/$ESCROW"
fi
