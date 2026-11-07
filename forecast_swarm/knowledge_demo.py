"""Offline core-to-encyclopedia demonstration with explicit consent gating."""

import argparse
import json
import re
from pathlib import Path

from forecast_encyclopedia.adapter import adapt_report
from forecast_encyclopedia.demo import load_demo
from forecast_encyclopedia.model import load_json, permission
from forecast_encyclopedia.render import export
from .demo import run_demo


ROOT = Path(__file__).resolve().parent.parent
CONSENT_FIXTURE = ROOT / "fixtures_encyclopedia" / "core_demo_consent.json"
RECEIPT_SCHEMA = "forecast-near-receipts/v1"
MANIFEST = ".knowledge-demo-manifest.json"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _nonempty(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")


def simulation_receipts(report):
    """Derive clearly simulated receipts from the deterministic core ledger."""
    jobs = []
    for result in report["scenarios"]:
        acceptance = result["customer_acceptance"]
        ledger = acceptance["ledger"]
        if ledger["paid_to_worker"]:
            status = "PAID"
        elif ledger["refunded_to_customer"]:
            status = "REFUNDED"
        else:
            continue
        jobs.append({
            "job_id": result["delivery"]["content"]["inputs"]["terms"]["job_id"],
            "artifact_sha256": result["delivery"]["sha256"],
            "customer": ledger["customer"], "worker": ledger["worker"],
            "status": status, "transaction_ids": [],
        })
    return {"schema_version": RECEIPT_SCHEMA, "mode": "SIMULATION", "jobs": jobs}


def validate_receipts(receipts):
    if type(receipts) is not dict or set(receipts) != {"schema_version", "mode", "jobs"}:
        raise ValueError("Receipt document has unexpected or missing fields")
    if receipts["schema_version"] != RECEIPT_SCHEMA or receipts["mode"] not in ("SIMULATION", "LOCAL_NEAR_SANDBOX"):
        raise ValueError("Unsupported payment receipt schema or mode")
    if type(receipts["jobs"]) is not list:
        raise ValueError("Receipt jobs must be a list")
    seen_jobs, seen_hashes = set(), set()
    for receipt in receipts["jobs"]:
        required = {"job_id", "artifact_sha256", "customer", "worker", "status", "transaction_ids"}
        if type(receipt) is not dict or set(receipt) != required:
            raise ValueError("Receipt has unexpected or missing fields")
        _nonempty(receipt["job_id"], "receipt job_id")
        _nonempty(receipt["customer"], "receipt customer")
        if receipt["worker"] is not None:
            _nonempty(receipt["worker"], "receipt worker")
        if receipt["status"] not in ("PAID", "REFUNDED"):
            raise ValueError("Receipt status must be PAID or REFUNDED")
        digest = receipt["artifact_sha256"]
        if digest is not None and (type(digest) is not str or not SHA256.fullmatch(digest)):
            raise ValueError("artifact_sha256 must be a lowercase SHA-256 digest or null")
        if receipt["status"] == "PAID" and (digest is None or receipt["worker"] is None):
            raise ValueError("A paid receipt must bind an artifact and worker")
        if type(receipt["transaction_ids"]) is not list or any(type(tx) is not str or not tx.strip() for tx in receipt["transaction_ids"]):
            raise ValueError("transaction_ids must be a list of nonempty strings")
        if len(set(receipt["transaction_ids"])) != len(receipt["transaction_ids"]):
            raise ValueError("Duplicate transaction ID")
        if receipts["mode"] == "LOCAL_NEAR_SANDBOX" and not receipt["transaction_ids"]:
            raise ValueError("Local NEAR sandbox receipts must include transaction IDs")
        if receipt["job_id"] in seen_jobs:
            raise ValueError("Duplicate receipt job_id")
        seen_jobs.add(receipt["job_id"])
        if digest is not None:
            if digest in seen_hashes:
                raise ValueError("Duplicate receipt artifact hash")
            seen_hashes.add(digest)
    return receipts


def _grant_map(consent):
    if consent is None:
        return {}
    if type(consent) is not dict:
        raise ValueError("Consent must be a hash-keyed object")
    for digest, grant in consent.items():
        if type(digest) is not str or not SHA256.fullmatch(digest):
            raise ValueError("Consent key must be a lowercase SHA-256 digest")
        if type(grant) is not dict or set(grant) != {"allowed", "consent"} or grant["allowed"] is not True:
            raise ValueError("Consent grant must explicitly allow publication")
        permission({"publication": grant})
    return consent


def build_integration(report=None, receipts=None, consent=None):
    """Return records and a private-safe sidecar; no filesystem writes occur."""
    if report is None:
        report = run_demo()
    if type(report) is not dict or type(report.get("scenarios")) is not list:
        raise ValueError("A core v1 report is required")
    receipts = validate_receipts(simulation_receipts(report) if receipts is None else receipts)
    grants = _grant_map(consent)

    by_hash = {}
    for result in report["scenarios"]:
        delivery = result.get("delivery", {})
        digest = delivery.get("sha256")
        if type(digest) is str:
            if digest in by_hash:
                raise ValueError("Core report contains duplicate delivery hashes")
            by_hash[digest] = result
    if grants.keys() - by_hash.keys():
        raise ValueError("Consent grant does not match a supplied core delivery")

    paid_hashes = set()
    for receipt in receipts["jobs"]:
        digest = receipt["artifact_sha256"]
        if digest is not None and digest not in by_hash:
            raise ValueError("Receipt artifact hash does not match a core delivery")
        if receipt["status"] == "PAID":
            result = by_hash[digest]
            if result["delivery"]["content"]["delivery_validity"] != "VALID":
                raise ValueError("A paid receipt cannot publish an invalid or insufficient delivery")
            if receipts["mode"] == "SIMULATION":
                ledger = result["customer_acceptance"]["ledger"]
                if ledger["paid_to_worker"] <= 0 or ledger["refunded_to_customer"]:
                    raise ValueError("Simulation receipt disagrees with the core payment ledger")
            if digest in grants:
                paid_hashes.add(digest)
        elif receipts["mode"] == "SIMULATION" and digest is not None:
            ledger = by_hash[digest]["customer_acceptance"]["ledger"]
            if ledger["refunded_to_customer"] <= 0 or ledger["paid_to_worker"]:
                raise ValueError("Simulation refund disagrees with the core payment ledger")

    # The adapter independently replays the core report. Only paid, consented
    # delivery hashes receive publication grants; refunds remain private.
    effective_grants = {digest: grants[digest] for digest in paid_hashes}
    core_records = adapt_report(report, effective_grants)
    if len(core_records) != len(report["scenarios"]):
        raise ValueError("Core adapter record count mismatch")

    public_by_hash = {}
    for result, record in zip(report["scenarios"], core_records):
        digest = result["delivery"]["sha256"]
        if record.get("publication", {}).get("allowed", False):
            public_by_hash[digest] = record

    sidecar_entries = []
    for receipt in receipts["jobs"]:
        digest = receipt["artifact_sha256"]
        record = public_by_hash.get(digest)
        if receipt["status"] != "PAID" or record is None:
            continue
        sidecar_entries.append({
            **receipt,
            "claim_id": record["id"],
            "history_tip_sha256": record["versions"][-1]["sha256"],
        })
    sidecar_entries.sort(key=lambda entry: entry["job_id"])
    sidecar = {
        "schema_version": "forecast-knowledge-payment-provenance/v1",
        "receipt_mode": receipts["mode"],
        "notice": "Local runner assertion bound to the core delivery hash. This JSON is not a cryptographic payment proof or authenticated customer identity.",
        "receipts": sidecar_entries,
    }
    return load_demo() + core_records, sidecar


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _write_output(out, records, sidecar):
    out = Path(out).absolute()
    for path in (out, *out.parents):
        if path.is_symlink():
            raise ValueError("Output path cannot contain symlinks")
    expected_files = {"index.html", "payment-provenance.json", MANIFEST}
    if out.exists():
        for child in out.iterdir():
            if child.is_symlink():
                raise ValueError("Output contains a symlink")
        if list(out.iterdir()):
            manifest_path = out / MANIFEST
            if not manifest_path.is_file():
                raise ValueError("Refusing to overwrite a non-demo directory")
            manifest = load_json(manifest_path.read_text(encoding="utf-8"))
            if manifest != sorted(expected_files) or {p.name for p in out.iterdir()} != expected_files | {"encyclopedia"}:
                raise ValueError("Output contains foreign or missing files")
            if not (out / "encyclopedia").is_dir() or (out / "encyclopedia").is_symlink():
                raise ValueError("Encyclopedia export must be a regular directory")
    out.mkdir(parents=True, exist_ok=True)
    export(records, out / "encyclopedia")
    (out / "payment-provenance.json").write_text(_json(sidecar), encoding="utf-8")
    page = (
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Forecast knowledge demo</title>"
        "<body><main><h1>Forecast knowledge demo</h1>"
        "<p>Offline, synthetic, scripted, and private by default. Public imported claims require a matching paid receipt and explicit hash-keyed consent.</p>"
        "<p>Payment provenance is a local runner assertion. A SHA-256 digest binds bytes, not their truth, transaction finality, or identity.</p>"
        "<ul><li><a href=\"encyclopedia/index.html\">Open the encyclopedia</a></li>"
        "<li><a href=\"payment-provenance.json\">Inspect payment provenance JSON</a></li></ul>"
        "</main></body></html>\n"
    )
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / MANIFEST).write_text(_json(sorted(expected_files)), encoding="utf-8")


def run(out="artifacts/knowledge-demo", core_report=None, receipts=None,
        consent=None):
    report = load_json(Path(core_report).read_text(encoding="utf-8")) if core_report else run_demo()
    receipt_doc = load_json(Path(receipts).read_text(encoding="utf-8")) if receipts else None
    consent_doc = load_json(Path(consent).read_text(encoding="utf-8")) if consent else None
    records, sidecar = build_integration(report, receipt_doc, consent_doc)
    _write_output(out, records, sidecar)
    return sidecar


def main():
    parser = argparse.ArgumentParser(description="Build a consent-gated offline forecast knowledge demo")
    parser.add_argument("--out", type=Path, default=Path("artifacts/knowledge-demo"))
    parser.add_argument("--core-report", type=Path, help="Use an actual forecast_swarm v1 report JSON")
    parser.add_argument("--receipts", type=Path, help="Optional forecast-near-receipts/v1 JSON")
    parser.add_argument("--consent", type=Path, help="Explicit grants keyed by exact delivery SHA-256")
    parser.add_argument("--fixture-consent", action="store_true", help="Use explicit synthetic fixture grants")
    args = parser.parse_args()
    if args.consent and args.fixture_consent:
        parser.error("Choose --consent or --fixture-consent, not both")
    consent = args.consent or (CONSENT_FIXTURE if args.fixture_consent else None)
    sidecar = run(args.out, args.core_report, args.receipts, consent)
    print("OFFLINE / SYNTHETIC / SCRIPTED: consent-gated knowledge export complete")
    print(f"Public paid receipts: {len(sidecar['receipts'])}")
    print(f"Landing page: {(args.out / 'index.html').absolute()}")
    print(f"Payment provenance: {(args.out / 'payment-provenance.json').absolute()}")


if __name__ == "__main__":
    main()
