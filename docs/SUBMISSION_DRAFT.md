# NEAR HACKATHON submission draft — Forecast Evidence Swarm

**Status: DRAFT for the owner's review. Nothing has been submitted, pushed or posted.**
Prepared 2026-11-08. One submission per team and it cannot be edited after sending, so
every field below needs the owner's explicit approval.

## Rules check (sources and confidence)

`https://nearhackathon.com/HACKATHON.md` could **not** be read on 2026-11-08: the site
reset every connection from this machine (curl, fetch tool and the embedded browser).
The facts below come from secondary sources and must be rechecked on the live file
before submitting:

| Fact | Source (read 2026-11-08) |
| --- | --- |
| Submissions close **2026-11-14 23:59 UTC** (= Nov 15 01:59 Kyiv); judging Nov 16–18 | README of `github.com/nearai/near-hackathon-prompt-examples` (last commit 2026-10-30); NEAR Protocol post on X |
| 13 tracks; each pays $10K / $3K / $2K; one $55K grand prize; prizes in NEAR | same README |
| Jury includes **Claude Code and Codex as AI judges**; README needs "do X, see Y" steps | same README and its `00-setup.md` |
| Checklist: public repo with "do X, see Y" README; live demo post on X saying it was built at NEAR HACKATHON with video or screenshots; a **mainnet NEAR account** for the payout; select every fitting track; no keys/secrets in Git history; submit before the deadline | `SUBMITTING.md` in the same repo |
| Submission via the form at `nearhackathon.com/#apply` or the submission API in HACKATHON.md; an agent must show the full payload and wait for the human's OK | `SUBMITTING.md` |
| Form asks for project name, team lead, email, team details, … (list truncated in the source) | NEAR Protocol post on X |
| Description length 20–2000 characters | earlier local research note; **not reverified** |
| Existing libraries/products allowed with disclosure; the new work is evaluated | `docs/PRIOR_WORK.md` note from 2026-11-06; **not reverified** |

## Project name

Forecast Evidence Swarm

## One-line tagline (≤ 120 characters)

Commission a forecast, verify its evidence, pay via NEAR escrow on acceptance, publish it with immutable history.

## Description (1,902 characters incl. paragraph breaks — within the assumed 20–2000 limit)

> Forecast Evidence Swarm is a marketplace workflow for paid forecasting research that keeps five things separate: whether the evidence was valid, whether the forecast turned out right, whether the customer accepted the work, whether payment happened, and whether the result may be published.
>
> A customer orders a binary forecast with a question, resolution source, decision cutoff, deadlines and budget. Analyst, critic and verifier roles produce a delivery bundle; deterministic gates reject evidence published after the cutoff, missing observations and provisional outcomes. The analyst can be a bounded LLM worker (OpenAI-compatible incl. NEAR AI Cloud, or Anthropic) with one call, a cost ceiling and an output gate: unknown citations or non-numeric output make the delivery invalid. Every call is traced and committed with the bundle as canonical JSON and SHA-256.
>
> A NEAR escrow contract (near-sdk 5.17) holds the reward. The worker submits the hash; the customer accepts that exact hash, or disputes it to a named resolver; deadlines refund silent or abandoned jobs. Payouts and refunds are asynchronous transfers with callbacks; a failed transfer keeps its original beneficiary and can be retried by anyone.
>
> Only a valid, paid delivery with hash-bound consent becomes a public encyclopedia page. Pages are append-only and hash-linked, so a 75% forecast that resolved NO stays visible as 75%.
>
> Verified: 78 + 30 Python tests, 8 contract unit tests, and two integration tests on a local NEAR Sandbox that check exact balances for payout, timeout refund, failed-transfer retry, dispute resolution and cancellation. One command (python3 -m forecast_swarm.walkthrough) runs the whole flow offline.
>
> Honest limits: the LLM path is tested offline with hand-authored replay data (live run pending), data is synthetic, no testnet/mainnet deployment, and no forecasting skill or profitability is claimed.

## Track candidates

Track ids are from the organizers' prompt-examples repository and must be matched to the
live form. The submission form allows several tracks; select only those the project fits.

| Track | Fit | Reasoning |
| --- | --- | --- |
| **Agent Economy** (`agents`) — recommended | Good, stronger with the AI worker | The track asks for agents that hire other agents, check work and pay out with a receipt for every task. We implement the hire → check → accept → pay/refund loop with exact-balance chain tests and receipts bound to the work hash. The worker can now be a real, budget-bounded LLM agent whose every call is traced inside the paid artifact, and whose bad output is refused before payment. Caveats: no live model run is recorded yet (offline replay uses hand-authored answers), the worker holds no wallet of its own, and the chain run used scripted deliveries. |
| **Open Innovation** (`open`) — recommended | Good | Explicitly combinable with any other track. Immutable, consent-gated forecast history tied to on-chain payment is not a standard category. |
| AI Swarms (`swarms`) — optional, weaker | Still weak | The track is about many agents coordinating in a market (bidding, pooling, intent settlement). The AI worker adds one LLM role to a fixed three-role pipeline; critic and verifier stay deterministic on purpose. That is not a market of agents. Selecting it would likely read as overclaiming. |
| Investment Thesis, AI Security & Defense, others | Not a fit | Thesis requires on-chain NEAR analytics; Security is the domain of the owner's separate BUMM Guard submission — keep the boundary. |

## Prior-work disclosure (proposed text)

> This project was started for NEAR HACKATHON on 2026-11-06; all code in the repository was written during the event and the Git history shows its progression. The ideas — timestamped forecast journals, outcome finality, deterministic replay and fixed evaluation rules — come from the author's earlier private prediction-market research (InvariFi). That research is background only: none of its code, strategies, parameters or data is included, and it is not evidence of forecasting accuracy or profitability. The author also submits a separate, independent project, BUMM Guard (security review of NEAR contract code), in its own repository; the two projects share no source code. Design lessons from reviewing BUMM Guard's escrow pattern are documented in docs/NEAR_REUSE.md. Third-party libraries: near-sdk, near-workspaces, near-sandbox and other Rust crates (MIT or Apache-2.0); the Python code uses only the standard library.

## Demo assets

- Repository README "Try it in 30 seconds" and `DEMO.md` (paths A/B/C) are the judge-facing steps.
- Screenshots or a short video for the X post still need to be captured from
  `python3 -m forecast_swarm.walkthrough` output and the generated HTML pages; any images
  placed in the repository must be labelled synthetic.

## License

**Decided by the owner on 2026-11-08: `MIT OR Apache-2.0`.** `LICENSE-MIT`, `LICENSE-APACHE`
and the Cargo `license` fields were added. The MIT copyright line reads "Forecast Evidence
Swarm authors"; the owner may replace it with their own name. The options considered are
kept below for the record.

### Options considered

Every Rust dependency checked (`near-sdk`, `near-workspaces`, `near-sandbox`, `serde_json`,
`anyhow`, `sha2`) is `MIT OR Apache-2.0` and `tokio` is MIT, so all options below are
compatible with the dependencies.

1. **`MIT OR Apache-2.0` (dual, the Rust/NEAR ecosystem norm)** — recommended for a hackathon.
   - Anyone may use, modify and commercialise the code, including closed-source forks.
   - Apache-2.0 adds an explicit patent grant and patent-retaliation clause; MIT keeps it simple.
   - Matches `near-sdk` and most dependencies, which makes reuse by judges, NEAR teams and
     grant programs frictionless.
   - Consequence: no legal protection against a competitor reusing the escrow/evidence design
     in a proprietary product.

2. **`AGPL-3.0-only`** — strong copyleft.
   - Anyone who modifies it and offers it as a network service must publish their source
     under AGPL; the owner can still dual-license commercially (as sole copyright holder).
   - Protects the work from silent proprietary forks.
   - Consequence: many companies avoid AGPL code, so adoption, contributions and reuse in
     NEAR ecosystem projects may be lower; check whether the hackathon rules require an
     OSI-approved license (AGPL is OSI-approved) before choosing.

Chosen: option 1.

## Pre-submission checklist (owner actions marked ★)

- [ ] ★ Re-read the live HACKATHON.md (dates, tracks, form fields, description limits, rules on prior work and AI-written code).
- [x] ★ License chosen: `MIT OR Apache-2.0`; files and Cargo fields added (optionally put the owner's name in `LICENSE-MIT`).
- [ ] ★ Decide whether internal handoff files (`docs/HANDOFF.md`, `docs/CLAUDE_CODE_START.md`, `forecast_encyclopedia/CLAUDE_HANDOFF.md`, `CLAUDE.md`, `AGENTS.md`) stay public; three of them contain local absolute paths.
- [ ] ★ Approve the push of local `main` to `GodBooster/forecast-evidence-swarm` and the change from private to public visibility.
- [ ] ★ Provide the mainnet NEAR account for the prize payout (not created by any agent).
- [ ] ★ Record and publish the X demo post (video or screenshots; says built at NEAR HACKATHON).
- [ ] ★ Pick tracks and approve the final description and disclosure text.
- [x] Bounded AI worker implemented and tested offline (`--roles llm`, docs/AI_WORKER.md).
- [ ] ★ Choose provider (NEAR AI Cloud / Anthropic / other), model and a spending limit; put the key in a local `.env.local` yourself; approve one live run (results go to docs/VALIDATION.md).
- [ ] ★ Decide whether a recorded live cassette (model text over synthetic inputs) may be committed publicly.
- [ ] Re-run all tests and `bash sandbox/run.sh` on the final commit.
- [ ] ★ Review the full submission payload and send it personally (or approve an agent sending exactly that payload).
