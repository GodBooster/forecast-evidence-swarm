"""Customer, worker-agent and resolver actions against the escrow contract on NEAR testnet.

    python3 -m forecast_swarm.chain <subcommand> --contract <escrow account> …

Reads go through the read-only RPC client (``near_rpc``). State-changing calls are signed
and sent by near-cli-rs (``near``), which holds the keys in its own keychain; this module
never reads, prints or stores key material. Every subcommand is a dry run unless
``--execute`` is given: it reads the chain, performs every check it can, and prints the
exact ``near`` command instead of sending it. Only testnet is supported.

The worker agent (``worker-run``) reads its job from the chain, refuses to work unless the
order it was handed hashes to the ``order_sha256`` stored by the customer and the deadlines
agree, builds the delivery, waits for the decision time on the chain clock and submits the
delivery hash. It is meant to sign with a function-call access key restricted to this
contract and to the methods ``submit`` and ``dispute`` (``--key legacy-keychain``), so the
agent process can commit deliveries and nothing else: it cannot transfer NEAR, deploy code
or change keys. The customer (``customer-check``) and the resolver (``resolver-check``)
apply the same deterministic rule, ``forecast_swarm.verify`` in chain mode.

Standard library only. All data are synthetic; nothing here establishes forecasting skill.
"""

import argparse
import copy
import hashlib
import json
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .demo import load_cases, run_demo
from .evidence import build_bundle, chain_deadlines, order_commitment, timestamp, validate_bundle, validate_case
from .near_rpc import NearRpc, RpcError, explorer_account_url, explorer_tx_url
from .verify import verify

NETWORK = "testnet"
GAS_TGAS = {"create_job": 30, "assign": 30, "submit": 30, "dispute": 30,
            "consent_publication": 30, "revoke_publication": 30,
            "accept": 100, "resolve": 100, "timeout": 100, "cancel": 100, "retry_transfer": 100}
SIGNERS = {"keychain": "sign-with-keychain", "legacy-keychain": "sign-with-legacy-keychain"}
TX_ID = re.compile(r"Transaction ID:\s*([1-9A-HJ-NP-Za-km-z]{32,64})")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
RUN_LOG_SCHEMA = "forecast-near-run-log/v1"
SNAPSHOT_SCHEMA = "forecast-near-chain-snapshot/v1"
RECEIPT_SCHEMA = "forecast-near-receipts/v2"
ISO = "%Y-%m-%dT%H:%M:%SZ"
SETTLED = {"ACCEPTED", "REFUNDED", "PAYOUT_READY", "REFUND_READY"}
# Never send a call this close to the deadline that would make it illegal.
DEADLINE_MARGIN_MS = 10_000


class ChainError(RuntimeError):
    pass


def call_command(contract, method, args, signer, deposit_yocto=0, key="keychain"):
    """The exact near-cli-rs command for one contract call."""
    return ["near", "contract", "call-function", "as-transaction", contract, method,
            "json-args", json.dumps(args, separators=(",", ":"), sort_keys=True),
            "prepaid-gas", f"{GAS_TGAS[method]} Tgas",
            "attached-deposit", f"{int(deposit_yocto)} yoctoNEAR",
            "sign-as", signer, "network-config", NETWORK, SIGNERS[key], "send"]


def _run_near(command):
    return subprocess.run(command, capture_output=True, text=True, timeout=240, stdin=subprocess.DEVNULL)


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChainError(f"Cannot read JSON from {path}: {exc}") from exc


def iso(ms):
    return datetime.fromtimestamp(ms // 1000, tz=timezone.utc).strftime(ISO)


class Session:
    """One contract, one RPC client, one near-cli runner; dry run unless ``execute``."""

    def __init__(self, contract, rpc, execute=False, runner=_run_near, out=print, log_path=None,
                 sleep=time.sleep, max_wait_s=1200, poll_s=2):
        self.contract, self.rpc, self.execute = contract, rpc, execute
        self.runner, self.out, self.log_path = runner, out, log_path
        self.sleep, self.max_wait_s, self.poll_s = sleep, max_wait_s, poll_s

    # -- reads -----------------------------------------------------------------------
    def view(self, method, args=None):
        return self.rpc.view(self.contract, method, args)["value"]

    def job(self, job_id):
        job = self.view("get_job", {"id": job_id})
        if type(job) is not dict:
            raise ChainError(f"Job {job_id} does not exist on {self.contract}")
        return job

    def chain_ms(self):
        return self.rpc.block()["timestamp_ms"]

    def wait_chain_time(self, target_ms, what):
        """Block until the chain clock reaches ``target_ms``. In a dry run only report."""
        now = self.chain_ms()
        if now >= target_ms:
            return True
        if not self.execute:
            self.out(f"DRY RUN: would wait {(target_ms - now + 999) // 1000}s for {what} ({iso(target_ms)})")
            return False
        self.out(f"waiting {(target_ms - now + 999) // 1000}s for {what} ({iso(target_ms)}) on the chain clock")
        waited = 0
        while now < target_ms:
            if waited >= self.max_wait_s:
                raise ChainError(f"Gave up waiting for {what}")
            self.sleep(self.poll_s)
            waited += self.poll_s
            now = self.chain_ms()
        return True

    def wait_job(self, job_id, done, what, timeout_s=90):
        """Poll ``get_job`` until ``done(job)``; the job as last seen is in the error."""
        waited = 0
        while True:
            job = self.job(job_id)
            if done(job):
                return job
            if waited >= timeout_s:
                raise ChainError(f"Job {job_id} did not reach {what}; status {job.get('status')}")
            self.sleep(self.poll_s)
            waited += self.poll_s

    # -- writes ----------------------------------------------------------------------
    def send(self, step, method, args, signer, deposit_yocto=0, key="keychain", note=None):
        """Print the command; send it only with ``execute``. Returns the tx hash or None."""
        command = call_command(self.contract, method, args, signer, deposit_yocto, key)
        self.out(f"[{step}] $ {shlex.join(command)}")
        if not self.execute:
            self.out("DRY RUN: not sent (add --execute to sign and send with near-cli)")
            return None
        try:
            done = self.runner(command)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ChainError(f"near-cli could not run: {exc}") from exc
        output = ANSI.sub("", (done.stdout or "") + "\n" + (done.stderr or ""))
        found = TX_ID.search(output)
        tail = "\n".join(output.strip().splitlines()[-12:])
        if found is None:
            raise ChainError(f"{method} was not sent (near-cli exit {done.returncode}):\n{tail}")
        tx_hash = found.group(1)
        entry = {"step": step, "method": method, "args": args, "signer": signer, "key": key,
                 "deposit_yocto": str(int(deposit_yocto)), "tx_hash": tx_hash,
                 "explorer": explorer_tx_url(NETWORK, tx_hash)}
        if note:
            entry.update(note)
        try:
            status = self.rpc.tx_status(tx_hash, signer).get("status")
        except RpcError as exc:
            raise ChainError(f"{method} sent as {tx_hash} but its status could not be read: {exc}") from exc
        entry["succeeded"] = type(status) is dict and "SuccessValue" in status
        self.record(entry)
        self.out(f"[{step}] tx {tx_hash} {'succeeded' if entry['succeeded'] else 'FAILED'}  {entry['explorer']}")
        if not entry["succeeded"]:
            raise ChainError(f"{method} failed on chain (tx {tx_hash}):\n{tail}")
        if done.returncode != 0:
            raise ChainError(f"{method} succeeded on chain (tx {tx_hash}) but near-cli exited {done.returncode}:\n{tail}")
        return tx_hash

    def record(self, entry):
        if self.log_path is None:
            return
        path = Path(self.log_path)
        log = _read_json(path) if path.exists() else {
            "schema_version": RUN_LOG_SCHEMA, "network": NETWORK, "contract_id": self.contract, "entries": []}
        if log.get("schema_version") != RUN_LOG_SCHEMA or log.get("contract_id") != self.contract:
            raise ChainError(f"{path} is not a run log for {self.contract}")
        log["entries"].append(entry)
        _write_json(path, log)


# -- order ---------------------------------------------------------------------------

def make_order_case(now_ms, job_ref, scenario="valid_wrong", decision_in=90, delivery_in=270,
                    acceptance_in=420, dispute_in=720):
    """A synthetic order with fresh deadlines: the fixture case shifted to the chain clock.

    Evidence timestamps move with the decision time, so the evidence gate sees the same
    relative timing as the fixture. The order carries no outcome: resolution is later."""
    if not (0 < decision_in < delivery_in < acceptance_in < dispute_in):
        raise ChainError("Require 0 < decision < delivery < acceptance < dispute (seconds from now)")
    source = next((case for case in load_cases() if case["scenario"] == scenario), None)
    if source is None:
        raise ChainError(f"Unknown fixture scenario: {scenario}")
    case = copy.deepcopy(source)
    base = datetime.fromtimestamp(-(-now_ms // 1000), tz=timezone.utc).replace(tzinfo=None)
    decision = base + timedelta(seconds=decision_in)
    delta = decision - timestamp(case["terms"]["decision_at"])

    def shift(value):
        return (timestamp(value) + delta).strftime(ISO)

    terms = case["terms"]
    terms["job_id"] = job_ref
    terms["decision_at"] = decision.strftime(ISO)
    terms["delivery_deadline"] = (base + timedelta(seconds=delivery_in)).strftime(ISO)
    terms["acceptance_deadline"] = (base + timedelta(seconds=acceptance_in)).strftime(ISO)
    terms["dispute_deadline"] = (base + timedelta(seconds=dispute_in)).strftime(ISO)
    terms["resolution_at"] = max(timestamp(shift(terms["resolution_at"])),
                                 base + timedelta(seconds=delivery_in + 1)).strftime(ISO)
    for item in case["evidence"]:
        item["observed_at"], item["available_at"] = shift(item["observed_at"]), shift(item["available_at"])
    case["scenario"] = "testnet_" + scenario
    case["title"] = f"Synthetic testnet order {job_ref}"
    case["outcome"] = None
    case["evaluation_at"] = terms["decision_at"]
    validate_case(case)
    return case


def cmd_order(session, args):
    now_ms = int(timestamp(args.now).replace(tzinfo=timezone.utc).timestamp() * 1000) if args.now \
        else session.chain_ms()
    case = make_order_case(now_ms, args.job_ref, args.scenario, args.decision_in, args.delivery_in,
                           args.acceptance_in, args.dispute_in)
    _write_json(args.out, case)
    session.out(json.dumps({"case": str(args.out), "job_ref": args.job_ref,
                            "order_sha256": order_commitment(case["terms"]),
                            **chain_deadlines(case["terms"])}, indent=2))
    return 0


def _load_case(path):
    case = _read_json(path)
    try:
        validate_case(case)
    except (ValueError, KeyError, TypeError) as exc:
        raise ChainError(f"{path} is not a valid order case: {exc}") from exc
    return case


def _order_matches(job, terms):
    """Problems that make the on-chain job a different order than ``terms``."""
    problems = []
    if job.get("order_sha256") != order_commitment(terms):
        problems.append("order hash on chain differs from the order I was given")
    problems += [f"{name} on chain differs from the order" for name, value in chain_deadlines(terms).items()
                 if job.get(name) != value]
    return problems


# -- customer ------------------------------------------------------------------------

def cmd_create_job(session, args):
    case = _load_case(args.case)
    terms, reward = case["terms"], int(args.reward_yocto)
    if reward <= 0:
        raise ChainError("--reward-yocto must be positive")
    config = session.view("get_config")
    storage = int(config["job_storage_deposit"])
    deadlines = chain_deadlines(terms)
    if session.chain_ms() + DEADLINE_MARGIN_MS >= deadlines["decision_deadline_ms"]:
        raise ChainError("The order's decision time is too close or already past on the chain clock")
    order = order_commitment(terms)
    first = session.view("job_count")
    session.out(f"order {terms['job_id']}: order_sha256 {order}; reward {reward} + storage {storage} yoctoNEAR")
    tx = session.send("create_job", "create_job", {"order_sha256": order, **deadlines}, args.customer,
                      reward + storage, note={"job_ref": terms["job_id"]})
    if tx is None:
        return 0
    for job_id in range(first, session.view("job_count")):
        job = session.job(job_id)
        if job["customer"] == args.customer and job["order_sha256"] == order:
            session.record({"step": "job_created", "job_id": job_id, "job_ref": terms["job_id"], "tx_hash": tx})
            session.out(f"job id: {job_id}")
            return 0
    raise ChainError("create_job succeeded but the new job was not found")


def cmd_assign(session, args):
    job = session.job(args.job_id)
    if job["status"] != "OPEN" or job["customer"] != args.customer:
        raise ChainError(f"Job {args.job_id} is {job['status']} for customer {job['customer']}; cannot assign")
    tx = session.send("assign", "assign", {"job_id": args.job_id, "worker": args.worker}, args.customer,
                      note={"job_id": args.job_id})
    if tx:
        session.wait_job(args.job_id, lambda j: j["status"] == "ASSIGNED" and j["worker"] == args.worker, "ASSIGNED")
    return 0


def _checked_bundle(session, job_id, bundle_path, wanted_status):
    """Read the job, require the status, run the chain-mode verification. -> (job, ok)"""
    job = session.job(job_id)
    if job["status"] != wanted_status:
        raise ChainError(f"Job {job_id} is {job['status']}, expected {wanted_status}")
    digest = job.get("artifact_sha256")
    bundle = _read_json(bundle_path)
    ok, lines = verify(bundle, digest, chain_job=job)
    session.out("\n".join(lines))
    return job, ok


def cmd_customer_check(session, args):
    job, ok = _checked_bundle(session, args.job_id, args.bundle, "SUBMITTED")
    if job["customer"] != args.customer:
        raise ChainError(f"{args.customer} is not the customer of job {args.job_id}")
    if session.chain_ms() + DEADLINE_MARGIN_MS >= job["acceptance_deadline_ms"]:
        raise ChainError("Too close to the acceptance deadline to act safely")
    note = {"job_id": args.job_id, "verified": ok}
    if ok:
        tx = session.send("accept", "accept", {"job_id": args.job_id, "artifact_sha256": job["artifact_sha256"]},
                          args.customer, note=note)
        if tx:
            final = session.wait_job(args.job_id, lambda j: j["status"] in SETTLED, "a settled payout")
            session.out(f"job {args.job_id}: {final['status']}")
        return 0
    if args.dispute_on_fail:
        tx = session.send("dispute", "dispute", {"job_id": args.job_id}, args.customer, note=note)
        if tx:
            session.wait_job(args.job_id, lambda j: j["status"] == "DISPUTED", "DISPUTED")
    else:
        session.out("not accepted; no transaction sent (use --dispute-on-fail to open a dispute)")
    return 1


def cmd_dispute(session, args):
    job = session.job(args.job_id)
    if job["status"] != "SUBMITTED" or args.account not in (job["customer"], job["worker"]):
        raise ChainError(f"Job {args.job_id} is {job['status']}; only its customer or worker can dispute a submission")
    tx = session.send("dispute", "dispute", {"job_id": args.job_id}, args.account, key=args.key,
                      note={"job_id": args.job_id})
    if tx:
        session.wait_job(args.job_id, lambda j: j["status"] == "DISPUTED", "DISPUTED")
    return 0


def cmd_consent(session, args):
    job = session.job(args.job_id)
    if job["status"] != "ACCEPTED" or job["customer"] != args.customer:
        raise ChainError(f"Job {args.job_id} is {job['status']}; only the customer of an ACCEPTED job can consent")
    tx = session.send("consent", "consent_publication",
                      {"job_id": args.job_id, "artifact_sha256": job["artifact_sha256"]}, args.customer,
                      note={"job_id": args.job_id})
    if tx:
        session.wait_job(args.job_id, lambda j: j["publication_consent"] is True, "publication consent")
    return 0


# -- worker agent --------------------------------------------------------------------

def cmd_worker_run(session, args):
    case = _load_case(args.case)
    terms = case["terms"]
    job = session.job(args.job_id)
    if job["worker"] != args.worker or job["status"] != "ASSIGNED":
        raise ChainError(f"Job {args.job_id} is {job['status']} with worker {job['worker']}; nothing for {args.worker} to do")
    problems = _order_matches(job, terms)
    if problems:
        raise ChainError("Refusing to work: " + "; ".join(problems))
    session.out(f"job {args.job_id}: order {job['order_sha256']} matches the order file; reward {job['reward']} yoctoNEAR")
    bundle = validate_bundle(build_bundle(case))
    validity = bundle["content"]["delivery_validity"]
    _write_json(args.out, bundle)
    session.out(f"delivery {bundle['sha256']} ({validity}) written to {args.out}")
    if validity != "VALID":
        raise ChainError(f"Refusing to submit a {validity} delivery: it would not pass the customer's check")
    ready = session.wait_chain_time(job["decision_deadline_ms"] + 1000, "the decision time")
    if ready and session.chain_ms() + DEADLINE_MARGIN_MS >= job["delivery_deadline_ms"]:
        raise ChainError("Too close to the delivery deadline to submit safely")
    tx = session.send("submit", "submit", {"job_id": args.job_id, "artifact_sha256": bundle["sha256"]},
                      args.worker, key=args.key, note={"job_id": args.job_id})
    if tx:
        session.wait_job(args.job_id, lambda j: j["status"] == "SUBMITTED"
                         and j["artifact_sha256"] == bundle["sha256"], "SUBMITTED with the delivery hash")
    return 0


# -- resolver and anyone -------------------------------------------------------------

def cmd_resolver_check(session, args):
    job, ok = _checked_bundle(session, args.job_id, args.bundle, "DISPUTED")
    if session.chain_ms() + DEADLINE_MARGIN_MS >= job["dispute_deadline_ms"]:
        raise ChainError("Too close to the dispute deadline to resolve safely")
    session.out(f"resolver rule: verification {'passed, pay the worker' if ok else 'failed, refund the customer'}")
    tx = session.send("resolve", "resolve", {"job_id": args.job_id, "pay_worker": ok}, args.resolver,
                      note={"job_id": args.job_id, "verified": ok})
    if tx:
        final = session.wait_job(args.job_id, lambda j: j["status"] in SETTLED, "a settled transfer")
        session.out(f"job {args.job_id}: {final['status']}")
    return 0


def cmd_timeout(session, args):
    job = session.job(args.job_id)
    deadline = {"OPEN": "delivery_deadline_ms", "ASSIGNED": "delivery_deadline_ms",
                "SUBMITTED": "acceptance_deadline_ms", "DISPUTED": "dispute_deadline_ms"}.get(job["status"])
    if deadline is None:
        raise ChainError(f"Job {args.job_id} is {job['status']}; timeout does not apply")
    session.wait_chain_time(job[deadline] + 1000, deadline.replace("_ms", "").replace("_", " "))
    tx = session.send("timeout", "timeout", {"job_id": args.job_id}, args.caller,
                      note={"job_id": args.job_id, "previous_status": job["status"]})
    if tx:
        final = session.wait_job(args.job_id, lambda j: j["status"] in SETTLED, "a settled refund")
        session.out(f"job {args.job_id}: {final['status']}")
    return 0


# -- evidence ------------------------------------------------------------------------

def take_snapshot(session, job_ids):
    config = session.rpc.view(session.contract, "get_config")
    jobs = {str(job_id): session.job(job_id) for job_id in job_ids}
    block = session.rpc.block()
    return {"schema_version": SNAPSHOT_SCHEMA, "network": NETWORK, "contract_id": session.contract,
            "rpc_url": session.rpc.rpc_url, "captured_at": iso(block["timestamp_ms"]),
            "block_height": block["height"], "block_hash": block["hash"],
            "config": config["value"], "jobs": jobs}


def build_receipts(log, snapshot):
    """v2 receipts for every settled job in the snapshot; transaction IDs come from the run log."""
    if log.get("contract_id") != snapshot.get("contract_id"):
        raise ChainError("Run log and snapshot are for different contracts")
    refs, txs = {}, {}
    for entry in log["entries"]:
        if "job_id" not in entry:
            continue
        if entry["step"] == "job_created":
            refs[entry["job_id"]] = entry["job_ref"]
        if entry.get("tx_hash") and entry["tx_hash"] not in txs.setdefault(entry["job_id"], []):
            txs[entry["job_id"]].append(entry["tx_hash"])
    jobs = []
    for key, job in sorted(snapshot["jobs"].items(), key=lambda item: int(item[0])):
        status = {"ACCEPTED": "PAID", "REFUNDED": "REFUNDED"}.get(job["status"])
        if status is None or job["id"] not in refs:
            continue
        jobs.append({"job_id": refs[job["id"]], "chain_job_id": job["id"], "order_sha256": job["order_sha256"],
                     "artifact_sha256": job["artifact_sha256"], "customer": job["customer"],
                     "worker": job["worker"], "status": status, "transaction_ids": txs.get(job["id"], [])})
    return {"schema_version": RECEIPT_SCHEMA, "mode": "NEAR_TESTNET", "network": NETWORK,
            "contract_id": snapshot["contract_id"], "jobs": jobs}


def summary_markdown(log, snapshot, receipts):
    contract = snapshot["contract_id"]
    lines = [f"# NEAR testnet run: `{contract}`", "",
             "Synthetic orders, testnet NEAR only. Every line below can be re-checked against the chain; "
             "`chain-snapshot.json` is the contract state this summary was built from "
             f"(block {snapshot['block_height']}, {snapshot['captured_at']}, read through one RPC node).", "",
             f"- Contract: [{contract}]({explorer_account_url(NETWORK, contract)})",
             f"- Resolver: `{snapshot['config']['resolver']}`",
             f"- Jobs created: {snapshot['config']['job_count']}",
             f"- Escrowed rewards after the run: {snapshot['config']['escrowed_rewards']} yoctoNEAR",
             f"- Per-job storage deposits kept by the contract: {snapshot['config']['storage_deposits']} yoctoNEAR", ""]
    refs = {job["chain_job_id"]: job for job in receipts["jobs"]}
    for key, job in sorted(snapshot["jobs"].items(), key=lambda item: int(item[0])):
        receipt = refs.get(job["id"], {})
        lines += [f"## Job {job['id']}" + (f" (`{receipt['job_id']}`)" if receipt else ""), "",
                  f"- Final status: **{job['status']}**" + (f" → receipt `{receipt['status']}`" if receipt else ""),
                  f"- Customer `{job['customer']}`, worker `{job['worker']}`, reward {job['reward']} yoctoNEAR",
                  f"- Order hash `{job['order_sha256']}`", f"- Delivery hash `{job['artifact_sha256']}`",
                  f"- Publication consent on chain: `{str(job['publication_consent']).lower()}`", "",
                  "| Step | Signer | Key | Transaction |", "|---|---|---|---|"]
        created = {entry["tx_hash"] for entry in log["entries"]
                   if entry.get("step") == "job_created" and entry.get("job_id") == job["id"]}
        for entry in log["entries"]:
            if entry.get("method") and (entry.get("job_id") == job["id"] or entry["tx_hash"] in created):
                lines.append(f"| `{entry['method']}` | `{entry['signer']}` | {entry['key']} | "
                             f"[{entry['tx_hash']}]({entry['explorer']}) |")
        lines.append("")
    return "\n".join(lines)


def cmd_snapshot(session, args):
    job_ids = [int(item) for item in args.job_ids.split(",") if item.strip()]
    snapshot = take_snapshot(session, job_ids)
    _write_json(args.out, snapshot)
    session.out(f"snapshot of {len(job_ids)} job(s) at block {snapshot['block_height']} written to {args.out}")
    if args.log:
        log = _read_json(args.log)
        receipts = build_receipts(log, snapshot)
        out_dir = Path(args.out).parent
        _write_json(out_dir / "near-receipts.json", receipts)
        (out_dir / "README.md").write_text(summary_markdown(log, snapshot, receipts), encoding="utf-8")
        session.out(f"receipts ({len(receipts['jobs'])} settled job(s)) and README.md written to {out_dir}")
    return 0


def base58(data):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number, text = int.from_bytes(data, "big"), ""
    while number:
        number, digit = divmod(number, 58)
        text = alphabet[digit] + text
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + text


def cmd_deployment(session, args):
    """Compare the code deployed on chain with a local wasm build (code hash = SHA-256)."""
    try:
        digest = hashlib.sha256(Path(args.wasm).read_bytes()).digest()
    except OSError as exc:
        raise ChainError(f"Cannot read {args.wasm}: {exc}") from exc
    account = session.rpc.view_account(session.contract)
    record = {"network": NETWORK, "contract_id": session.contract, "block_height": account.get("block_height"),
              "code_hash_on_chain": account.get("code_hash"), "local_wasm_sha256": digest.hex(),
              "local_wasm_code_hash": base58(digest), "matches": account.get("code_hash") == base58(digest),
              "storage_usage_bytes": account.get("storage_usage")}
    if args.out:
        _write_json(args.out, record)
    session.out(json.dumps(record, indent=2))
    return 0 if record["matches"] else 1


def cmd_report(session, args):
    """A core report for the given order cases, in the shape the knowledge demo imports."""
    report = run_demo(cases=[_load_case(path) for path in args.cases])
    _write_json(args.out, report)
    session.out(f"core report for {len(args.cases)} order(s) written to {args.out}")
    return 0


# -- CLI -----------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="python3 -m forecast_swarm.chain",
        description="Escrow actions on NEAR testnet. Dry run unless --execute; keys stay in near-cli's keychain.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--contract", help="escrow contract account on testnet")
    common.add_argument("--rpc-url", help="testnet RPC endpoint override")
    common.add_argument("--execute", action="store_true", help="sign and send with near-cli (default: dry run)")
    common.add_argument("--log", type=Path, help="append sent transactions to this run-log JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, handler, text):
        item = sub.add_parser(name, parents=[common], help=text, description=text)
        item.set_defaults(handler=handler)
        return item

    item = add("order", cmd_order, "Write a synthetic order case with fresh deadlines and print its order hash")
    item.add_argument("--job-ref", required=True, help="order reference stored in the terms (terms.job_id)")
    item.add_argument("--out", required=True, type=Path)
    item.add_argument("--scenario", default="valid_wrong", help="fixture scenario to derive the order from")
    item.add_argument("--now", help="YYYY-MM-DDTHH:MM:SSZ instead of the chain clock (offline use)")
    for name, value in (("decision", 90), ("delivery", 270), ("acceptance", 420), ("dispute", 720)):
        item.add_argument(f"--{name}-in", type=int, default=value, help=f"seconds from now (default {value})")

    item = add("create-job", cmd_create_job, "Customer: fund a job bound to the order hash")
    item.add_argument("--customer", required=True)
    item.add_argument("--case", required=True, type=Path)
    item.add_argument("--reward-yocto", required=True)

    item = add("assign", cmd_assign, "Customer: assign the worker")
    item.add_argument("--customer", required=True)
    item.add_argument("--job-id", required=True, type=int)
    item.add_argument("--worker", required=True)

    item = add("worker-run", cmd_worker_run,
               "Worker agent: check the order against the chain, build the delivery, submit its hash")
    item.add_argument("--worker", required=True)
    item.add_argument("--job-id", required=True, type=int)
    item.add_argument("--case", required=True, type=Path, help="the order the worker was handed")
    item.add_argument("--out", required=True, type=Path, help="where to write the delivery bundle")
    item.add_argument("--key", choices=sorted(SIGNERS), default="legacy-keychain",
                      help="near-cli key store holding the worker's function-call key (default: legacy-keychain)")

    item = add("customer-check", cmd_customer_check,
               "Customer: verify the delivery against the chain, then accept (or dispute)")
    item.add_argument("--customer", required=True)
    item.add_argument("--job-id", required=True, type=int)
    item.add_argument("--bundle", required=True, type=Path)
    item.add_argument("--dispute-on-fail", action="store_true")

    item = add("dispute", cmd_dispute, "Customer or worker: dispute a submission")
    item.add_argument("--account", required=True)
    item.add_argument("--job-id", required=True, type=int)
    item.add_argument("--key", choices=sorted(SIGNERS), default="keychain")

    item = add("resolver-check", cmd_resolver_check,
               "Resolver: apply the verification rule to a disputed job and resolve it")
    item.add_argument("--resolver", required=True)
    item.add_argument("--job-id", required=True, type=int)
    item.add_argument("--bundle", required=True, type=Path)

    item = add("timeout", cmd_timeout, "Anyone: wait for the applicable deadline and trigger the refund")
    item.add_argument("--caller", required=True)
    item.add_argument("--job-id", required=True, type=int)

    item = add("consent", cmd_consent, "Customer: record publication consent for the accepted delivery on chain")
    item.add_argument("--customer", required=True)
    item.add_argument("--job-id", required=True, type=int)

    item = add("snapshot", cmd_snapshot, "Record get_job/get_config for offline re-checking; with --log also receipts")
    item.add_argument("--job-ids", required=True, help="comma-separated chain job ids")
    item.add_argument("--out", required=True, type=Path)

    item = add("deployment", cmd_deployment, "Check that the deployed code hash equals a local wasm build")
    item.add_argument("--wasm", required=True, type=Path)
    item.add_argument("--out", type=Path)

    item = add("report", cmd_report, "Build the core report for order cases (input of the knowledge demo)")
    item.add_argument("--cases", required=True, nargs="+", type=Path)
    item.add_argument("--out", required=True, type=Path)
    return parser


OFFLINE = {"report"}


def main(argv=None, rpc=None, runner=_run_near, out=print, sleep=time.sleep):
    args = build_parser().parse_args(argv)
    offline = args.command in OFFLINE or (args.command == "order" and args.now)
    try:
        if not offline and not args.contract and args.command != "order":
            raise ChainError("--contract is required")
        if rpc is None and not offline:
            rpc = NearRpc(network=NETWORK, rpc_url=args.rpc_url)
        session = Session(args.contract, rpc, args.execute, runner, out, args.log, sleep)
        return args.handler(session, args)
    except (ChainError, RpcError) as exc:
        print(f"CHAIN ERROR: {exc}", file=sys.stderr)
        return 2
    except (ValueError, KeyError, TypeError) as exc:
        print(f"CHAIN ERROR: unexpected data: {exc!r}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
