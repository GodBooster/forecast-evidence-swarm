"""Strict append-only snapshots and domain-separated, integer-only commitments."""
import copy
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlsplit
from . import SCHEMA


def canonical(value):
    def check(v):
        if v is None or type(v) in (str, bool, int):
            return
        if type(v) is list:
            for x in v:
                check(x)
            return
        if type(v) is dict and all(type(k) is str for k in v):
            for x in v.values():
                check(x)
            return
        raise ValueError("Only integer-only JSON is supported")
    check(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def load_json(text):
    """Reject duplicate object keys and noncanonical numeric types at the boundary."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(text, object_pairs_hook=pairs)
    canonical(value)
    return value


def digest(domain, value):
    return hashlib.sha256((SCHEMA + ":" + domain + "\n").encode() + canonical(value)).hexdigest()


def fields(obj, names, optional=""):
    if type(obj) is not dict or not set(names.split()) <= obj.keys() or obj.keys() - set((names + " " + optional).split()):
        raise ValueError("Missing or unsupported fields")


def nonempty(v):
    if type(v) is not str or not v.strip():
        raise ValueError("Expected nonempty text")


def timestamp(v):
    if type(v) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", v):
        raise ValueError("Expected UTC whole-second timestamp")
    return datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")


def safe_id(v):
    if type(v) is not str or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", v):
        raise ValueError("Unsafe identifier")


def claim_id(identity):
    return "claim-" + digest("identity", identity)


def valid_claim_id(v):
    if type(v) is not str or not re.fullmatch(r"claim-[0-9a-f]{64}", v):
        raise ValueError("Invalid claim ID")


def safe_url(v):
    if v is None:
        return
    if type(v) is not str or any(ord(c) < 33 or ord(c) == 127 for c in v) or "\\" in v:
        raise ValueError("Unsafe URL")
    try:
        u = urlsplit(v)
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.port == 0:
            raise ValueError("Only absolute HTTP(S) links without credentials are allowed")
        u.port
    except (ValueError, TypeError) as exc:
        raise ValueError("Unsafe URL") from exc


def validate_identity(i):
    fields(i, "question scope resolution_rule resolution_source resolution_at")
    for v in i.values():
        nonempty(v)
    timestamp(i["resolution_at"])


def permission(record):
    p = record.get("publication", {"allowed": False, "consent": None})
    fields(p, "allowed consent")
    if type(p["allowed"]) is not bool:
        raise ValueError("Publication requires an explicit boolean")
    if p["allowed"]:
        fields(p["consent"], "by at statement")
        nonempty(p["consent"]["by"])
        timestamp(p["consent"]["at"])
        if p["consent"]["statement"] != "Publish this claim and its complete version history":
            raise ValueError("Explicit publication consent required")
    elif p["consent"] is not None:
        raise ValueError("Revocation must clear current consent")
    return p["allowed"]


def validate_snapshot(s, identity):
    fields(s, "as_of change_reason evidence statements criticism forecast delivery_validity customer_acceptance outcome")
    now = timestamp(s["as_of"])
    nonempty(s["change_reason"])
    if s["delivery_validity"] not in ("VALID", "INVALID", "INSUFFICIENT_DATA"):
        raise ValueError("Invalid delivery state")
    if s["customer_acceptance"] not in ("NOT_REQUESTED", "AWAITING_CUSTOMER", "ACCEPTED", "REFUNDED", "DISPUTED"):
        raise ValueError("Invalid acceptance state")
    evidence = {}
    if type(s["evidence"]) is not list:
        raise ValueError("Evidence must be a list")
    for e in s["evidence"]:
        fields(e, "id source excerpt observed_at available_at synthetic url")
        safe_id(e["id"])
        if e["id"] in evidence:
            raise ValueError("Duplicate evidence")
        nonempty(e["source"])
        nonempty(e["excerpt"])
        if e["synthetic"] is not True:
            raise ValueError("This milestone supports explicitly synthetic records only")
        safe_url(e["url"])
        if e["source"].startswith("synthetic:") and e["url"] is not None:
            raise ValueError("Synthetic identifiers cannot be public links")
        if not timestamp(e["observed_at"]) <= timestamp(e["available_at"]) <= now:
            raise ValueError("Evidence unavailable as of this version")
        evidence[e["id"]] = e

    def refs(ids, required=True):
        if type(ids) is not list or any(type(x) is not str for x in ids) or len(set(ids)) != len(ids) or (required and not ids) or any(x not in evidence for x in ids):
            raise ValueError("Invalid evidence references")
        return [evidence[x] for x in ids]

    if type(s["statements"]) is not list or type(s["criticism"]) is not list or not s["criticism"]:
        raise ValueError("Statements and criticism must be lists; criticism is required")
    for entry in s["statements"]:
        fields(entry, "text evidence_ids")
        nonempty(entry["text"])
        refs(entry["evidence_ids"])
    for c in s["criticism"]:
        nonempty(c)
    f = s["forecast"]
    fields(f, "cutoff probability_bps evidence_ids method")
    cutoff = timestamp(f["cutoff"])
    nonempty(f["method"])
    if not cutoff <= now or cutoff >= timestamp(identity["resolution_at"]):
        raise ValueError("Forecast cutoff must precede resolution and not exceed as-of")
    p = f["probability_bps"]
    if p is not None and (type(p) is not int or not 0 <= p <= 10000):
        raise ValueError("Probability must be integer basis points or null")
    if p is not None and s["delivery_validity"] != "VALID":
        raise ValueError("Invalid or insufficient delivery must abstain")
    for e in refs(f["evidence_ids"], required=p is not None):
        if timestamp(e["available_at"]) > cutoff:
            raise ValueError("Post-cutoff data cannot support the forecast")
    o = s["outcome"]
    fields(o, "status value resolved_at evidence_ids")
    if o["status"] not in ("UNRESOLVED", "PROPOSED", "DISPUTED", "FINAL"):
        raise ValueError("Invalid outcome status")
    if o["value"] is not None and (type(o["value"]) is not int or o["value"] not in (0, 1)):
        raise ValueError("Invalid outcome value")
    outcome_evidence = refs(o["evidence_ids"], required=o["status"] != "UNRESOLVED")
    if o["status"] == "UNRESOLVED" and (o["value"] is not None or o["resolved_at"] is not None or o["evidence_ids"]):
        raise ValueError("Unknown is not a negative result")
    if o["resolved_at"] is not None:
        resolved = timestamp(o["resolved_at"])
        if not timestamp(identity["resolution_at"]) <= resolved <= now:
            raise ValueError("Invalid resolution time")
        if any(timestamp(e["available_at"]) < resolved for e in outcome_evidence):
            raise ValueError("Outcome evidence predates resolution")
    if o["status"] == "FINAL":
        if o["value"] is None or o["resolved_at"] is None or any(e["source"] != identity["resolution_source"] for e in outcome_evidence):
            raise ValueError("Final result needs known value, time and specified source")
    return evidence


def forecast_commitment(identity, snapshot):
    ids = snapshot["forecast"]["evidence_ids"]
    return digest("forecast", {"identity": identity, "forecast": snapshot["forecast"],
        "evidence": sorted((e for e in snapshot["evidence"] if e["id"] in ids), key=lambda e: e["id"]),
        "delivery_validity": snapshot["delivery_validity"]})


def validate_record(r):
    fields(r, "schema id identity synthetic versions", "publication previous_claim")
    if r["schema"] != SCHEMA or r["synthetic"] is not True:
        raise ValueError("Unsupported schema or non-synthetic record")
    validate_identity(r["identity"])
    valid_claim_id(r["id"])
    if r["id"] != claim_id(r["identity"]):
        raise ValueError("Changed question, scope or rules require a new claim")
    permission(r)
    if r.get("previous_claim") is not None:
        valid_claim_id(r["previous_claim"])
        if r["previous_claim"] == r["id"]:
            raise ValueError("A revision must be a distinct claim")
    if type(r["versions"]) is not list or not r["versions"]:
        raise ValueError("At least one version required")
    prev = None
    prior_evidence = {}
    frozen = None
    for n, v in enumerate(r["versions"], 1):
        fields(v, "number previous_sha256 forecast_sha256 snapshot sha256")
        if type(v["number"]) is not int or v["number"] != n or v["previous_sha256"] != (prev["sha256"] if prev else None):
            raise ValueError("Broken version chain")
        s = v["snapshot"]
        ev = validate_snapshot(s, r["identity"])
        if prev and timestamp(s["as_of"]) <= timestamp(prev["snapshot"]["as_of"]):
            raise ValueError("Version times must strictly increase")
        if any(ev.get(k) != e for k, e in prior_evidence.items()):
            raise ValueError("Prior evidence cannot be removed or rewritten")
        fc = forecast_commitment(r["identity"], s)
        if v["forecast_sha256"] != fc or (frozen is not None and fc != frozen):
            raise ValueError("Historical forecast is immutable")
        if prev and prev["snapshot"]["outcome"]["status"] == "FINAL" and s["outcome"] != prev["snapshot"]["outcome"]:
            raise ValueError("Final outcome is immutable in v1; use a linked correction claim")
        payload = {k: val for k, val in v.items() if k != "sha256"}
        if v["sha256"] != digest("version", {"claim_id": r["id"], **payload}):
            raise ValueError("Version commitment mismatch")
        prior_evidence, frozen, prev = ev, fc, v
    return r


def append_version(record, snapshot):
    """Pure operation: never mutates caller's prior history."""
    r = copy.deepcopy(record)
    if r["versions"]:
        validate_record(r)
    s = copy.deepcopy(snapshot)
    s["evidence"].sort(key=lambda e: e["id"])
    v = {"number": len(r["versions"]) + 1,
         "previous_sha256": r["versions"][-1]["sha256"] if r["versions"] else None,
         "forecast_sha256": forecast_commitment(r["identity"], s), "snapshot": s}
    v["sha256"] = digest("version", {"claim_id": r["id"], **v})
    r["versions"].append(v)
    return validate_record(r)


def new_claim(identity, snapshot, publication=None, previous_claim=None):
    r = {"schema": SCHEMA, "id": claim_id(identity), "identity": copy.deepcopy(identity),
         "synthetic": True, "versions": []}
    if publication is not None:
        r["publication"] = copy.deepcopy(publication)
    if previous_claim is not None:
        r["previous_claim"] = previous_claim
    return append_version(r, snapshot)


def accuracy(snapshot):
    p, o = snapshot["forecast"]["probability_bps"], snapshot["outcome"]
    if p is None or o["status"] != "FINAL":
        return {"status": "NOT_EVALUABLE", "direction_correct": None, "brier_scaled_1e8": None}
    return {"status": "EVALUATED", "direction_correct": int(p >= 5000) == o["value"],
            "brier_scaled_1e8": (p - o["value"] * 10000) ** 2}


def verify_extension(trusted, candidate):
    """Detect rewrites/truncation against a retained trusted local history."""
    validate_record(trusted)
    validate_record(candidate)
    if trusted["id"] != candidate["id"] or len(candidate["versions"]) < len(trusted["versions"]) or canonical(candidate["versions"][:len(trusted["versions"])]) != canonical(trusted["versions"]):
        raise ValueError("Candidate is not an append-only extension of trusted history")
    return candidate


def revise_claim(previous, identity, snapshot, publication=None):
    validate_record(previous)
    if claim_id(identity) == previous["id"]:
        raise ValueError("Unchanged terms belong to the existing claim")
    return new_claim(identity, snapshot, publication, previous["id"])
