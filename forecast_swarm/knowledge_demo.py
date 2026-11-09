"""Offline core-to-encyclopedia demonstration with explicit consent gating."""

import argparse
import json
import re
from html import escape
from pathlib import Path

from forecast_encyclopedia.adapter import adapt_report
from forecast_encyclopedia.demo import load_demo
from forecast_encyclopedia.model import load_json, permission
from forecast_encyclopedia.render import export
from .demo import run_demo
from .evidence import chain_deadlines, order_commitment, timestamp


ROOT = Path(__file__).resolve().parent.parent
CONSENT_FIXTURE = ROOT / "fixtures_encyclopedia" / "core_demo_consent.json"
RECEIPT_SCHEMA = "forecast-near-receipts/v1"
RECEIPT_SCHEMA_V2 = "forecast-near-receipts/v2"
SNAPSHOT_SCHEMA = "forecast-near-chain-snapshot/v1"
CONSENT_STATEMENT = "Publish this claim and its complete version history"
MANIFEST = ".knowledge-demo-manifest.json"
RECEIPT_LABELS = {"LOCAL_NEAR_SANDBOX": "local NEAR Sandbox receipt", "NEAR_TESTNET": "NEAR testnet receipt"}
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
    v2 = type(receipts) is dict and receipts.get("schema_version") == RECEIPT_SCHEMA_V2
    keys = {"schema_version", "mode", "network", "contract_id", "jobs"} if v2 else {"schema_version", "mode", "jobs"}
    if type(receipts) is not dict or set(receipts) != keys:
        raise ValueError("Receipt document has unexpected or missing fields")
    if v2:
        if receipts["mode"] != "NEAR_TESTNET" or receipts["network"] != "testnet":
            raise ValueError("Unsupported payment receipt schema or mode")
        _nonempty(receipts["contract_id"], "receipt contract_id")
    elif receipts["schema_version"] != RECEIPT_SCHEMA or receipts["mode"] not in ("SIMULATION", "LOCAL_NEAR_SANDBOX"):
        raise ValueError("Unsupported payment receipt schema or mode")
    if type(receipts["jobs"]) is not list:
        raise ValueError("Receipt jobs must be a list")
    seen_jobs, seen_hashes, seen_chain = set(), set(), set()
    for receipt in receipts["jobs"]:
        required = {"job_id", "artifact_sha256", "customer", "worker", "status", "transaction_ids"}
        if v2:
            required |= {"chain_job_id", "order_sha256"}
        if type(receipt) is not dict or set(receipt) != required:
            raise ValueError("Receipt has unexpected or missing fields")
        _nonempty(receipt["job_id"], "receipt job_id")
        if v2:
            chain_id = receipt["chain_job_id"]
            if type(chain_id) is not int or chain_id < 0:
                raise ValueError("chain_job_id must be an integer >= 0")
            if chain_id in seen_chain:
                raise ValueError("Duplicate receipt chain_job_id")
            seen_chain.add(chain_id)
            if type(receipt["order_sha256"]) is not str or not SHA256.fullmatch(receipt["order_sha256"]):
                raise ValueError("order_sha256 must be a lowercase SHA-256 digest")
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
        if receipts["mode"] == "NEAR_TESTNET" and not receipt["transaction_ids"]:
            raise ValueError("NEAR testnet receipts must include transaction IDs")
        if receipt["job_id"] in seen_jobs:
            raise ValueError("Duplicate receipt job_id")
        seen_jobs.add(receipt["job_id"])
        if digest is not None:
            if digest in seen_hashes:
                raise ValueError("Duplicate receipt artifact hash")
            seen_hashes.add(digest)
    return receipts


JOB_VIEW_KEYS = ("id customer worker reward order_sha256 decision_deadline_ms delivery_deadline_ms "
                 "acceptance_deadline_ms dispute_deadline_ms artifact_sha256 status pending_attempt_id "
                 "publication_consent").split()


def validate_chain_snapshot(snapshot):
    keys = {"schema_version", "network", "contract_id", "rpc_url", "captured_at", "block_height", "block_hash", "config", "jobs"}
    if type(snapshot) is not dict or set(snapshot) != keys:
        raise ValueError("Chain snapshot has unexpected or missing fields")
    if snapshot["schema_version"] != SNAPSHOT_SCHEMA or snapshot["network"] != "testnet":
        raise ValueError("Unsupported chain snapshot schema or network")
    for key in ("contract_id", "rpc_url", "block_hash"):
        _nonempty(snapshot[key], f"snapshot {key}")
    timestamp(snapshot["captured_at"])
    if type(snapshot["block_height"]) is not int or snapshot["block_height"] < 0:
        raise ValueError("snapshot block_height must be an integer >= 0")
    if type(snapshot["config"]) is not dict or type(snapshot["jobs"]) is not dict:
        raise ValueError("snapshot config and jobs must be objects")
    for key, job in snapshot["jobs"].items():
        if type(key) is not str or not key.isascii() or not key.isdecimal():
            raise ValueError("snapshot job keys must be decimal strings")
        if type(job) is not dict or not set(JOB_VIEW_KEYS) <= set(job):
            raise ValueError("snapshot job is missing get_job fields")
        if type(job["id"]) is not int or job["id"] != int(key):
            raise ValueError("snapshot job id does not match its key")
        if type(job["publication_consent"]) is not bool:
            raise ValueError("snapshot publication_consent must be a boolean")
    return snapshot


def _check_chain_receipt(receipt, job, by_hash):
    label = f"chain job {receipt['chain_job_id']}"
    for field in ("customer", "worker", "order_sha256"):
        if job[field] != receipt[field]:
            raise ValueError(f"Receipt {field} does not match {label} on chain")
    if receipt["status"] == "REFUNDED":
        if job["status"] != "REFUNDED":
            raise ValueError(f"Receipt says REFUNDED but {label} is {job['status']}")
        return
    if job["status"] != "ACCEPTED":
        raise ValueError(f"Receipt says PAID but {label} is {job['status']}, not ACCEPTED")
    if job["artifact_sha256"] != receipt["artifact_sha256"]:
        raise ValueError(f"Receipt artifact hash does not match the artifact accepted on {label}")
    terms = by_hash[receipt["artifact_sha256"]]["delivery"]["content"]["inputs"]["terms"]
    if receipt["job_id"] != terms["job_id"]:
        raise ValueError("Receipt job_id does not match the delivery terms")
    if order_commitment(terms) != receipt["order_sha256"]:
        raise ValueError(f"Order hash of {label} does not match the delivered terms")
    if chain_deadlines(terms) != {key: job[key] for key in chain_deadlines(terms)}:
        raise ValueError(f"Deadlines of {label} do not match the delivered terms")


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


def build_integration(report=None, receipts=None, consent=None, chain_snapshot=None):
    """Return records and a private-safe sidecar; no filesystem writes occur."""
    if report is None:
        report = run_demo()
    if type(report) is not dict or type(report.get("scenarios")) is not list:
        raise ValueError("A core v1 report is required")
    receipts = validate_receipts(simulation_receipts(report) if receipts is None else receipts)
    testnet = receipts["mode"] == "NEAR_TESTNET"
    if testnet:
        if chain_snapshot is None:
            raise ValueError("NEAR_TESTNET receipts require a chain snapshot")
        if consent is not None:
            raise ValueError("NEAR_TESTNET consent comes from the chain; a consent file is not accepted")
        validate_chain_snapshot(chain_snapshot)
        if chain_snapshot["network"] != receipts["network"] or chain_snapshot["contract_id"] != receipts["contract_id"]:
            raise ValueError("Chain snapshot network or contract does not match the receipts")
    elif chain_snapshot is not None:
        raise ValueError("A chain snapshot is only used with NEAR_TESTNET receipts")
    grants = {} if testnet else _grant_map(consent)

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
        job = None
        if testnet:
            job = chain_snapshot["jobs"].get(str(receipt["chain_job_id"]))
            if job is None:
                raise ValueError(f"Chain job {receipt['chain_job_id']} is not in the chain snapshot")
        if receipt["status"] == "PAID":
            result = by_hash[digest]
            if result["delivery"]["content"]["delivery_validity"] != "VALID":
                raise ValueError("A paid receipt cannot publish an invalid or insufficient delivery")
            if testnet:
                _check_chain_receipt(receipt, job, by_hash)
                if job["publication_consent"] is True:
                    grants[digest] = {"allowed": True, "consent": {
                        "by": receipt["customer"], "at": chain_snapshot["captured_at"], "statement": CONSENT_STATEMENT}}
            if receipts["mode"] == "SIMULATION":
                ledger = result["customer_acceptance"]["ledger"]
                if ledger["paid_to_worker"] <= 0 or ledger["refunded_to_customer"]:
                    raise ValueError("Simulation receipt disagrees with the core payment ledger")
            if digest in grants:
                paid_hashes.add(digest)
        elif testnet:
            _check_chain_receipt(receipt, job, by_hash)
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
    if testnet:
        sidecar.update({
            "network": receipts["network"], "contract_id": receipts["contract_id"],
            "snapshot_block_height": chain_snapshot["block_height"], "snapshot_block_hash": chain_snapshot["block_hash"],
            "snapshot_captured_at": chain_snapshot["captured_at"],
            "notice": "Receipt fields were checked against the escrow contract state on NEAR testnet recorded in a chain snapshot that was read through one RPC node (no light-client proof). Publication consent is the customer's on-chain consent_publication call for the exact artifact hash. A SHA-256 digest binds bytes, not their truth.",
        })
    return load_demo() + core_records, sidecar


def acceptance_labels(sidecar):
    """Acceptance card for claims whose receipt came from a chain rather than the simulator:
    the label names the receipt source and the value summarises the receipt itself
    (status, receipt job ID, transaction count). Pages without such a receipt keep the
    replayed simulator state under the simulation label. Records are not modified."""
    label = RECEIPT_LABELS.get(sidecar["receipt_mode"])
    if label is None:
        return None
    if sidecar["receipt_mode"] == "NEAR_TESTNET":
        return {entry["claim_id"]: {"label": label,
                                    "value": f"{entry['status']} · chain job {entry['chain_job_id']} · {len(entry['transaction_ids'])} tx"}
                for entry in sidecar["receipts"]}
    return {entry["claim_id"]: {"label": label,
                                "value": f"{entry['status']} · job {entry['job_id']} · {len(entry['transaction_ids'])} tx"}
            for entry in sidecar["receipts"]}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _write_output(out, records, sidecar, role_mode=None):
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
    export(records, out / "encyclopedia", acceptance_labels(sidecar))
    (out / "payment-provenance.json").write_text(_json(sidecar), encoding="utf-8")
    testnet = sidecar["receipt_mode"] == "NEAR_TESTNET"
    page = (
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Forecast knowledge demo</title>"
        "<body><main><h1>Forecast knowledge demo</h1>"
        + ("<p>" + ("Synthetic data, scripted roles, private by default." if testnet else "Offline, synthetic, scripted, and private by default.") + " Public imported claims require a matching paid receipt and explicit hash-keyed consent.</p>"
           if role_mode is None else
           "<p>Synthetic and private by default. Imported claims use an LLM analyst (" + escape(role_mode["provider"]) + "/"
           + escape(role_mode["model"]) + ", " + escape(role_mode["inference_source"]) + ") inside deterministic gates; critic and verifier are scripted. "
           "Public imported claims require a matching paid receipt and explicit hash-keyed consent.</p>")
        + ("<p>Payment provenance and publication consent were checked against NEAR testnet contract state recorded in a chain snapshot (one RPC node, no light-client proof). A SHA-256 digest binds bytes, not their truth.</p>" if testnet else
           "<p>Payment provenance is a local runner assertion. A SHA-256 digest binds bytes, not their truth, transaction finality, or identity.</p>")
        + "<ul><li><a href=\"encyclopedia/index.html\">Open the encyclopedia</a></li>"
        "<li><a href=\"payment-provenance.json\">Inspect payment provenance JSON</a></li></ul>"
        "</main></body></html>\n"
    )
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / MANIFEST).write_text(_json(sorted(expected_files)), encoding="utf-8")


def run(out="artifacts/knowledge-demo", core_report=None, receipts=None,
        consent=None, chain_snapshot=None):
    report = load_json(Path(core_report).read_text(encoding="utf-8")) if core_report else run_demo()
    receipt_doc = load_json(Path(receipts).read_text(encoding="utf-8")) if receipts else None
    consent_doc = load_json(Path(consent).read_text(encoding="utf-8")) if consent else None
    snapshot_doc = load_json(Path(chain_snapshot).read_text(encoding="utf-8")) if chain_snapshot else None
    records, sidecar = build_integration(report, receipt_doc, consent_doc, snapshot_doc)
    _write_output(out, records, sidecar, report.get("role_mode"))
    return sidecar


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a consent-gated offline forecast knowledge demo")
    parser.add_argument("--out", type=Path, default=Path("artifacts/knowledge-demo"))
    parser.add_argument("--core-report", type=Path, help="Use an actual forecast_swarm v1 report JSON")
    parser.add_argument("--receipts", type=Path, help="Optional forecast-near-receipts/v1 or v2 JSON (v2 = NEAR testnet, needs --chain-snapshot)")
    parser.add_argument("--chain-snapshot", type=Path, help="Recorded forecast-near-chain-snapshot/v1 JSON; required for NEAR_TESTNET receipts")
    parser.add_argument("--consent", type=Path, help="Explicit grants keyed by exact delivery SHA-256")
    parser.add_argument("--fixture-consent", action="store_true", help="Use explicit synthetic fixture grants")
    args = parser.parse_args(argv)
    if args.consent and args.fixture_consent:
        parser.error("Choose --consent or --fixture-consent, not both")
    consent = args.consent or (CONSENT_FIXTURE if args.fixture_consent else None)
    sidecar = run(args.out, args.core_report, args.receipts, consent, args.chain_snapshot)
    print("NEAR TESTNET RECEIPTS / SYNTHETIC DATA: chain-checked, consent-gated knowledge export complete"
          if sidecar["receipt_mode"] == "NEAR_TESTNET" else
          "OFFLINE / SYNTHETIC / SCRIPTED: consent-gated knowledge export complete")
    print(f"Public paid receipts: {len(sidecar['receipts'])}")
    print(f"Landing page: {(args.out / 'index.html').absolute()}")
    print(f"Payment provenance: {(args.out / 'payment-provenance.json').absolute()}")


if __name__ == "__main__":
    main()
