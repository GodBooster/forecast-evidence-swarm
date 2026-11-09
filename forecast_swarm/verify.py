"""Customer-side check before calling ``accept`` on the escrow contract.

The contract binds payment to a 64-hex SHA-256 digest and never inspects the bytes
behind it. Before accepting, the customer should therefore (1) replay the delivered
bundle through the same deterministic validator the worker used, (2) require the
replayed delivery validity to be VALID, and (3) compare the recomputed commitment with
the digest stored on chain (``get_job(id).artifact_sha256``).

    python3 -m forecast_swarm.verify --bundle <dir-or-json> --expect-sha256 <hex>

With ``--near-contract <id> --job-id <n>`` the tool reads the job itself through a
read-only NEAR RPC view call and additionally requires that the bundle's own order terms
hash to the ``order_sha256`` the customer stored at ``create_job`` and that the four
on-chain deadlines equal the terms' deadlines. That is also the resolver's rule for a
dispute: pay the worker exactly when this check passes.

    python3 -m forecast_swarm.verify --bundle <dir-or-json> --near-contract <id> --job-id <n>

``--bundle`` accepts a bundle JSON (``{"content": …, "sha256": …}``), a core report
JSON (``{"scenarios": [{"delivery": bundle, …}]}``, selecting the delivery whose digest
equals the expected hash), a scenario wrapper with a ``delivery`` field, or a directory
containing ``report.json`` (or ``core/report.json``). Exit status 0 means the bundle
replays, is VALID and matches the expected digest (and, when given, the order hash and
chain deadlines); 1 otherwise. Standard library only. The chain mode trusts the answer of
one RPC node. A match proves byte agreement with the committed artifact and order, not
that the contents are true.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from .evidence import chain_deadlines, order_commitment, validate_bundle

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REPORT_NAMES = ("report.json", "core/report.json")


class VerifyError(ValueError):
    pass


def _load_json(path):
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise VerifyError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyError(f"Cannot read JSON from {path}: {exc}") from exc


def load_bundle(path, expected_sha256):
    """Return the bundle dict selected from ``path`` (file or directory)."""
    path = Path(path)
    if path.is_dir():
        candidates = [path / name for name in REPORT_NAMES]
        found = [p for p in candidates if p.is_file()]
        if not found:
            raise VerifyError(f"{path} contains none of: {', '.join(REPORT_NAMES)}")
        path = found[0]
    document = _load_json(path)
    if type(document) is not dict:
        raise VerifyError("Top-level JSON must be an object")
    if type(document.get("scenarios")) is list:
        matches = [item["delivery"] for item in document["scenarios"]
                   if type(item) is dict and type(item.get("delivery")) is dict
                   and item["delivery"].get("sha256") == expected_sha256]
        if not matches:
            raise VerifyError("No delivery in the report carries the expected sha256")
        return matches[0]
    if type(document.get("delivery")) is dict:
        return document["delivery"]
    if "content" in document and "sha256" in document:
        return document
    raise VerifyError("JSON is neither a bundle, a scenario wrapper nor a core report")


def order_checks(bundle, expected_order_sha256=None, chain_job=None):
    """Compare the bundle's own order terms with an expected order hash and/or a chain job.

    ``chain_job`` is the JSON object returned by the contract's ``get_job`` view.
    Returns (ok, lines); a bundle without readable terms fails."""
    lines = []
    try:
        terms = bundle["content"]["inputs"]["terms"]
        order = order_commitment(terms)
        deadlines = chain_deadlines(terms)
    except (KeyError, TypeError, ValueError) as exc:
        return False, [f"order: FAILED (cannot derive the order commitment: {exc})"]
    ok = True
    lines.append(f"order sha256 (from the bundle's terms): {order}")
    if expected_order_sha256 is not None:
        match = order == expected_order_sha256
        ok &= match
        lines.append(f"order: {'MATCH' if match else 'MISMATCH'} (expected {expected_order_sha256})")
    if chain_job is not None:
        match = order == chain_job.get("order_sha256")
        ok &= match
        lines.append(f"order vs chain: {'MATCH' if match else 'MISMATCH'} (on chain {chain_job.get('order_sha256')})")
        wrong = [name for name, value in deadlines.items()
                 if type(chain_job.get(name)) is not int or chain_job[name] != value]
        ok &= not wrong
        lines.append("deadlines vs chain: MATCH" if not wrong
                     else f"deadlines vs chain: MISMATCH ({', '.join(wrong)})")
    return ok, lines


def verify(bundle, expected_sha256, expected_order_sha256=None, chain_job=None):
    """Replay the bundle; return (ok, lines). Never raises for a bad bundle."""
    lines = [f"expected sha256: {expected_sha256}"]
    recorded = bundle.get("sha256") if type(bundle) is dict else None
    lines.append(f"recorded sha256: {recorded}")
    try:
        validated = validate_bundle(bundle)
    except ValueError as exc:
        lines.append(f"replay: FAILED ({exc})")
        lines.append("result: DO NOT ACCEPT")
        return False, lines
    digest = validated["sha256"]
    validity = validated["content"]["delivery_validity"]
    match = digest == expected_sha256
    lines.append(f"replay: OK (recomputed sha256 {digest})")
    lines.append(f"hash: {'MATCH' if match else 'MISMATCH'}")
    lines.append(f"delivery validity: {validity}")
    ok = match and validity == "VALID"
    if expected_order_sha256 is not None or chain_job is not None:
        order_ok, order_lines = order_checks(validated, expected_order_sha256, chain_job)
        ok = ok and order_ok
        lines.extend(order_lines)
    scope = "bytes match the committed hash" if chain_job is None and expected_order_sha256 is None \
        else "bytes match the committed hash and the order"
    lines.append(f"result: SAFE TO ACCEPT ({scope}; truth is not proven)" if ok else "result: DO NOT ACCEPT")
    return ok, lines


def read_chain_job(rpc, contract_id, job_id):
    """``get_job`` through a read-only view call; returns (job, block_height, block_hash)."""
    answer = rpc.view(contract_id, "get_job", {"id": job_id})
    job = answer["value"]
    if type(job) is not dict:
        raise VerifyError(f"Job {job_id} does not exist on {contract_id}")
    return job, answer["block_height"], answer["block_hash"]


def main(argv=None, rpc_factory=None):
    parser = argparse.ArgumentParser(
        description="Replay a delivery bundle, require VALID and compare its SHA-256 with the on-chain digest")
    parser.add_argument("--bundle", required=True, type=Path,
                        help="bundle JSON, core report JSON, or a directory holding report.json")
    parser.add_argument("--expect-sha256",
                        help="64 lowercase hex digits, e.g. get_job(id).artifact_sha256")
    parser.add_argument("--expect-order-sha256",
                        help="order hash the customer stored with create_job (get_job(id).order_sha256)")
    parser.add_argument("--near-contract", help="escrow contract account; reads the job from chain (read-only)")
    parser.add_argument("--job-id", type=int, help="numeric job id on the escrow contract")
    parser.add_argument("--network", default="testnet", help="RPC preset for --near-contract (default: testnet)")
    parser.add_argument("--rpc-url", help="RPC endpoint override for --near-contract")
    args = parser.parse_args(argv)
    chain = args.near_contract is not None
    if chain != (args.job_id is not None):
        parser.error("--near-contract and --job-id go together")
    if not chain and args.expect_sha256 is None:
        parser.error("give --expect-sha256, or --near-contract with --job-id")
    hashes = {}
    for name in ("expect_sha256", "expect_order_sha256"):
        value = getattr(args, name)
        if value is not None:
            value = value.strip().lower()
            if not SHA256.fullmatch(value):
                parser.error(f"--{name.replace('_', '-')} must be 64 hex digits")
        hashes[name] = value
    expected, chain_job, chain_lines = hashes["expect_sha256"], None, []
    try:
        if chain:
            if rpc_factory is None:
                from .near_rpc import NearRpc
                rpc_factory = NearRpc
            try:
                rpc = rpc_factory(network=args.network, rpc_url=args.rpc_url)
                chain_job, height, block_hash = read_chain_job(rpc, args.near_contract, args.job_id)
            except RuntimeError as exc:
                raise VerifyError(f"Cannot read job {args.job_id} from {args.near_contract}: {exc}") from exc
            chain_lines = [f"chain: {args.near_contract} job {args.job_id} via {rpc.rpc_url} "
                           f"at block {height} ({block_hash})",
                           f"chain status: {chain_job.get('status')}"]
            submitted = chain_job.get("artifact_sha256")
            if type(submitted) is not str or not SHA256.fullmatch(submitted):
                raise VerifyError("The job has no submitted artifact hash on chain yet")
            if expected is not None and expected != submitted:
                raise VerifyError("--expect-sha256 differs from the artifact hash stored on chain")
            expected = submitted
        bundle = load_bundle(args.bundle, expected)
    except VerifyError as exc:
        print(f"VERIFY FAILED: {exc}", file=sys.stderr)
        return 1
    ok, lines = verify(bundle, expected, hashes["expect_order_sha256"], chain_job)
    print("\n".join(chain_lines + lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
