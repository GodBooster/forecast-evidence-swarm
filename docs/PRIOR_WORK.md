# Prior work

This prototype builds on ideas developed in the owner's private InvariFi prediction-market research: timestamped forecast journals, outcome finality, deterministic replay and accounting, fixed evaluation rules, experiment manifests and risk gates.

The private research infrastructure is baseline. Its existence is not evidence of profitable live trading. The new public prototype should use a minimal independent implementation with synthetic fixtures, without private trading logic or production data.

Repository creation date: 2026-11-06. Initial commit contains project documentation only. Implementation commits will identify the new features. Do not backdate commits or present imported work as newly written.

Offline milestone, implemented in this repository: independent Python scripted roles,
synthetic fixtures, strict timestamp/finality checks, canonical delivery commitments,
HTML/JSON reporting, synchronous budget simulation and tests. No private InvariFi or
BUMM source was copied. The related BUMM Guard `swarm-jobs` branch was reviewed for
future NEAR design lessons; see [reuse assessment](NEAR_REUSE.md). That existing
contract and review tooling remain prior work, not newly implemented capabilities
of Forecast Evidence Swarm.

License: `MIT OR Apache-2.0` (chosen 2026-11-08). Rust dependencies checked (`near-sdk`, `near-workspaces`, `near-sandbox`, `serde_json`, `anyhow`, `sha2`) are `MIT OR Apache-2.0`; `tokio` is MIT; Python uses only the standard library. Disclose the owner's related BUMM project in both READMEs if both are submitted; describe shared components and demonstrate independent products.

Rules checked on 2026-11-06: https://nearhackathon.com/HACKATHON.md. Existing libraries and products are permitted with disclosure; the new NEAR integration is evaluated. Recheck the live rules before submission.
