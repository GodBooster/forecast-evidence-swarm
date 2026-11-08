"""Escaped static pages and an exclusive, revocable public export directory."""
import copy
import json
import re
from html import escape
from pathlib import Path
from .model import validate_record, permission, accuracy, load_json

NOTICE = "OFFLINE · SYNTHETIC · TEMPLATE-GENERATED"
MANIFEST = ".encyclopedia-export.json"
FILE = re.compile(r"(?:index\.(?:html|json)|claim-[0-9a-f]{64}(?:-v[1-9][0-9]*)?\.(?:html|json))")


def txt(v):
    return escape(str(v), quote=True)


LLM_NOTICE = "Scripted examples and supplied excerpts; forecasts whose method names an LLM analyst are model output produced inside deterministic evidence and output gates, a judgement rather than verified fact."


def is_llm(snapshot):
    return snapshot["forecast"]["method"].startswith("LLM analyst (")


def shell(title, body, llm=False):
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>{txt(title)} · Forecast Encyclopedia</title><style>
:root{{color-scheme:light}}*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f0;color:#20372e;font:16px/1.65 system-ui,sans-serif}}main{{max-width:1040px;margin:auto;padding:36px 24px}}a{{color:#146354;text-underline-offset:3px}}h1{{font-size:clamp(29px,4vw,44px);line-height:1.16;max-width:900px}}h2{{font-size:23px}}h3{{font-size:17px}}.eyebrow{{letter-spacing:.1em;font-size:12px;font-weight:700}}.notice{{padding:16px 20px;background:#e2ebda;border-left:4px solid #698447}}article,section.card{{background:white;border:1px solid #d4dfd5;border-radius:12px;padding:24px;margin:22px 0}}.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}.stat{{background:#eef3f0;border-radius:8px;padding:15px;overflow-wrap:anywhere}}.stat strong{{display:block;font-size:20px}}small,.meta{{color:#53665c}}code,pre{{font-size:12px;overflow-wrap:anywhere;white-space:pre-wrap}}details{{border-top:1px solid #d4dfd5;margin-top:16px;padding:14px 0}}summary{{cursor:pointer;font-weight:600}}li{{margin:8px 0}}.source{{border-top:1px solid #d4dfd5;padding:14px 0;overflow-wrap:anywhere}}blockquote{{border-left:3px solid #a7b79f;padding-left:16px;margin-left:0}}footer{{font-size:14px;margin:32px 0}}@media(max-width:600px){{main{{padding:20px 14px}}article,section.card{{padding:17px}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><main><p class="eyebrow">FORECAST EVIDENCE SWARM / ENCYCLOPEDIA</p><div class="notice"><strong>{NOTICE}</strong><br>{(LLM_NOTICE + " ") if llm else "Scripted examples and supplied excerpts. No live AI inference. "}Citation checks do not prove source truth or semantic support.</div>{body}<footer>Own betting market and market feeds: planned. No market price is inferred from a model forecast. No wallets, bets or payment execution.<br>Hashes commit to bytes, not truth, authorship or publication time.</footer></main></body></html>'''


def citations(ids):
    return " ".join(f'<a href="#e-{txt(i)}">[{txt(i)}]</a>' for i in ids)


def page(r, v):
    i, s = r["identity"], v["snapshot"]
    p = s["forecast"]["probability_bps"]
    forecast = "Abstained — insufficient or invalid evidence" if p is None else f"{p / 100:.2f}% YES"
    score = accuracy(s)
    quality = "Not evaluable" if score["status"] == "NOT_EVALUABLE" else ("Correct direction" if score["direction_correct"] else "Incorrect direction — retained")
    o = s["outcome"]
    outcome = o["status"] + (" · " + ("YES" if o["value"] else "NO") if o["value"] is not None else " · unknown")
    sources = []
    for e in s["evidence"]:
        source = txt(e["source"])
        if e["url"]:
            source = f'<a rel="noreferrer noopener" href="{txt(e["url"])}">{source}</a>'
        sources.append(f'<div class="source" id="e-{txt(e["id"])}"><strong>{txt(e["id"])} · synthetic source</strong><p>{source}</p><blockquote>{txt(e["excerpt"])}</blockquote><small>Observed {txt(e["observed_at"])} · Available {txt(e["available_at"])}</small></div>')
    history = "".join(f'<li><a href="{r["id"]}-v{x["number"]}.html">Version {x["number"]} · {txt(x["snapshot"]["as_of"])}</a> — {txt(x["snapshot"]["change_reason"])}</li>' for x in r["versions"])
    previous = f'<p>Revised claim: <a href="{r["previous_claim"]}.html">Earlier question or rules</a>.</p>' if r.get("previous_claim") else ""
    score_detail = "" if score["brier_scaled_1e8"] is None else f'<p>Brier score: {score["brier_scaled_1e8"] / 100000000:.8f}. One example establishes no forecasting skill.</p>'
    body = f'''<nav><a href="index.html">All public claims</a></nav><header><h1>{txt(i['question'])}</h1><p>{txt(i['scope'])}</p><p class="meta">Version {v['number']} · as of {txt(s['as_of'])}. This page describes that historical instant.</p>{previous}</header>
<section class="card"><h2>Forecast and result</h2><div class="grid"><div class="stat">Historical forecast<strong>{txt(forecast)}</strong>{citations(s['forecast']['evidence_ids'])}<br><small>Cutoff {txt(s['forecast']['cutoff'])}</small></div><div class="stat">Claim resolution<strong>{txt(outcome)}</strong>{citations(o['evidence_ids'])}</div><div class="stat">Delivery validity<strong>{txt(s['delivery_validity'])}</strong></div><div class="stat">Customer acceptance · simulation<strong>{txt(s['customer_acceptance'])}</strong></div></div><h3>Later forecast accuracy: {txt(quality)}</h3>{score_detail}<p>A valid delivery can be wrong. Acceptance does not certify accuracy. Proposed or disputed results are never scored as final.</p><p>Method: {txt(s['forecast']['method'])}</p></section>
<section class="card"><h2>Resolution rules</h2><p>{txt(i['resolution_rule'])}</p><p>Specified source: {txt(i['resolution_source'])}<br>Resolution time: {txt(i['resolution_at'])}</p><p>A different question, scope, source, time or rule creates a new linked claim.</p></section>
<section class="card"><h2>Evidence notes</h2>{''.join('<p>' + txt(x['text']) + ' ' + citations(x['evidence_ids']) + '</p>' for x in s['statements']) or '<p>No supported evidence note is supplied.</p>'}<h3>Criticism and uncertainty · supplied commentary</h3><ul>{''.join('<li>' + txt(x) + '</li>' for x in s['criticism'])}</ul><h3>Selected sources and excerpts</h3>{''.join(sources) or '<p>No usable evidence supplied. Unknown does not mean NO.</p>'}</section>
<section class="card"><h2>Version history</h2><ol>{history}</ol><p>Change in this version: {txt(s['change_reason'])}</p><details><summary>Technical commitments and JSON</summary><p>Claim ID: <code>{r['id']}</code></p><p>Version SHA-256: <code>{v['sha256']}</code></p><p>Previous version: <code>{txt(v['previous_sha256'])}</code></p><p>Frozen forecast: <code>{v['forecast_sha256']}</code></p><a href="{r['id']}-v{v['number']}.json">This version JSON</a> · <a href="{r['id']}.json">Complete claim JSON</a></details></section>
<p class="meta">Publication explicitly permitted for the complete history. Revocation removes the current export; previously downloaded copies cannot be recalled.</p>'''
    return shell(i["question"], body, is_llm(s))


def public_records(records):
    seen = set()
    for r in records:
        validate_record(r)
        if r["id"] in seen:
            raise ValueError("Duplicate claim")
        seen.add(r["id"])
    allowed = {r["id"] for r in records if permission(r)}
    result = []
    for original in records:
        if original["id"] not in allowed:
            continue
        r = copy.deepcopy(original)
        # Consent receipts remain local, not public personal metadata.
        r["publication"] = {"allowed": True, "consent": {"by": "local consent receipt withheld", "at": r["publication"]["consent"]["at"], "statement": r["publication"]["consent"]["statement"]}}
        if r.get("previous_claim") not in allowed:
            r.pop("previous_claim", None)
        result.append(r)
    return sorted(result, key=lambda r: r["id"])


def encode(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def build_files(records):
    public = public_records(records)
    files, cards, entries = {}, [], []
    for r in public:
        latest = r["versions"][-1]
        s = latest["snapshot"]
        entries.append({"id": r["id"], "question": r["identity"]["question"], "latest_sha256": latest["sha256"], "as_of": s["as_of"]})
        cards.append(f'<article><p class="eyebrow">{txt(s["outcome"]["status"])} · {txt(s["delivery_validity"])}</p><h2><a href="{r["id"]}.html">{txt(r["identity"]["question"])}</a></h2><p>{txt(r["identity"]["scope"])}</p><small>{len(r["versions"])} version(s) · As of {txt(s["as_of"])}</small></article>')
        files[r["id"] + ".json"] = encode(r)
        files[r["id"] + ".html"] = page(r, latest)
        for v in r["versions"]:
            name = r["id"] + "-v" + str(v["number"])
            files[name + ".html"] = page(r, v)
            files[name + ".json"] = encode({"schema": r["schema"], "claim_id": r["id"], "identity": r["identity"], "version": v})
    files["index.json"] = encode({"schema": "forecast-encyclopedia-index/v1", "claims": entries})
    files["index.html"] = shell("Public claims", '<h1>Questions, evidence,<br>and a history that stays visible.</h1><p>Explore forecasts as they were made, inspect disagreements, and see what eventually resolved.</p><p>Only explicitly permitted claims appear here. Dates are fixed synthetic examples, not a live clock.</p>' + ''.join(cards) + '<p><a href="index.json">Machine-readable index</a></p>', any(is_llm(r["versions"][-1]["snapshot"]) for r in public))
    return files


def export(records, destination):
    """Dedicated exporter-owned folder. Reject symlinks and foreign files before writes."""
    files = build_files(records)
    out = Path(destination).absolute()
    for p in [out, *out.parents]:
        if p.is_symlink():
            raise ValueError("Output path cannot contain symlinks")
    old = set()
    if out.exists():
        children = list(out.iterdir())
        if any(p.is_symlink() or not p.is_file() for p in children):
            raise ValueError("Output contains a symlink or directory")
        if children:
            if not (out / MANIFEST).is_file():
                raise ValueError("Refusing to overwrite a non-export directory")
            manifest = load_json((out / MANIFEST).read_text())
            if type(manifest) is not list or any(type(n) is not str or not FILE.fullmatch(n) for n in manifest):
                raise ValueError("Invalid export manifest")
            old = set(manifest)
            if {p.name for p in children} != old | {MANIFEST}:
                raise ValueError("Foreign or missing files in export directory")
    out.mkdir(parents=True, exist_ok=True)
    # Remove revoked content before writing the replacement index.
    for name in sorted(old - files.keys()):
        (out / name).unlink()
    for name, body in sorted(files.items()):
        (out / name).write_text(body, encoding="utf-8")
    (out / MANIFEST).write_text(encode(sorted(files)), encoding="utf-8")
    return len(files)
