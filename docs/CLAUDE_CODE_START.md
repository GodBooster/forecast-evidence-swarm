# Ready-to-use continuation request for Claude Code

Continue developing Forecast Evidence Swarm for the NEAR hackathon. Communicate
with me in Ukrainian. The repository is:
`/Users/vika-mac/Downloads/InvariFi/forecast-evidence-swarm`.

Read `CLAUDE.md`, `AGENTS.md` and `docs/HANDOFF.md`, then the referenced contract,
sandbox and knowledge-integration specifications. Inspect current Git state before
editing. Preserve existing work and keep this product independent of BUMM Guard.
The encyclopedia is a module of Forecast Evidence Swarm, not a third project.

The offline product is implemented. As of November 8, 2026, 41 swarm/integration,
30 encyclopedia and 8 native contract tests pass. Wasm is built. The sandbox Rust
harness is still uncompiled and unexecuted: the previous Codex environment blocked
Docker dependency setup with an automatic approval account usage limit. Check
current prerequisites and use normal permissions in this environment.

Start with `sandbox/run.sh` and `sandbox/tests/near_sandbox.rs`. Compile and correct
the real integration harness, run it against an ephemeral local NEAR sandbox, and
produce actual payout/refund/failure-recovery evidence. Required milestone: one
customer-accepted job pays the worker; a different submitted job refunds at timeout;
repeat payout/refund is rejected; known failed transfers retain the fixed beneficiary
and can be retried safely; the paid, consented result opens in the encyclopedia.
Check balances, receipts and liabilities, not just state labels. Preserve forecast
commitments and history. Keep real chain provenance separate from simulated credits.

Proceed with authorized local changes, tests and scoped commits. Cost-conscious
subagents are permitted if useful; coordinate file ownership and the shared index.
Do not push, publish, submit to the hackathon, use paid APIs, create owner wallets,
spend real funds or transact on mainnet without my explicit authorization. Use only
synthetic data and ephemeral local test accounts at this step. Never bypass a current
permission denial. No existing forecasting skill/profitability claim is justified.

After verified sandbox success, update commands/validation/docs with actual evidence
and give me a concise Ukrainian report of changes, tests, commits and remaining
limitations. Real AI inference comes afterward, once approved access is available.
