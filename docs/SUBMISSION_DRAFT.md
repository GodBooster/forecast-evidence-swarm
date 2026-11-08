# NEAR HACKATHON submission draft — Forecast Evidence Swarm

**Status: DRAFT for the owner's review. Nothing has been submitted, pushed or posted.**
Prepared 2026-11-08. One submission per project; corrections after sending go through
`https://nearhackathon.com/request-changes`, so every field below needs the owner's
explicit approval before it is sent.

## Rules check (verified on the live file, 2026-11-08)

Source: `https://nearhackathon.com/HACKATHON.md`, read live by the coordinating Claude Code
session on **2026-11-08** (this machine could not open the site directly earlier that day).
Recheck shortly before submitting in case the organizers change it.

| Topic | Rule |
| --- | --- |
| Deadline | Development and submission close **2026-11-14T23:59:00Z** (Nov 15 01:59 Kyiv). The repository must be **public** by then. |
| Judging | From 2026-11-16; results by 2026-11-18 23:59Z. Claude Code and Codex are used **only for screening** (reproducibility, feature checks, preliminary score); humans decide (Q-017). |
| Prizes | $55K grand prize; $10K / $3K / $2K in each of 13 tracks; paid in one payment within 30 days. |
| How to submit | Form at `https://nearhackathon.com/#apply`, or `POST https://nearhackathon.com/api/applications`. One submission per project; changes via `https://nearhackathon.com/request-changes`. |
| Payload fields (exactly) | `requestId` (UUID, one per submission, reused when retrying after 503); `projectName` 2–80 chars; `leadName` 2–80; `email` ≤ 160 (at most 2 submissions per email); `size` one of `1`, `2 - 4`, `4 - 6`, `6 - 8`, `8+`; `tracks` array of track ids; `nearAddress` mainnet account, 2–64 chars, lowercase; `projectUrl` public repository (each repository only once); `demoUrl` public post on X; `idea` 20–2000 chars; `consent` `true` only after the lead has read verbatim: *"I agree that the organizers may use these details to review our submission and contact us about this hackathon."* |
| Spam trap | Field `website` must be absent or empty; any value rejects the submission. |
| API responses | 201 saved; 400 field error; 403 closed; 409 repository already submitted; 413 body too large; 503 retry with the **same** `requestId`. |
| Track ids | `defi`, `thesis`, `privacy`, `business`, `swarms`, `security`, `agents`, `realworld`, `games`, `nfts`, `memecoins`, `social`, `open`. |
| Prior code (Q-001/Q-005) | Code written from 2026-10-19 is allowed; libraries and AI-written code are allowed and must be listed in the README. This project started 2026-11-06. |
| Two projects (Q-015) | One person may enter up to 2 independent projects; **each README must name the other**. |
| License (Q-014) | Any license; a LICENSE file is required. `LICENSE-MIT` + `LICENSE-APACHE` satisfy it. |
| Demo (Q-012) | A local-only demo is acceptable, but the X post needs a **video**; screenshots alone are not enough. |
| X post | Say it was built at NEAR HACKATHON; tag `@NEARProtocol` and `#NEARHackathon` (optionally `@NearLegion`, `@NearBuilders`); include video. Advice: lead with the user's problem, show one complete action-to-result moment, name NEAR's concrete role, end with the next step and links. |
| Inference credits (Q-000) | $10 of free NEAR AI credits via `https://nearbuilders.org/join`; API key at `https://cloud.near.ai` (OpenAI-compatible). |
| Partner hint, `agents` track | Agent Market (`market.near.ai`, `docs.market.near.ai/list-your-agent`). An opportunity only; nothing is listed there. |

## Project name

Forecast Evidence Swarm

## One-line tagline (≤ 120 characters)

Commission a forecast, verify its evidence, pay via NEAR escrow on acceptance, publish it with immutable history.

## Description / `idea` field (1,892 characters incl. paragraph breaks — within the 20–2000 limit)

> Forecast Evidence Swarm is a marketplace workflow for paid forecasting research that keeps five things separate: whether the evidence was valid, whether the forecast turned out right, whether the customer accepted the work, whether payment happened, and whether the result may be published.
>
> A customer orders a binary forecast with a question, resolution source, decision cutoff, deadlines and budget. Analyst, critic and verifier roles produce a delivery bundle; deterministic gates reject evidence published after the cutoff, missing observations and provisional outcomes. The analyst can be a bounded LLM worker (OpenAI-compatible incl. NEAR AI Cloud, or Anthropic) with one call, a cost ceiling and an output gate: unknown citations or non-numeric output make the delivery invalid. Every call is traced and committed with the bundle as canonical JSON and SHA-256.
>
> A NEAR escrow contract (near-sdk 5.17) holds the reward. The worker submits the hash; the customer accepts that exact hash, or disputes it to a named resolver; deadlines refund silent or abandoned jobs. Payouts and refunds are asynchronous transfers with callbacks; a failed transfer keeps its original beneficiary and can be retried by anyone.
>
> Only a valid, paid delivery with hash-bound consent becomes a public encyclopedia page. Pages are append-only and hash-linked, so a 75% forecast that resolved NO stays visible as 75%.
>
> Verified: 79 + 30 Python tests, 8 contract unit tests, and two integration tests on a local NEAR Sandbox that check exact balances for payout, timeout refund, failed-transfer retry, dispute resolution and cancellation. One command (python3 -m forecast_swarm.walkthrough) runs the whole flow offline.
>
> Honest limits: the LLM worker has one live run so far (3 calls; all passed the gates), data is synthetic, no testnet/mainnet deployment, and no forecasting skill or profitability is claimed.

## Track candidates

Track ids verified on the live file. Select only tracks the project fits.

| Track | Fit | Reasoning |
| --- | --- | --- |
| **Agent Economy** (`agents`) — recommended | Good | The track asks for agents that hire other agents, check work and pay out with a receipt for every task. We implement the hire → check → accept → pay/refund loop with exact-balance chain tests and receipts bound to the work hash. The worker can be a real, budget-bounded LLM agent whose every call is traced inside the paid artifact and whose bad output is refused before payment; one live run (3 calls) passed. Caveats: a single small live run, the worker holds no wallet of its own, and the chain run used scripted deliveries. Possible extra: list the worker on Agent Market (`market.near.ai`) — **not done**. |
| **Open Innovation** (`open`) — recommended | Good | Combinable with other tracks. Immutable, consent-gated forecast history tied to on-chain payment is not a standard category. |
| Private AI (`privacy`) — conditional, **do not select now** | Not yet | Covers private AI, TEE and NEAR AI Cloud. The only live run went through the OpenAI API, with no TEE and no attestation. Revisit only if a run goes through NEAR AI Cloud **and** an attestation is actually obtained and recorded. |
| AI Swarms (`swarms`) — not recommended | Weak | The track is about many agents coordinating in a market (bidding, pooling, intent settlement). We have one LLM role in a fixed three-role pipeline; critic and verifier stay deterministic on purpose. Selecting it would likely read as overclaiming. |
| `thesis`, `security`, `defi`, `business`, `realworld`, others | Not a fit | Thesis requires on-chain NEAR analytics; security review is the domain of the owner's separate BUMM Guard project — keep the boundary. |

## Prior-work disclosure (proposed text)

> This project was started for NEAR HACKATHON on 2026-11-06 (after the 2026-10-19 cutoff for allowed code); the Git history shows its progression. The ideas — timestamped forecast journals, outcome finality, deterministic replay and fixed evaluation rules — come from the author's earlier private prediction-market research (InvariFi). That research is background only: none of its code, strategies, parameters or data is included, and it is not evidence of forecasting accuracy or profitability. The author's second, independent hackathon project is BUMM Guard (security review of NEAR contract code), in its own repository; the two share no source code, and design lessons from reviewing BUMM Guard's escrow pattern are in docs/NEAR_REUSE.md. Code was written with AI coding agents (OpenAI Codex and Anthropic Claude Code) under the author's direction. Third-party libraries: near-sdk, near-workspaces, near-sandbox and other Rust crates (MIT or Apache-2.0); the Python code uses only the standard library; the optional live analyst calls an external model API. License: MIT OR Apache-2.0 (LICENSE-MIT, LICENSE-APACHE).

## Demo assets

- Judge-facing steps: README "Try it in 30 seconds" and `DEMO.md` (paths A–D).
- **A video is required for the X post** (Q-012); screenshots alone are not enough. Suggested
  60–90 s screen recording: run `python3 -m forecast_swarm.walkthrough --roles llm --replay
  fixtures/llm_cassettes/hand_authored_analyst.json` (or the scripted default), scroll the
  five steps, open `core/report.html` (analyst card, output gate, inference trace) and the
  encyclopedia claim showing v1 72%/75% preserved next to the NO outcome. If the live run is
  shown, say it was one run on synthetic data. Optionally show the sandbox test output
  from `DEMO.md` path C. Any media in the repository must be labelled synthetic.

## Submission payload draft (owner fills ★ fields; never sent by an agent without approval)

| Field | Proposed value |
| --- | --- |
| `requestId` | generate one UUID at send time; reuse it only to retry after 503 |
| `projectName` | `Forecast Evidence Swarm` |
| `leadName` | ★ owner |
| `email` | ★ owner (counts toward the 2-submissions-per-email limit, shared with BUMM Guard) |
| `size` | ★ probably `1` |
| `tracks` | `["agents", "open"]` |
| `nearAddress` | ★ owner's mainnet account (lowercase; not created by any agent) |
| `projectUrl` | `https://github.com/GodBooster/forecast-evidence-swarm` once public |
| `demoUrl` | ★ URL of the owner's X post |
| `idea` | the Description above (1,892 characters) |
| `consent` | `true` only after the owner reads the consent sentence verbatim |
| `website` | omit (spam trap) |

## X post draft (owner edits and publishes personally)

> Paying for a forecast usually means trusting a black box: was the data even available at the time, and will the page quietly change after the event?
>
> Built at #NEARHackathon: Forecast Evidence Swarm. Order a forecast → an AI analyst works inside hard evidence gates → the customer accepts the exact delivery hash → a @NEARProtocol escrow contract pays out (or refunds at the deadline) → the result becomes a public page whose original forecast can never be rewritten.
>
> In the video: one order end to end, a delivery rejected for using data published after the cutoff, and a 72% forecast kept visible after it resolved NO. Synthetic data; contract tested on a local NEAR Sandbox.
>
> Code + one-command demo: <repo URL>

The draft is longer than 280 characters: post it as a thread (paragraph 1–2 first, with
the video) unless the account allows long posts. Attach the video. Optional tags:
@NearLegion @NearBuilders. Add the BUMM Guard repository link to the README once its URL
is final. Do not claim forecasting skill,
mainnet deployment or TEE privacy.

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

- [x] Live HACKATHON.md read on 2026-11-08 (by the coordinating session); facts above. Recheck once just before sending.
- [x] ★ License chosen: `MIT OR Apache-2.0`; LICENSE files present and named in the README (optionally put the owner's name in `LICENSE-MIT`).
- [x] README discloses prior work, the other project (BUMM Guard), AI coding agents and libraries.
- [ ] ★ In the **BUMM Guard** repository: make its README name Forecast Evidence Swarm as the owner's other project (Q-015). Not done; not in this repository's scope.
- [ ] ★ Decide whether internal handoff files (`docs/HANDOFF.md`, `docs/CLAUDE_CODE_START.md`, `forecast_encyclopedia/CLAUDE_HANDOFF.md`, `CLAUDE.md`, `AGENTS.md`) stay public; three of them contain local absolute paths.
- [ ] ★ Approve the push of local `main` to `GodBooster/forecast-evidence-swarm` and make it **public before 2026-11-14T23:59Z**.
- [ ] ★ Provide the mainnet NEAR account for the prize payout (not created by any agent).
- [ ] ★ Record a **video** and publish the X post (built at NEAR HACKATHON, `@NEARProtocol`, `#NEARHackathon`).
- [ ] ★ Approve tracks (`agents`, `open`), the `idea` text and the disclosure text.
- [x] Bounded AI worker implemented and tested offline (`--roles llm`, docs/AI_WORKER.md).
- [x] ★ Live run approved and done 2026-11-08: OpenAI `gpt-6.1-terra`, $1 ceiling, ≈$0.004656 estimated (docs/VALIDATION.md). Check the actual charge in the provider's billing page; consider rotating that key.
- [ ] ★ Optional: a second live run through NEAR AI Cloud (OpenAI-compatible) using the free $10 credits (`https://nearbuilders.org/join`, key at `https://cloud.near.ai`). Needs new explicit approval and limit; `privacy` stays unselected unless an attestation is actually obtained.
- [ ] ★ Optional: list the worker on Agent Market (`market.near.ai`) — an opportunity for `agents`, not done.
- [ ] ★ Decide whether a recorded live cassette (model text over synthetic inputs) may be committed publicly.
- [ ] Re-run all tests and `bash sandbox/run.sh` on the final commit.
- [ ] ★ Review the full payload (table above, with a fresh `requestId` and an empty `website`) and send it personally, or approve an agent sending exactly that payload.
