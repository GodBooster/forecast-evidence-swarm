# NEAR Project Reuse Assessment

This note records a read-only review of the related local NEAR project as of 2026-11-06. It identifies architectural lessons for the future NEAR sandbox milestone; it does not import code or product content. Forecast Evidence Swarm and BUMM Guard remain independent products.

## What was verified locally

The BUMM Guard `main` worktree is at `5228a537` and does not contain the `swarm_jobs` contract or `review-job` command. A separate local worktree, branch `swarm-jobs`, is clean at `08976b0`; its relevant commits are `ca48df9` (contract and scenarios), `396ae87` (review command and docs), and `08976b0` (minimum agent deposit and review budget floor). These are local branch/worktree facts, not evidence of a merge to `main` or a public release.

The branch contains:

- A NEAR escrow contract at `tests/fixtures/near/swarm_jobs/src/lib.rs`. It defines `Open`, `Submitted`, `Rejected`, `Paying`, `Paid`, and `Cancelled` states; role checks for poster, agent, and reviewer; hash-shaped submission fields; and an asynchronous reward transfer.
- A CLI review path at `bumm_guard/review.py`. It reads the on-chain job and reviewer, checks that local wasm/report bytes match submitted hashes, runs the existing deploy gate in dry-run mode, records a review report, and prints an `approve` or `reject` call for the reviewer. It does not sign or send transactions.
- Three NEAR sandbox scenarios at `scenarios/swarm_jobs/` and contract tests in the fixture source. CI builds the wasm, runs the scenarios, and uploads the same wasm used by them (`.github/workflows/ci.yml`). `docs/SWARM_JOBS.md` describes these checks and states that the testnet run is still a plan.

The contract and review flow described in the supplied project note match those source files. The note's claims about successful tests are documented in the branch's CI setup and docs; this assessment did not run tests or independently inspect a CI run. The contract is not testnet-validated according to its own documentation.

## Useful architecture for Forecast Evidence Swarm

The most reusable idea is the separation between local verification and on-chain authorization. A reviewer can inspect exact submitted bytes and a bound report, while retaining a human-controlled signing step. The `Paying` intermediate state and private promise callback also show how an asynchronous payout can become an explicit, recoverable state transition. For Forecast Evidence Swarm's planned NEAR contract, these are useful design prompts: model transfer-in-flight separately, make duplicate release/refund calls fail, and test both transfer success and failure in a local sandbox. The current Python simulator covers synchronous acceptance and refund transitions; it does not yet model asynchronous transfers.

The scenario files also offer a useful testing shape: specify actors, attached deposits, calls, views, balances, and expected failures as a readable sequence. Forecast Evidence Swarm can design its own Python scenario format around its acceptance rules, then later map equivalent cases into `near-workspaces`. No BUMM Guard scenario format or source code is copied here.

## Important limitations to account for

- **Review-payout recovery is partial.** In `tests/fixtures/near/swarm_jobs/src/lib.rs`, `approve` sets `Paying` and schedules a transfer; `on_reward_paid` is `#[private]` and reads promise success. A failed transfer restores `Submitted` and clears the gate report hash, leaving the reward in the contract so review can be retried (around lines 234–280). This is a useful pattern, but a failed or out-of-gas callback could leave the job in `Paying`; the local code has no separate recovery entry point for that condition.
- **Other refunds/withdrawals lack equivalent recovery.** `cancel` marks the job `Cancelled` before returning a transfer promise, and `withdraw_budget` subtracts budget before transfer; neither has a callback to restore state if transfer fails (around lines 166–183 and 299–310). The branch's own `docs/SWARM_JOBS.md` calls out this difference.
- **Submitted jobs can stay locked indefinitely.** The poster may cancel only in `Open` or `Rejected`, while a `Submitted` job waits for the fixed reviewer. There is no review deadline, timeout, alternate reviewer, or permissionless expiry path. Forecast Evidence Swarm's build specification already requires a clear rule for submitted but unaccepted work and says funds must not remain locked by an unspecified timeout. Treat this as a limitation to solve independently, not a behavior to inherit.
- **The reviewer is trusted.** `review-job` performs checks off-chain; the contract does not verify sandbox evidence. The reviewer account can approve without proving the review happened. The report hash makes the decision auditable, not trustless.
- **Customer acceptance is a different product rule.** BUMM Guard's reviewer judges whether submitted contract work passes a security/deploy gate, then the reviewer authorizes payment. Forecast Evidence Swarm's first version should implement explicit customer acceptance under a declared acceptance policy. Forecast correctness and evidence validity must remain separate: a later correct outcome must not release payment for an invalid delivery, and a valid delivery may still forecast incorrectly.

## Product boundary and collaboration value

BUMM Guard's core is NEAR contract safety and deployment gating: static checks, sandbox scenarios, code-hash-bound upgrade proof, and a reviewer-controlled release for contract work. Forecast Evidence Swarm's core is commissioning a forecast with inspectable evidence, timestamp/finality checks, and customer-defined acceptance. The products have adjacent escrow and evidence concepts, but distinct users, evidence meanings, and acceptance authorities.

Mutual value can come from exchanging design reviews or testing ideas: BUMM Guard can contribute lessons about NEAR authorization, sandbox fault cases, and asynchronous transfer recovery; Forecast Evidence Swarm can contribute a clearer customer-facing distinction between evidence/delivery acceptance and eventual forecast accuracy. Any future shared protocol or library should be independently specified, explicitly licensed, and attributed. This assessment reuses no BUMM Guard code, private research, account details, credentials, or deployment instructions.

## Local references

- BUMM Guard branch `swarm-jobs`, commits `ca48df9`, `396ae87`, `08976b0`.
- `tests/fixtures/near/swarm_jobs/src/lib.rs` — contract state machine, permissions, callbacks, cancellation, and budget withdrawal.
- `bumm_guard/review.py` — read-only review inputs and dry-run gate integration; prints but does not execute reviewer calls.
- `scenarios/swarm_jobs/01_review_pays_agent.json`, `02_review_guardrails.json`, and `03_cancel_refunds.json` — local sandbox cases.
- `docs/SWARM_JOBS.md` — project description and documented limitations, including unbounded reviewer wait and unhandled cancel/withdraw transfer failure.
- Forecast Evidence Swarm `docs/BUILD_SPEC.md` — offline simulator requirements, payment-state-machine requirements, and planned NEAR contract sandbox milestone.
