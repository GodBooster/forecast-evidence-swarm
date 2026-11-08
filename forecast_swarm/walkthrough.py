"""One-command product walkthrough: order -> research -> evidence checks ->
acceptance/payment -> permitted encyclopedia page.

Every step prints what to look at and checks the invariant it demonstrates. The
command exits non-zero if any check fails. Only synthetic fixtures are used.
"""

import argparse
import json
import sys
from pathlib import Path

from forecast_encyclopedia.model import load_json
from . import knowledge_demo
from .demo import render_html, run_demo

FOCUS = "valid_wrong"


class WalkthroughError(RuntimeError):
    pass


def _check(condition, message):
    if not condition:
        raise WalkthroughError(message)


def _scenario(report, name):
    return next(item for item in report["scenarios"] if item["scenario"] == name)


def build(out, receipts_path=None):
    """Write all walkthrough outputs under ``out`` and return a summary dict."""
    out = Path(out)
    core_dir = out / "core"
    knowledge_dir = out / "knowledge"
    report = run_demo()
    core_dir.mkdir(parents=True, exist_ok=True)
    (core_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (core_dir / "report.html").write_text(render_html(report), encoding="utf-8")

    receipts = (load_json(Path(receipts_path).read_text(encoding="utf-8"))
                if receipts_path else knowledge_demo.simulation_receipts(report))
    knowledge_demo.validate_receipts(receipts)
    sidecar = knowledge_demo.run(
        knowledge_dir, core_dir / "report.json",
        receipts_path, knowledge_demo.CONSENT_FIXTURE,
    )
    index = load_json((knowledge_dir / "encyclopedia" / "index.json").read_text(encoding="utf-8"))
    public_ids = {claim["id"] for claim in index["claims"]}

    focus = _scenario(report, FOCUS)
    content = focus["delivery"]["content"]
    terms = content["inputs"]["terms"]
    roles = content["roles"]
    focus_hash = focus["delivery"]["sha256"]

    # Step 1-2: order terms and scripted research roles.
    _check(roles["analyst"]["mode"] == roles["critic"]["mode"] == roles["verifier"]["mode"] == "scripted",
           "roles must be labelled scripted")
    # Step 3: evidence checks separate validity from later correctness.
    validity = {item["scenario"]: item["delivery"]["content"]["delivery_validity"] for item in report["scenarios"]}
    _check(validity["future_data"] == "INVALID", "evidence published after the cutoff must be INVALID")
    _check(validity["missing_data"] == "INSUFFICIENT_DATA", "missing evidence must be INSUFFICIENT_DATA")
    _check(validity[FOCUS] == "VALID", "focus delivery must be VALID")
    _check(focus["evaluation"]["forecast_quality"]["direction_correct"] is False,
           "focus forecast is intentionally wrong yet valid")

    # Step 4: payment receipt for the exact delivery hash.
    by_hash = {job["artifact_sha256"]: job for job in receipts["jobs"]}
    paid = by_hash.get(focus_hash)
    _check(paid is not None and paid["status"] == "PAID", "focus delivery must have a PAID receipt")
    paid_public = [entry for entry in sidecar["receipts"] if entry["artifact_sha256"] == focus_hash]
    _check(len(paid_public) == 1, "paid, consented delivery must appear in payment provenance")
    claim_id = paid_public[0]["claim_id"]

    # Step 5: permitted encyclopedia page with preserved history.
    _check(claim_id in public_ids, "paid, consented claim must be listed in the public encyclopedia")
    claim = load_json((knowledge_dir / "encyclopedia" / f"{claim_id}.json").read_text(encoding="utf-8"))
    versions = claim["versions"]
    _check(len(versions) >= 2, "claim must keep its original forecast and the later update")
    _check(versions[0]["snapshot"]["outcome"]["status"] == "UNRESOLVED", "version 1 must preserve the unresolved forecast")
    _check(versions[-1]["snapshot"]["outcome"]["status"] == "FINAL", "latest version must record the final outcome")
    _check(versions[0]["snapshot"]["forecast"] == versions[-1]["snapshot"]["forecast"],
           "the historical forecast must not change after the outcome")
    _check(versions[-1]["previous_sha256"] == versions[-2]["sha256"], "version chain must link by hash")

    # Refunded or invalid deliveries must never be public, whatever consent says.
    refunded = [job for job in receipts["jobs"] if job["status"] == "REFUNDED" and job["artifact_sha256"]]
    public_hashes = {entry["artifact_sha256"] for entry in sidecar["receipts"]}
    for job in refunded:
        _check(job["artifact_sha256"] not in public_hashes, "a refunded delivery was published")

    summary = {
        "schema_version": "forecast-walkthrough/v1",
        "receipt_mode": receipts["mode"],
        "receipt_source": str(receipts_path) if receipts_path else "derived SIMULATION receipts",
        "order": {key: terms[key] for key in ("job_id", "question", "source", "decision_at",
                                              "delivery_deadline", "acceptance_deadline", "budget_credits")},
        "research": {
            "analyst_probability_bps": roles["analyst"]["probability_bps"],
            "critic_status": roles["critic"]["status"],
            "critic_findings": roles["critic"]["findings"],
            "verifier_status": roles["verifier"]["status"],
        },
        "evidence_checks": validity,
        "delivery_sha256": focus_hash,
        "forecast_quality": focus["evaluation"]["forecast_quality"],
        "payment": {"status": paid["status"], "job_id": paid["job_id"], "transaction_ids": paid["transaction_ids"]},
        "refunded_artifacts_kept_private": [job["artifact_sha256"] for job in refunded],
        "public_paid_claims": len(sidecar["receipts"]),
        "encyclopedia": {
            "claim_id": claim_id,
            "page": f"knowledge/encyclopedia/{claim_id}.html",
            "versions": [{"number": v["number"], "sha256": v["sha256"], "as_of": v["snapshot"]["as_of"],
                          "outcome": v["snapshot"]["outcome"]["status"]} for v in versions],
        },
    }
    (out / "walkthrough.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def describe(summary, out):
    out = Path(out).absolute()
    order, research = summary["order"], summary["research"]
    payment = summary["payment"]
    lines = [
        "Forecast Evidence Swarm walkthrough (synthetic fixtures; scripted roles; no LLM, wallet or network).",
        "",
        "1. ORDER  A customer commissions a binary forecast with a source, cutoff, deadlines and budget.",
        f"   job={order['job_id']}  question={order['question']!r}",
        f"   cutoff={order['decision_at']}  delivery<{order['delivery_deadline']}  "
        f"accept<{order['acceptance_deadline']}  budget={order['budget_credits']} synthetic credits",
        "",
        "2. RESEARCH  Analyst, critic and verifier roles (scripted functions, labelled as such).",
        f"   analyst={research['analyst_probability_bps'] / 100:.2f}% YES  critic={research['critic_status']} "
        f"({len(research['critic_findings'])} findings)  verifier={research['verifier_status']}",
        "",
        "3. EVIDENCE CHECKS  Deterministic gates decide delivery validity before anyone is paid.",
    ]
    lines += [f"   {name:<15} {status}" for name, status in summary["evidence_checks"].items()]
    quality = summary["forecast_quality"]
    lines += [
        f"   Focus delivery is VALID but the outcome was NO: direction_correct={quality['direction_correct']}, "
        f"Brier={quality['brier_score_scaled_1e8'] / 1e8:.4f}. Validity and correctness stay separate.",
        f"   delivery sha256={summary['delivery_sha256']}",
        "",
        f"4. ACCEPTANCE / PAYMENT  receipts: {summary['receipt_mode']} ({summary['receipt_source']})",
        f"   job {payment['job_id']}: {payment['status']} for exactly this delivery hash; "
        f"{len(payment['transaction_ids'])} transaction IDs recorded",
        f"   refunded deliveries kept private: {len(summary['refunded_artifacts_kept_private'])}; "
        f"public paid claims: {summary['public_paid_claims']}",
    ]
    if summary["receipt_mode"] == "SIMULATION":
        lines.append("   SIMULATION receipts are derived from the synthetic ledger; no NEAR transfer occurred.")
    else:
        lines.append("   LOCAL_NEAR_SANDBOX receipts come from an ephemeral local chain; not a public explorer record.")
    enc = summary["encyclopedia"]
    lines += [
        "",
        "5. KNOWLEDGE PAGE  Only a paid, VALID delivery with hash-bound consent becomes public.",
        f"   claim={enc['claim_id']}",
    ]
    lines += [f"   v{v['number']} as_of={v['as_of']} outcome={v['outcome']} sha256={v['sha256'][:16]}…" for v in enc["versions"]]
    lines += [
        "   The 75% forecast in v1 is preserved unchanged after the NO outcome in the latest version.",
        "",
        "All walkthrough checks passed.",
        f"Open: {out / 'core' / 'report.html'}",
        f"Open: {out / enc['page']}",
        f"Summary JSON: {out / 'walkthrough.json'}",
        "Browser preview: python3 -m http.server 8873 --bind 127.0.0.1 --directory artifacts",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the end-to-end synthetic product walkthrough")
    parser.add_argument("--out", type=Path, default=Path("artifacts/walkthrough"))
    parser.add_argument("--receipts", type=Path,
                        help="forecast-near-receipts/v1 JSON, e.g. from sandbox/run.sh; default derives SIMULATION receipts")
    args = parser.parse_args(argv)
    try:
        summary = build(args.out, args.receipts)
    except (WalkthroughError, ValueError) as error:
        print(f"WALKTHROUGH CHECK FAILED: {error}", file=sys.stderr)
        return 1
    print(describe(summary, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
