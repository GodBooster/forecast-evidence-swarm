"""Customer-side check before calling ``accept`` on the escrow contract.

The contract binds payment to a 64-hex SHA-256 digest and never inspects the bytes
behind it. Before accepting, the customer should therefore (1) replay the delivered
bundle through the same deterministic validator the worker used, (2) require the
replayed delivery validity to be VALID, and (3) compare the recomputed commitment with
the digest stored on chain (``get_job(id).artifact_sha256``).

    python3 -m forecast_swarm.verify --bundle <dir-or-json> --expect-sha256 <hex>

``--bundle`` accepts a bundle JSON (``{"content": …, "sha256": …}``), a core report
JSON (``{"scenarios": [{"delivery": bundle, …}]}``, selecting the delivery whose digest
equals the expected hash), a scenario wrapper with a ``delivery`` field, or a directory
containing ``report.json`` (or ``core/report.json``). Exit status 0 means the bundle
replays, is VALID and matches the expected digest; 1 otherwise. Standard library only.
A match proves byte agreement with the committed artifact, not that its contents are true.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from .evidence import validate_bundle

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


def verify(bundle, expected_sha256):
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
    lines.append("result: SAFE TO ACCEPT (bytes match the committed hash; truth is not proven)"
                 if ok else "result: DO NOT ACCEPT")
    return ok, lines


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Replay a delivery bundle, require VALID and compare its SHA-256 with the on-chain digest")
    parser.add_argument("--bundle", required=True, type=Path,
                        help="bundle JSON, core report JSON, or a directory holding report.json")
    parser.add_argument("--expect-sha256", required=True,
                        help="64 lowercase hex digits, e.g. get_job(id).artifact_sha256")
    args = parser.parse_args(argv)
    expected = args.expect_sha256.strip().lower()
    if not SHA256.fullmatch(expected):
        parser.error("--expect-sha256 must be 64 hex digits")
    try:
        bundle = load_bundle(args.bundle, expected)
    except VerifyError as exc:
        print(f"VERIFY FAILED: {exc}", file=sys.stderr)
        return 1
    ok, lines = verify(bundle, expected)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
