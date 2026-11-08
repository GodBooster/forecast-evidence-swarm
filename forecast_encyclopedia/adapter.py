"""Read-only adapter: forecast-evidence-swarm/v1 report -> encyclopedia/v1.

Imports the core verifier and simulator to replay supplied artifacts, never to
modify core files or execute external payments. Publication is never inferred.
"""
import copy
from .model import fields, canonical, new_claim, append_version, timestamp, validate_record, verify_extension, digest

CONTRACT = "forecast-evidence-swarm/v1"
LLM_CONTRACT = "forecast-evidence-swarm/llm-analyst/v1"
LLM_MODE = "SYNTHETIC_SIMULATION_LLM_ANALYST"
LLM_METHOD_PREFIX = "LLM analyst ("


def adapt_report(report, grants=None):
    from forecast_swarm.evidence import validate_bundle, validate_case, quality
    from forecast_swarm.demo import simulate
    fields(report, "schema_version mode notice commitment_notice scenarios", "role_mode")
    scripted = report["schema_version"] == CONTRACT and report["mode"] == "OFFLINE_SYNTHETIC_SIMULATION" and "role_mode" not in report
    llm = report["schema_version"] == LLM_CONTRACT and report["mode"] == LLM_MODE and type(report.get("role_mode")) is dict
    if not (scripted or llm):
        raise ValueError("Unsupported core report contract")
    if type(report["scenarios"]) is not list or (grants is not None and type(grants) is not dict):
        raise ValueError("Invalid scenarios or grants")
    grants = grants or {}
    records, seen = [], set()
    for result in report["scenarios"]:
        fields(result, "scenario title delivery evaluation customer_acceptance")
        bundle = validate_bundle(result["delivery"])
        content = bundle["content"]
        if content["schema_version"] != report["schema_version"]:
            raise ValueError("Delivery schema does not match the report contract")
        inputs = content["inputs"]
        if bundle["sha256"] in seen:
            raise ValueError("Duplicate core delivery")
        seen.add(bundle["sha256"])
        if result["scenario"] != inputs["scenario"] or result["title"] != inputs["title"]:
            raise ValueError("Core wrapper does not match committed input")
        evaluation = result["evaluation"]
        fields(evaluation, "as_of outcome forecast_quality")
        case = {**inputs, "outcome": evaluation["outcome"], "evaluation_at": evaluation["as_of"]}
        validate_case(case)
        roles = content["roles"]
        if canonical(evaluation["forecast_quality"]) != canonical(quality(case, roles["analyst"])):
            raise ValueError("Core quality replay mismatch")
        if canonical(result["customer_acceptance"]) != canonical(simulate(case, bundle)):
            raise ValueError("Core acceptance replay mismatch")
        t = inputs["terms"]
        identity = {"question": t["question"], "scope": "Synthetic core job " + t["job_id"] + ". " + inputs["title"],
                    "resolution_rule": "Use the final binary outcome from the specified core registry for this exact job, at or after its resolution time. Provisional outcomes remain unresolved.",
                    "resolution_source": t["source"], "resolution_at": t["resolution_at"]}
        evidence, rejected, local_ids = [], [], {}
        for n, e in enumerate(inputs["evidence"], 1):
            if any(e[k] is None for k in ("source", "observed_at", "available_at", "yes_count", "sample_count")) or not e["observed_at"] <= e["available_at"] <= t["decision_at"]:
                rejected.append(e["id"])
                continue
            local_ids[e["id"]] = f"core-e{n}"
            evidence.append({"id": f"core-e{n}", "source": e["source"], "excerpt": f"Supplied synthetic batch {e['id']}: {e['yes_count']} YES in {e['sample_count']} observations.",
                             "observed_at": e["observed_at"], "available_at": e["available_at"], "synthetic": True, "url": None})
        p = roles["analyst"]["probability_bps"]
        statements = [{"text": e["excerpt"], "evidence_ids": [e["id"]]} for e in evidence]
        forecast_ids = [e["id"] for e in evidence] if p is not None else []
        model_notes = []
        if roles["analyst"]["mode"] == "llm":
            analyst = roles["analyst"]
            if p is not None:
                forecast_ids = [local_ids[x] for x in analyst["evidence_ids"]]
                statements.append({"text": "Analyst rationale (LLM model output, not verified fact): " + analyst["rationale"],
                                   "evidence_ids": forecast_ids})
                model_notes = ["Model-stated uncertainty driver: " + d for d in analyst["uncertainty"]["drivers"]]
            model_notes.append("LLM output gate: " + analyst["gate"]["status"] + (" (" + "; ".join(analyst["gate"]["reasons"]) + ")" if analyst["gate"]["reasons"] else ""))
        s = {"as_of": t["decision_at"], "change_reason": "Imported and replay-validated actual core report; historical forecast snapshot.",
             "evidence": evidence, "statements": statements,
             "criticism": roles["critic"]["findings"] + model_notes + roles["verifier"]["reasons"] + (["Unusable or post-cutoff batches were excluded from encyclopedia forecast citations; original delivery validity is retained. Batch IDs: " + ", ".join(rejected)] if rejected else []),
             "forecast": {"cutoff": t["decision_at"], "probability_bps": p,
                          "evidence_ids": forecast_ids,
                          "method": roles["analyst"]["method"] + " Read-only core v1 delivery commitment: " + bundle["sha256"]},
             "delivery_validity": content["delivery_validity"], "customer_acceptance": "NOT_REQUESTED",
             "outcome": {"status": "UNRESOLVED", "value": None, "resolved_at": None, "evidence_ids": []}}
        r = new_claim(identity, s, grants.get(bundle["sha256"]))
        if timestamp(evaluation["as_of"]) > timestamp(s["as_of"]):
            later = copy.deepcopy(s)
            later.update(as_of=evaluation["as_of"], change_reason="Later core evaluation and simulated acceptance added without changing the forecast.", customer_acceptance=result["customer_acceptance"]["status"])
            o = evaluation["outcome"]
            if o and o["source"] is not None and o["resolved_at"] is not None and o["available_at"] is not None and t["resolution_at"] <= o["resolved_at"] <= o["available_at"] <= evaluation["as_of"]:
                e = {"id": "core-outcome", "source": o["source"], "excerpt": "Supplied synthetic core outcome: " + ("unknown" if o["value"] is None else "YES" if o["value"] else "NO") + "; final=" + str(o["final"]),
                     "observed_at": o["resolved_at"], "available_at": o["available_at"], "synthetic": True, "url": None}
                later["evidence"].append(e)
                later["statements"].append({"text": e["excerpt"], "evidence_ids": [e["id"]]})
                status = "FINAL" if o["final"] and o["value"] is not None and o["source"] == t["source"] else "DISPUTED" if o["source"] != t["source"] else "PROPOSED"
                later["outcome"] = {"status": status, "value": o["value"], "resolved_at": o["resolved_at"], "evidence_ids": [e["id"]]}
            elif o is not None:
                later["criticism"].append("Core outcome has unknown, unavailable or invalid resolution information; no final encyclopedia outcome inferred.")
            r = append_version(r, later)
        records.append(r)
    if grants.keys() - seen:
        raise ValueError("Consent grant does not match a supplied core delivery")
    return records


def update_core_history(report, previous_records, grants=None):
    """Merge a verified report into retained local history without rewriting it.

    Current explicit grants control publication. Previously known records omitted
    from this report remain in the returned audit collection, but become private.
    Callers persist the returned full records in private storage, not a public URL.
    """
    previous = {}
    for record in previous_records:
        validate_record(record)
        if record["id"] in previous:
            raise ValueError("Duplicate trusted claim")
        previous[record["id"]] = copy.deepcopy(record)
    updated = {}
    for incoming in adapt_report(report, grants):
        old = previous.get(incoming["id"])
        if old is None:
            updated[incoming["id"]] = incoming
            continue
        if canonical(old["versions"][0]) != canonical(incoming["versions"][0]):
            raise ValueError("Core report rewrites the trusted initial forecast version")
        candidate = copy.deepcopy(old)
        candidate.pop("publication", None)
        if "publication" in incoming:
            candidate["publication"] = copy.deepcopy(incoming["publication"])
        latest = copy.deepcopy(incoming["versions"][-1]["snapshot"])
        retained = {e["id"]: copy.deepcopy(e) for e in old["versions"][-1]["snapshot"]["evidence"]}
        for evidence in latest["evidence"]:
            if evidence["id"] in retained and canonical(retained[evidence["id"]]) != canonical(evidence):
                if evidence["id"] != "core-outcome":
                    raise ValueError("Core evidence rewrites an existing evidence ID")
                # A revised result is a new source record, never an overwrite of
                # a provisional excerpt. Keep baseline v1 import IDs compatible.
                new_id = "core-outcome-" + digest("outcome-evidence", evidence)
                evidence["id"] = new_id
                latest["outcome"]["evidence_ids"] = [new_id if x == "core-outcome" else x for x in latest["outcome"]["evidence_ids"]]
                for statement in latest["statements"]:
                    statement["evidence_ids"] = [new_id if x == "core-outcome" else x for x in statement["evidence_ids"]]
                if new_id in retained and canonical(retained[new_id]) != canonical(evidence):
                    raise ValueError("Outcome evidence commitment mismatch")
            retained[evidence["id"]] = evidence
        latest["evidence"] = sorted(retained.values(), key=lambda e: e["id"])
        if canonical(latest) != canonical(old["versions"][-1]["snapshot"]):
            if timestamp(latest["as_of"]) <= timestamp(old["versions"][-1]["snapshot"]["as_of"]):
                raise ValueError("Changed report times must strictly increase")
            candidate = append_version(candidate, latest)
        verify_extension(old, candidate)
        updated[candidate["id"]] = candidate
    for key, old in previous.items():
        if key not in updated:
            old.pop("publication", None)
            updated[key] = old
    return [updated[key] for key in sorted(updated)]
