#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="${FORECAST_NEAR_CACHE:-/tmp/forecast-near-cargo}"
IMAGE="${FORECAST_RUST_IMAGE:-rust:1.99-slim-bookworm}"

cd "$ROOT"
mkdir -p "$CACHE/cargo" "$CACHE/target" artifacts/demo
RUN_DIR="$(mktemp -d "$ROOT/artifacts/near-sandbox-run.XXXXXX")"
KEEP_RUN_DIR=false
cleanup() {
  if [[ "$KEEP_RUN_DIR" != true ]]; then
    rm -rf -- "$RUN_DIR"
  fi
}
trap cleanup EXIT
RUN_REL="${RUN_DIR#"$ROOT/"}"
RECEIPTS="$RUN_REL/near-receipts.pending.json"
DIAGNOSTICS="$RUN_REL/near-diagnostics.pending.json"
INTEGRATION_OUT="$RUN_DIR/knowledge-demo"

python3 -m forecast_swarm --out artifacts/demo
cargo +1.99.1 build \
  --manifest-path contracts/forecast_jobs/Cargo.toml \
  --target wasm32-unknown-unknown --release --offline

# The runner container sees this repository and a task-local Cargo cache only. It has
# no wallet/config mounts and exposes no host ports. On first use, it resolves Cargo.lock
# from the exact near-workspaces pin; subsequent runs use that lock with --locked.
docker run --rm --network=bridge --cpus=4 --memory=6g --pids-limit=2048 \
  -v "$ROOT:/work" \
  -v "$CACHE/cargo:/cargo-cache" \
  -v "$CACHE/target:/tmp/cargo-target" \
  -w /work/sandbox \
  -e CARGO_HOME=/cargo-cache \
  -e CARGO_TARGET_DIR=/tmp/cargo-target \
  -e FORECAST_CONTRACT_WASM=/work/contracts/forecast_jobs/target/wasm32-unknown-unknown/release/forecast_jobs.wasm \
  -e FORECAST_CORE_REPORT=/work/artifacts/demo/report.json \
  -e FORECAST_SANDBOX_RECEIPTS="/work/$RECEIPTS" \
  -e FORECAST_SANDBOX_DIAGNOSTICS="/work/$DIAGNOSTICS" \
  "$IMAGE" sh -ec '
    if [ ! -f Cargo.lock ]; then cargo generate-lockfile; fi
    cargo test --locked -- --test-threads=1
  '

python3 -m forecast_swarm.knowledge_demo \
  --core-report artifacts/demo/report.json \
  --receipts "$RECEIPTS" \
  --fixture-consent \
  --out "$INTEGRATION_OUT"

mv "$RECEIPTS" "$RUN_REL/near-receipts.json"
mv "$DIAGNOSTICS" "$RUN_REL/near-diagnostics.json"
KEEP_RUN_DIR=true
printf 'Local NEAR receipt: %s/near-receipts.json\n' "$RUN_DIR"
printf 'Integration report: %s/index.html\n' "$INTEGRATION_OUT"
