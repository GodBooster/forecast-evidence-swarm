"""One offline command: synthetic inputs -> scripted roles -> JSON and HTML."""

import argparse
import json
from html import escape
from pathlib import Path

from . import SCHEMA_VERSION
from .evidence import build_bundle, quality
from .payments import JobSimulator, TransitionError


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic_cases.json"


def simulate(case, bundle):
    terms = case["terms"]
    now = terms["decision_at"]
    job = JobSimulator(terms, "customer", "resolver", now)
    job.assign("customer", "worker", now)
    rejection = None
    try:
        job.submit("worker", bundle, now)
    except TransitionError as exc:
        rejection = str(exc)
        job.timeout("any-observer", terms["delivery_deadline"])
    else:
        if case["scenario"] != "unresolved":
            # Explicit synthetic customer action, never a vote or quality verdict.
            job.accept("customer", now)
    snapshot = job.snapshot()
    return {"status": "AWAITING_CUSTOMER" if snapshot["state"] == "SUBMITTED" else snapshot["state"],
            "submission_rejection": rejection, "ledger": snapshot}


def run_demo():
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        bundle = build_bundle(case)
        results.append({"scenario": case["scenario"], "title": case["title"], "delivery": bundle,
                        "evaluation": {"as_of": case["evaluation_at"], "outcome": case["outcome"],
                                       "forecast_quality": quality(case, bundle["content"]["roles"]["analyst"])},
                        "customer_acceptance": simulate(case, bundle)})
    return {"schema_version": SCHEMA_VERSION, "mode": "OFFLINE_SYNTHETIC_SIMULATION",
            "notice": "All three roles are scripted. Credits are simulated. No network, LLM, wallet or NEAR contract is used. Forecast skill is not established.",
            "commitment_notice": "Delivery commitments exclude later outcomes, evaluation and payment history. A hash commits to bytes, not their truth.",
            "scenarios": results}


def text(value):
    return escape("unknown" if value is None else str(value), quote=True)


def render_html(report):
    cards, summary = [], []
    for result in report["scenarios"]:
        content = result["delivery"]["content"]
        inputs, roles = content["inputs"], content["roles"]
        terms = inputs["terms"]
        score = result["evaluation"]["forecast_quality"]
        acceptance = result["customer_acceptance"]
        ledger = acceptance["ledger"]
        probability = roles["analyst"]["probability_bps"]
        percent = "Abstained" if probability is None else f"{probability / 100:.2f}% YES"
        evaluated = score["status"]
        if score["direction_correct"] is not None:
            evaluated += " / " + ("correct direction" if score["direction_correct"] else "incorrect direction")
        name = text(result["scenario"])
        summary.append(f'<tr><td><a href="#{name}">{text(result["title"])}</a></td><td>{text(percent)}</td><td>{text(content["delivery_validity"])}</td><td>{text(evaluated)}</td><td>{text(acceptance["status"])}</td></tr>')
        evidence_rows = "".join(
            "<tr>" + "".join(f"<td>{text(item[key])}</td>" for key in
                             ("id", "source", "observed_at", "available_at", "yes_count", "sample_count")) + "</tr>"
            for item in inputs["evidence"])
        reasons = roles["verifier"]["reasons"] or ["All evidence passes the declared delivery checks."]
        role_cards = f'''<div class="role"><h3>Analyst <span>scripted</span></h3><strong>{text(percent)}</strong><p>{text(roles["analyst"]["method"])}</p></div>
<div class="role"><h3>Critic <span>scripted</span></h3><ul>{''.join('<li>' + text(v) + '</li>' for v in roles['critic']['findings'])}</ul></div>
<div class="role"><h3>Verifier <span>scripted</span></h3><strong>{text(content['delivery_validity'])}</strong><ul>{''.join('<li>' + text(v) + '</li>' for v in reasons)}</ul></div>'''
        trace = "".join(f'<li><time>{text(event["at"])}</time> · {text(event["actor"])}: {text(event["action"])} → <b>{text(event["state"])}</b></li>' for event in ledger["events"])
        brier = score["brier_score_scaled_1e8"]
        brier_display = "not evaluable" if brier is None else f"{brier / 100000000:.8f}"
        outcome = result["evaluation"]["outcome"]
        outcome_display = json.dumps(outcome, sort_keys=True, ensure_ascii=False)
        cards.append(f'''<article id="{name}"><p class="eyebrow">{text(terms['job_id'])} · synthetic fixture</p><h2>{text(result['title'])}</h2>
<p>{text(terms['question'])}</p><p class="meta">Decision cutoff: {text(terms['decision_at'])} · Delivery before: {text(terms['delivery_deadline'])}<br>Resolution at: {text(terms['resolution_at'])} · Source: {text(terms['source'])}</p>
<div class="roles">{role_cards}</div>
<h3>Evidence available at decision time</h3><div class="scroll"><table><thead><tr><th>ID</th><th>Source</th><th>Observed (UTC)</th><th>Available (UTC)</th><th>YES count</th><th>Sample count</th></tr></thead><tbody>{evidence_rows}</tbody></table></div>
<div class="split"><section><h3>Later forecast quality</h3><strong>{text(evaluated)}</strong><p>Brier score: {text(brier_display)} (lower is better; one synthetic example proves no skill).</p><p>Evaluated as of {text(result['evaluation']['as_of'])}.</p><p>{text('; '.join(score['reasons']))}</p><details><summary>Outcome record</summary><pre>{text(outcome_display)}</pre></details></section>
<section><h3>Customer acceptance · SIMULATION</h3><strong>{text(acceptance['status'])}</strong><p>Budget: {ledger['budget']} synthetic credits · Held: {ledger['escrow']} · Paid: {ledger['paid_to_worker']} · Refunded: {ledger['refunded_to_customer']}</p><p>{text(acceptance['submission_rejection'] or 'Only an explicit customer action releases payment; quality scoring does not.')}</p><p>Unaccepted work refunds at {text(terms['acceptance_deadline'])} when timeout is invoked. Disputed work refunds at {text(terms['dispute_deadline'])} if unresolved.</p></section></div>
<details><summary>Simulated job events</summary><ol>{trace}</ol></details>
<details><summary>Stable commitments (SHA-256)</summary><p>Delivery bundle</p><code>{text(result['delivery']['sha256'])}</code><p>Canonical evidence</p><code>{text(content['evidence_sha256'])}</code></details></article>''')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Forecast Evidence Swarm · Offline demo</title><style>
:root{{color-scheme:light;--ink:#163047;--muted:#4b6073;--line:#cbd8df;--paper:#fff;--accent:#085e60}}*{{box-sizing:border-box}}body{{margin:0;background:#edf3f5;color:var(--ink);font:16px/1.6 system-ui,sans-serif}}main{{max-width:1180px;margin:auto;padding:40px 24px}}h1{{font-size:clamp(30px,5vw,46px);line-height:1.12;margin:12px 0}}h2{{font-size:27px;line-height:1.25}}h3{{font-size:17px}}a{{color:var(--accent)}}.eyebrow{{text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:700;color:var(--accent)}}.notice{{border-left:4px solid var(--accent);background:#dceeed;padding:16px 20px;margin:24px 0}}article,.overview{{padding:28px;background:var(--paper);border:1px solid var(--line);border-radius:12px;margin:24px 0}}.meta{{color:var(--muted);font-size:14px}}.roles{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:24px 0}}.role{{padding:16px;background:#f1f6f7;border-radius:8px;min-width:0}}.role h3{{margin-top:0}}.role span{{display:inline-block;font-size:11px;letter-spacing:.04em;padding:2px 6px;background:#d9e7eb;border-radius:4px}}ul,ol{{padding-left:20px}}.role li{{font-size:14px;margin:8px 0}}.split{{display:grid;grid-template-columns:1fr 1fr;gap:28px}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{text-align:left;vertical-align:top;padding:12px 10px;border-bottom:1px solid var(--line)}}th{{background:#f1f6f7}}td{{overflow-wrap:anywhere}}.scroll{{overflow-x:auto}}code,pre{{font-size:12px;overflow-wrap:anywhere;white-space:pre-wrap}}details{{border-top:1px solid var(--line);padding:13px 0;margin-top:12px}}summary{{cursor:pointer;font-weight:600}}time{{font-size:12px}}footer{{font-size:14px;color:var(--muted)}}@media(max-width:760px){{main{{padding:22px 12px}}article,.overview{{padding:18px}}.roles,.split{{grid-template-columns:1fr}}table{{min-width:650px}}}}@media print{{body{{background:white}}article{{break-inside:avoid}}details{{display:block}}}}
</style></head><body><main><header><p class="eyebrow">Forecast Evidence Swarm / milestone 1</p><h1>A forecast with evidence you can inspect.</h1><p>Five deterministic examples. Three scripted roles. Delivery, forecast quality and acceptance shown separately.</p></header>
<div class="notice"><strong>OFFLINE · SYNTHETIC · SIMULATION</strong><p>{text(report['notice'])}</p><p>{text(report['commitment_notice'])}</p></div>
<section class="overview"><h2>Scenario overview</h2><div class="scroll"><table><thead><tr><th>Scenario</th><th>Forecast</th><th>Delivery validity</th><th>Forecast quality</th><th>Customer acceptance</th></tr></thead><tbody>{''.join(summary)}</tbody></table></div></section>
{''.join(cards)}<footer><p>Version: {text(report['schema_version'])}. All dates are explicit synthetic UTC fixtures. No runtime clock enters committed output.</p><p>NEAR contract, asynchronous transfers, LLM agents and authenticated integrations are planned. A valid delivery is not evidence of accuracy or profitability.</p><p><a href="report.json">Open machine-readable report.json</a></p></footer></main></body></html>
'''


def main():
    parser = argparse.ArgumentParser(description="Run the offline synthetic Forecast Evidence Swarm demo")
    parser.add_argument("--out", type=Path, default=Path("artifacts/demo"), help="output directory (default: artifacts/demo)")
    args = parser.parse_args()
    report = run_demo()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.out / "report.html").write_text(render_html(report), encoding="utf-8")
    print(report["notice"])
    for result in report["scenarios"]:
        print(f"{result['scenario']}: delivery={result['delivery']['content']['delivery_validity']}; "
              f"quality={result['evaluation']['forecast_quality']['status']}; acceptance={result['customer_acceptance']['status']}")
    print(f"HTML: {(args.out / 'report.html').resolve()}")
    print(f"JSON: {(args.out / 'report.json').resolve()}")


if __name__ == "__main__":
    main()
