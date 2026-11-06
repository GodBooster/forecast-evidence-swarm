# Forecast Evidence Swarm

A NEAR hackathon prototype for commissioning forecasts with evidence, criticism and reproducible validation.

**Status: project scaffold.** No runnable demo or deployed contract yet. Forecast quality and trading profitability have not been established.

A customer defines a question, resolution source, deadline and budget. Analyst, critic and verifier roles produce a forecast and evidence bundle. Deterministic checks evaluate data timing, completeness and acceptance rules. A planned NEAR contract records the job, budget and artifact commitment; the customer accepts delivery.

## First milestone

Build an offline end-to-end demo with synthetic fixtures: submit a question, run three scripted roles, accept valid evidence, reject invalid evidence and generate a report. See [build specification](docs/BUILD_SPEC.md).

## NEAR integration

Planned: a contract for bounded job budgets, deadlines, submission, customer acceptance, refunds and protection against duplicate payout. Offline simulation is not evidence of an onchain deployment. Each integration will be labelled implemented, simulated or planned.

## Prior work and disclosure

See [prior work](docs/PRIOR_WORK.md). The baseline predates this repository; only new features and integration are presented as hackathon work. Related project: BUMM, an independently developed security project; its public link and exact overlap must be confirmed before submission.

## License

License selection is pending. A LICENSE file must be added before publication or submission.
