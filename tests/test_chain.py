import contextlib
import hashlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from forecast_swarm import chain, knowledge_demo
from forecast_swarm.evidence import chain_deadlines, epoch_ms, order_commitment, validate_case
from forecast_swarm.near_rpc import RpcError

CONTRACT = "forecast-jobs.testnet"
CUSTOMER, WORKER, RESOLVER = "customer.testnet", "worker.testnet", "resolver.testnet"
STORAGE = 10 ** 22  # 0.01 NEAR, the contract's JOB_STORAGE_DEPOSIT
REWARD = 5 * 10 ** 23
START_MS = epoch_ms("2026-11-10T08:00:00Z") + 250
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
SETTLED_FINAL = ("ACCEPTED", "REFUNDED")


def base58_id(n):
    value = int.from_bytes(hashlib.sha256(f"tx-{n}".encode()).digest(), "big")
    text = ""
    while value:
        value, rest = divmod(value, 58)
        text = B58[rest] + text
    return text.rjust(44, "A")[-44:]


class Panic(Exception):
    pass


class FakeChain:
    """In-memory escrow (mimics lib.rs; transfers settle immediately) plus RPC and near-cli doubles."""

    def __init__(self, resolver=RESOLVER, contract=CONTRACT, now_ms=START_MS):
        self.contract, self.resolver, self.now_ms = contract, resolver, now_ms
        self.rpc_url = "https://fake-rpc.invalid"
        self.jobs, self.next_id = {}, 0
        self.storage_deposits = self.escrowed = 0
        self.paid = []          # (recipient, amount)
        self.commands = []      # every argv the runner received
        self.txs = {}           # tx hash -> bool success
        self.height = 1000
        self.tx_counter = 0
        self.fail_transfers = False  # True: the transfer receipt fails, as an unreachable recipient would

    # -- clock ------------------------------------------------------------------------
    def sleep(self, seconds):
        self.now_ms += int(seconds * 1000)

    # -- rpc double -------------------------------------------------------------------
    def block(self):
        return {"height": self.height, "hash": "BLOCKHASH" + str(self.height), "timestamp_ms": self.now_ms}

    def view(self, contract_id, method, args=None):
        assert contract_id == self.contract, contract_id
        if method == "get_job":
            job = self.jobs.get(args["id"])
            value = None if job is None else self._view(args["id"], job)
        elif method == "get_config":
            value = {"resolver": self.resolver, "storage_reserve": str(10 ** 24),
                     "job_storage_deposit": str(STORAGE), "storage_deposits": str(self.storage_deposits),
                     "escrowed_rewards": str(self.escrowed), "callback_gas": 10_000_000_000_000,
                     "job_count": self.next_id, "event_standard": "forecast_jobs", "event_version": "1.0.0"}
        elif method == "job_count":
            value = self.next_id
        else:
            raise RpcError(f"fake chain has no view {method}")
        return {"value": json.loads(json.dumps(value)), "block_height": self.height,
                "block_hash": "BLOCKHASH" + str(self.height), "logs": []}

    def tx_status(self, tx_hash, sender_id):
        if tx_hash not in self.txs:
            raise RpcError("UNKNOWN_TRANSACTION")
        if self.txs[tx_hash]:
            return {"status": {"SuccessValue": ""}}
        return {"status": {"Failure": {"ActionError": {"kind": {"FunctionCallError": "ExecutionError"}}}}}

    @staticmethod
    def _view(job_id, job):
        return {"id": job_id, "customer": job["customer"], "worker": job["worker"], "reward": str(job["reward"]),
                "order_sha256": job["order_sha256"], "decision_deadline_ms": job["decision"],
                "delivery_deadline_ms": job["delivery"], "acceptance_deadline_ms": job["acceptance"],
                "dispute_deadline_ms": job["dispute"], "artifact_sha256": job["artifact"],
                "status": job["status"], "pending_attempt_id": None,
                "publication_consent": job["consent"]}

    # -- near-cli double --------------------------------------------------------------
    def runner(self, command):
        self.commands.append(list(command))
        assert command[:4] == ["near", "contract", "call-function", "as-transaction"], command
        contract, method, args_text = command[4], command[5], command[7]
        assert command[6] == "json-args" and command[8] == "prepaid-gas" and command[10] == "attached-deposit"
        assert command[12] == "sign-as" and command[14] == "network-config" and command[15] == "testnet"
        assert command[16] in ("sign-with-keychain", "sign-with-legacy-keychain") and command[17] == "send"
        assert contract == self.contract
        args, signer = json.loads(args_text), command[13]
        deposit = int(command[11].split()[0])
        self.tx_counter += 1
        tx = base58_id(self.tx_counter)
        self.height += 1
        try:
            getattr(self, "_" + method)(signer, deposit, **args)
        except Panic as exc:
            self.txs[tx] = False
            return SimpleNamespace(returncode=1, stdout="",
                                   stderr=f"Transaction ID: {tx}\nPanicked: {exc}\n")
        self.txs[tx] = True
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr=f"Transaction ID: {tx}\n")

    @staticmethod
    def require(condition, message):
        if not condition:
            raise Panic(message)

    def _job(self, job_id):
        self.require(job_id in self.jobs, "Job does not exist")
        return self.jobs[job_id]

    def _create_job(self, signer, deposit, order_sha256, decision_deadline_ms, delivery_deadline_ms,
                    acceptance_deadline_ms, dispute_deadline_ms):
        self.require(re.fullmatch(r"[0-9a-f]{64}", order_sha256), "Order hash must be 64 lowercase hex characters")
        self.require(deposit > STORAGE, "Attach the reward plus the job storage deposit")
        self.require(signer != self.resolver, "Customer must be distinct from resolver")
        self.require(self.now_ms <= decision_deadline_ms, "Job must be created by the decision deadline")
        self.require(decision_deadline_ms < delivery_deadline_ms < acceptance_deadline_ms < dispute_deadline_ms,
                     "Deadlines must satisfy decision < delivery < acceptance < dispute")
        reward = deposit - STORAGE
        self.jobs[self.next_id] = {
            "customer": signer, "worker": None, "reward": reward, "order_sha256": order_sha256,
            "decision": decision_deadline_ms, "delivery": delivery_deadline_ms,
            "acceptance": acceptance_deadline_ms, "dispute": dispute_deadline_ms,
            "artifact": None, "status": "OPEN", "consent": False}
        self.next_id += 1
        self.storage_deposits += STORAGE
        self.escrowed += reward

    def _assign(self, signer, deposit, job_id, worker):
        job = self._job(job_id)
        self.require(signer == job["customer"], "Only the customer can assign")
        self.require(self.now_ms < job["delivery"], "Delivery deadline has passed")
        self.require(job["status"] == "OPEN", "Job is not open")
        self.require(worker not in (job["customer"], self.resolver), "Worker must be distinct")
        job["worker"], job["status"] = worker, "ASSIGNED"

    def _submit(self, signer, deposit, job_id, artifact_sha256):
        self.require(re.fullmatch(r"[0-9a-f]{64}", artifact_sha256), "Artifact hash must be 64 hex")
        job = self._job(job_id)
        self.require(job["worker"] == signer, "Only the assigned worker can submit")
        self.require(job["status"] == "ASSIGNED", "Job is not assigned")
        self.require(self.now_ms >= job["decision"], "Submission is before the decision deadline")
        self.require(self.now_ms < job["delivery"], "Delivery deadline has passed")
        job["artifact"], job["status"] = artifact_sha256, "SUBMITTED"

    def _settle(self, job, pay_worker):
        if self.fail_transfers:
            job["status"] = "PAYOUT_READY" if pay_worker else "REFUND_READY"
            return
        recipient = job["worker"] if pay_worker else job["customer"]
        self.paid.append((recipient, job["reward"]))
        self.escrowed -= job["reward"]
        job["status"] = "ACCEPTED" if pay_worker else "REFUNDED"

    def _accept(self, signer, deposit, job_id, artifact_sha256):
        job = self._job(job_id)
        self.require(signer == job["customer"], "Only the customer can accept")
        self.require(job["status"] == "SUBMITTED", "Job is not submitted")
        self.require(self.now_ms < job["acceptance"], "Acceptance deadline has passed")
        self.require(job["artifact"] == artifact_sha256, "Artifact hash does not match submission")
        self._settle(job, True)

    def _dispute(self, signer, deposit, job_id):
        job = self._job(job_id)
        self.require(job["status"] == "SUBMITTED", "Job is not submitted")
        self.require(signer in (job["customer"], job["worker"]), "Only customer or worker can dispute")
        self.require(self.now_ms < job["acceptance"], "Acceptance deadline has passed")
        job["status"] = "DISPUTED"

    def _resolve(self, signer, deposit, job_id, pay_worker):
        job = self._job(job_id)
        self.require(signer == self.resolver, "Only the resolver can resolve")
        self.require(job["status"] == "DISPUTED", "Job is not disputed")
        self.require(self.now_ms < job["dispute"], "Dispute deadline has passed")
        self._settle(job, pay_worker)

    def _timeout(self, signer, deposit, job_id):
        job = self._job(job_id)
        due = {"OPEN": "delivery", "ASSIGNED": "delivery", "SUBMITTED": "acceptance",
               "DISPUTED": "dispute"}.get(job["status"])
        self.require(due is not None and self.now_ms >= job[due], "Job is not refundable by timeout yet")
        self._settle(job, False)

    def _consent_publication(self, signer, deposit, job_id, artifact_sha256):
        job = self._job(job_id)
        self.require(signer == job["customer"], "Only the customer can consent to publication")
        self.require(job["status"] == "ACCEPTED", "Only an accepted job can be published")
        self.require(job["artifact"] == artifact_sha256, "Artifact hash does not match the accepted artifact")
        self.require(not job["consent"], "Publication consent already granted")
        job["consent"] = True

    def _retry_transfer(self, signer, deposit, job_id):
        job = self._job(job_id)
        self.require(job["status"] in ("PAYOUT_READY", "REFUND_READY"), "No failed transfer is ready to retry")
        self._settle(job, job["status"] == "PAYOUT_READY")

    def methods_sent(self):
        return [command[5] for command in self.commands]


class ChainTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.chain = FakeChain()

    def cli(self, *argv, rpc="fake", contract=True):
        """Run chain.main; returns (exit code, stdout lines, stderr text)."""
        lines, err = [], io.StringIO()
        argv = list(map(str, argv))
        if contract:
            argv += ["--contract", CONTRACT]
        with contextlib.redirect_stderr(err):
            code = chain.main(argv, rpc=self.chain if rpc == "fake" else rpc, runner=self.chain.runner,
                              out=lines.append, sleep=self.chain.sleep)
        return code, lines, err.getvalue()

    def order(self, name="order", job_ref="order-1", scenario="valid_wrong"):
        path = self.dir / f"{name}.json"
        code, lines, _ = self.cli("order", "--job-ref", job_ref, "--out", path, "--scenario", scenario,
                                  contract=False)
        self.assertEqual(code, 0, lines)
        return path

    def log_path(self):
        return self.dir / "run-log.json"

    def run_to(self, stage, case=None, bundle=None):
        """Drive the happy path up to and including ``stage``. Returns (case, bundle)."""
        case = case or self.order()
        bundle = bundle or self.dir / "bundle.json"
        log = ["--log", self.log_path(), "--execute"]
        steps = [
            ("create", ["create-job", "--customer", CUSTOMER, "--case", case, "--reward-yocto", REWARD]),
            ("assign", ["assign", "--customer", CUSTOMER, "--job-id", 0, "--worker", WORKER]),
            ("submit", ["worker-run", "--worker", WORKER, "--job-id", 0, "--case", case, "--out", bundle]),
            ("accept", ["customer-check", "--customer", CUSTOMER, "--job-id", 0, "--bundle", bundle]),
            ("consent", ["consent", "--customer", CUSTOMER, "--job-id", 0]),
        ]
        for name, argv in steps:
            code, lines, err = self.cli(*argv, *log)
            self.assertEqual(code, 0, (name, lines, err))
            if name == stage:
                break
        return case, bundle

    def job(self, job_id=0):
        return self.chain.view(CONTRACT, "get_job", {"id": job_id})["value"]

    def read_log(self):
        return json.loads(self.log_path().read_text())

    def tamper(self, bundle):
        document = json.loads(Path(bundle).read_text())
        document["content"]["inputs"]["evidence"][0]["yes_count"] += 1
        tampered = Path(bundle).with_name("tampered.json")
        tampered.write_text(json.dumps(document))
        return tampered


class CallCommandTests(unittest.TestCase):
    def test_exact_argv(self):
        command = chain.call_command(CONTRACT, "submit", {"job_id": 3, "artifact_sha256": "ab"}, WORKER,
                                     deposit_yocto=7, key="legacy-keychain")
        self.assertEqual(command, [
            "near", "contract", "call-function", "as-transaction", CONTRACT, "submit",
            "json-args", '{"artifact_sha256":"ab","job_id":3}',
            "prepaid-gas", "30 Tgas", "attached-deposit", "7 yoctoNEAR",
            "sign-as", WORKER, "network-config", "testnet", "sign-with-legacy-keychain", "send"])

    def test_gas_and_default_signer_mode(self):
        command = chain.call_command(CONTRACT, "accept", {}, CUSTOMER)
        self.assertEqual(command[8:10], ["prepaid-gas", "100 Tgas"])
        self.assertEqual(command[10:12], ["attached-deposit", "0 yoctoNEAR"])
        self.assertEqual(command[16], "sign-with-keychain")

    def test_testnet_only(self):
        self.assertEqual(chain.NETWORK, "testnet")
        for method in chain.GAS_TGAS:
            for key in chain.SIGNERS:
                command = chain.call_command(CONTRACT, method, {}, CUSTOMER, 0, key)
                index = command.index("network-config")
                self.assertEqual(command[index:index + 2], ["network-config", "testnet"])
                self.assertNotIn("mainnet", " ".join(command))
        self.assertEqual(chain.build_parser().parse_args(["order", "--job-ref", "a", "--out", "x"]).command, "order")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            chain.build_parser().parse_args(["order", "--job-ref", "a", "--out", "x", "--network", "mainnet"])


class OrderTests(ChainTestCase):
    def test_order_offline_deterministic(self):
        path_a, path_b = self.dir / "a.json", self.dir / "b.json"
        runs = []
        for path in (path_a, path_b):
            code, lines, err = self.cli("order", "--job-ref", "order-1", "--out", path,
                                        "--now", "2026-11-10T08:00:00Z", rpc=None, contract=False)
            self.assertEqual((code, err), (0, ""))
            runs.append(json.loads("\n".join(lines)))
        self.assertEqual(path_a.read_bytes(), path_b.read_bytes())
        self.assertEqual({k: v for k, v in runs[0].items() if k != "case"},
                         {k: v for k, v in runs[1].items() if k != "case"})
        case = json.loads(path_a.read_text())
        validate_case(case)
        self.assertIsNone(case["outcome"])
        self.assertEqual(case["scenario"], "testnet_valid_wrong")
        self.assertEqual(case["terms"]["job_id"], "order-1")
        base = epoch_ms("2026-11-10T08:00:00Z")
        self.assertEqual(chain_deadlines(case["terms"]), {
            "decision_deadline_ms": base + 90_000, "delivery_deadline_ms": base + 270_000,
            "acceptance_deadline_ms": base + 420_000, "dispute_deadline_ms": base + 720_000})
        self.assertEqual(runs[0]["order_sha256"], order_commitment(case["terms"]))
        self.assertEqual(runs[0]["decision_deadline_ms"], base + 90_000)

    def test_bad_ordering_exit_2(self):
        for flags in (["--decision-in", "300"], ["--delivery-in", "50"], ["--acceptance-in", "270"],
                      ["--dispute-in", "420"], ["--decision-in", "0"]):
            path = self.dir / "bad.json"
            code, lines, err = self.cli("order", "--job-ref", "o", "--out", path, "--now", "2026-11-10T08:00:00Z",
                                        *flags, rpc=None, contract=False)
            self.assertEqual(code, 2, flags)
            self.assertIn("CHAIN ERROR", err)
            self.assertFalse(path.exists())

    def test_order_online_uses_chain_clock_rounded_up(self):
        path = self.order()
        case = json.loads(path.read_text())
        # chain clock is START_MS (+250 ms), the order rounds up to the next whole second
        self.assertEqual(chain_deadlines(case["terms"])["decision_deadline_ms"], (START_MS // 1000 + 1 + 90) * 1000)


class DryRunTests(ChainTestCase):
    def test_create_job_dry_run_sends_nothing(self):
        case = self.order()
        code, lines, err = self.cli("create-job", "--customer", CUSTOMER, "--case", case, "--reward-yocto", REWARD)
        self.assertEqual((code, err), (0, ""))
        text = "\n".join(lines)
        self.assertIn("DRY RUN", text)
        self.assertIn("near contract call-function as-transaction", text)
        self.assertEqual(self.chain.commands, [])
        self.assertEqual(self.chain.next_id, 0)


class HappyPathTests(ChainTestCase):
    def full_flow(self, with_consent=True):
        case = self.order()
        bundle = self.dir / "bundle.json"
        self.run_to("consent" if with_consent else "accept", case, bundle)
        snapshot = self.dir / "out" / "chain-snapshot.json"
        code, lines, err = self.cli("snapshot", "--job-ids", "0", "--out", snapshot, "--log", self.log_path())
        self.assertEqual((code, err), (0, ""), lines)
        return case, bundle, snapshot

    def test_full_happy_path(self):
        case = self.order()
        bundle = self.dir / "bundle.json"
        log = ["--log", self.log_path(), "--execute"]

        code, lines, _ = self.cli("create-job", "--customer", CUSTOMER, "--case", case,
                                  "--reward-yocto", REWARD, *log)
        self.assertEqual(code, 0)
        self.assertIn("job id: 0", lines)
        create = self.chain.commands[0]
        self.assertEqual(create[11], f"{REWARD + STORAGE} yoctoNEAR")
        self.assertEqual(self.job()["reward"], str(REWARD))

        self.assertEqual(self.cli("assign", "--customer", CUSTOMER, "--job-id", 0, "--worker", WORKER, *log)[0], 0)
        self.assertEqual(self.job()["status"], "ASSIGNED")

        before = self.chain.now_ms
        code, lines, err = self.cli("worker-run", "--worker", WORKER, "--job-id", 0, "--case", case,
                                    "--out", bundle, *log)
        self.assertEqual((code, err), (0, ""), lines)
        self.assertGreater(self.chain.now_ms, before)                      # the fake clock was waited on
        self.assertGreaterEqual(self.chain.now_ms, self.job()["decision_deadline_ms"])
        self.assertTrue(any("waiting" in line for line in lines))
        self.assertTrue(bundle.exists())
        submit = self.chain.commands[-1]
        self.assertEqual(submit[5], "submit")
        self.assertEqual(submit[16], "sign-with-legacy-keychain")
        self.assertEqual(self.job()["status"], "SUBMITTED")

        code, lines, _ = self.cli("customer-check", "--customer", CUSTOMER, "--job-id", 0, "--bundle", bundle, *log)
        self.assertEqual(code, 0)
        self.assertIn("SAFE TO ACCEPT", "\n".join(lines))
        self.assertEqual(self.chain.methods_sent()[-1], "accept")
        self.assertEqual(self.job()["status"], "ACCEPTED")
        self.assertEqual(self.chain.paid, [(WORKER, REWARD)])

        self.assertEqual(self.cli("consent", "--customer", CUSTOMER, "--job-id", 0, *log)[0], 0)
        self.assertTrue(self.job()["publication_consent"])

        snapshot = self.dir / "out" / "chain-snapshot.json"
        code, lines, _ = self.cli("snapshot", "--job-ids", "0", "--out", snapshot, "--log", self.log_path())
        self.assertEqual(code, 0)
        for name in ("chain-snapshot.json", "near-receipts.json", "README.md"):
            self.assertTrue((snapshot.parent / name).exists(), name)

        run_log = self.read_log()
        self.assertEqual(run_log["schema_version"], "forecast-near-run-log/v1")
        self.assertEqual(run_log["contract_id"], CONTRACT)
        sent = [entry for entry in run_log["entries"] if "tx_hash" in entry and "method" in entry]
        self.assertEqual([entry["method"] for entry in sent], self.chain.methods_sent())
        self.assertEqual(len(sent), 5)
        for entry in sent:
            self.assertIs(entry["succeeded"], True)
            self.assertEqual(entry["explorer"], f"https://testnet.nearblocks.io/txns/{entry['tx_hash']}")

        receipts = json.loads((snapshot.parent / "near-receipts.json").read_text())
        self.assertEqual((receipts["schema_version"], receipts["mode"]),
                         ("forecast-near-receipts/v2", "NEAR_TESTNET"))
        self.assertEqual(len(receipts["jobs"]), 1)
        receipt = receipts["jobs"][0]
        self.assertEqual((receipt["status"], receipt["job_id"], receipt["chain_job_id"]), ("PAID", "order-1", 0))
        self.assertTrue(receipt["transaction_ids"])
        self.assertTrue(set(receipt["transaction_ids"]) <= {entry["tx_hash"] for entry in sent})

        readme = (snapshot.parent / "README.md").read_text()
        self.assertIn(CONTRACT, readme)
        for entry in sent:
            if entry["method"] != "create_job":
                self.assertIn(entry["tx_hash"], readme)

    def test_readme_lists_create_job_transaction(self):
        # chain.py:469-472: the create_job log entry has no job_id (only the later "job_created"
        # entry does, and that one has no "method"), so the funding tx never appears in README.md.
        _, _, snapshot = self.full_flow()
        readme = (snapshot.parent / "README.md").read_text()
        create_tx = self.chain.txs and next(e["tx_hash"] for e in self.read_log()["entries"]
                                            if e.get("method") == "create_job")
        self.assertIn(create_tx, readme)

    def test_end_to_end_gate_with_and_without_consent(self):
        for consent, expected in ((True, 1), (False, 0)):
            with self.subTest(consent=consent):
                self.setUp()
                case, bundle, snapshot = self.full_flow(with_consent=consent)
                report = self.dir / "report.json"
                code, lines, err = self.cli("report", "--cases", case, "--out", report, rpc=None, contract=False)
                self.assertEqual((code, err), (0, ""), lines)
                result = knowledge_demo.build_integration(
                    json.loads(report.read_text()),
                    json.loads((snapshot.parent / "near-receipts.json").read_text()), None,
                    chain_snapshot=json.loads(snapshot.read_text()))
                self.assertEqual(len(result[1]["receipts"]), expected)

    def test_snapshot_without_log_writes_only_snapshot(self):
        self.run_to("accept")
        out = self.dir / "snap" / "chain-snapshot.json"
        self.assertEqual(self.cli("snapshot", "--job-ids", "0", "--out", out)[0], 0)
        self.assertEqual(sorted(p.name for p in out.parent.iterdir()), ["chain-snapshot.json"])


class WorkerRefusalTests(ChainTestCase):
    def test_refuses_different_order(self):
        case_a = self.order("a", "order-A")
        case_b = self.order("b", "order-B")
        self.run_to("assign", case_a)
        sent = len(self.chain.commands)
        code, _, err = self.cli("worker-run", "--worker", WORKER, "--job-id", 0, "--case", case_b,
                                "--out", self.dir / "b.bundle.json", "--execute")
        self.assertEqual(code, 2)
        self.assertIn("Refusing to work", err)
        self.assertEqual(len(self.chain.commands), sent)
        self.assertNotIn("submit", self.chain.methods_sent())

    def test_refuses_wrong_worker_or_status(self):
        case = self.order()
        self.run_to("create", case)                       # OPEN, nobody assigned
        argv = ["worker-run", "--worker", WORKER, "--job-id", 0, "--case", case, "--out", self.dir / "w.json",
                "--execute"]
        self.assertEqual(self.cli(*argv)[0], 2)           # not ASSIGNED
        self.cli("assign", "--customer", CUSTOMER, "--job-id", 0, "--worker", WORKER, "--execute")
        argv[2] = "intruder.testnet"
        code, _, err = self.cli(*argv)                     # ASSIGNED, but to someone else
        self.assertEqual(code, 2)
        self.assertIn("nothing for intruder.testnet to do", err)
        self.assertNotIn("submit", self.chain.methods_sent())
        self.assertFalse((self.dir / "w.json").exists())

    def test_refuses_non_valid_delivery(self):
        case = self.order("future", "order-F", "future_data")
        self.run_to("assign", case)
        bundle = self.dir / "future-bundle.json"
        code, lines, err = self.cli("worker-run", "--worker", WORKER, "--job-id", 0, "--case", case,
                                    "--out", bundle, "--execute")
        self.assertEqual(code, 2)
        self.assertIn("Refusing to submit", err)
        self.assertEqual(json.loads(bundle.read_text())["content"]["delivery_validity"], "INVALID")
        self.assertNotIn("submit", self.chain.methods_sent())


class CustomerAndResolverTests(ChainTestCase):
    def test_customer_check_tampered_bundle(self):
        _, bundle = self.run_to("submit")
        tampered = self.tamper(bundle)
        sent = len(self.chain.commands)
        code, lines, _ = self.cli("customer-check", "--customer", CUSTOMER, "--job-id", 0, "--bundle", tampered,
                                  "--execute")
        self.assertEqual(code, 1)
        self.assertIn("DO NOT ACCEPT", "\n".join(lines))
        self.assertEqual(len(self.chain.commands), sent)
        self.assertEqual(self.job()["status"], "SUBMITTED")

    def test_customer_check_dispute_on_fail(self):
        _, bundle = self.run_to("submit")
        code, lines, _ = self.cli("customer-check", "--customer", CUSTOMER, "--job-id", 0,
                                  "--bundle", self.tamper(bundle), "--dispute-on-fail", "--execute")
        self.assertEqual(code, 1)
        self.assertEqual(self.chain.methods_sent()[-1], "dispute")
        self.assertEqual(self.job()["status"], "DISPUTED")

    def test_resolver_pays_worker_for_genuine_bundle(self):
        _, bundle = self.run_to("submit")
        self.cli("dispute", "--account", CUSTOMER, "--job-id", 0, "--execute")
        self.assertEqual(self.job()["status"], "DISPUTED")
        code, _, err = self.cli("resolver-check", "--resolver", RESOLVER, "--job-id", 0, "--bundle", bundle,
                                "--execute")
        self.assertEqual((code, err), (0, ""))
        resolve = self.chain.commands[-1]
        self.assertEqual(json.loads(resolve[7]), {"job_id": 0, "pay_worker": True})
        self.assertEqual(self.job()["status"], "ACCEPTED")

    def test_resolver_refunds_for_tampered_bundle(self):
        _, bundle = self.run_to("submit")
        self.cli("customer-check", "--customer", CUSTOMER, "--job-id", 0, "--bundle", self.tamper(bundle),
                 "--dispute-on-fail", "--execute")
        code, _, _ = self.cli("resolver-check", "--resolver", RESOLVER, "--job-id", 0,
                              "--bundle", self.tamper(bundle), "--execute")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.chain.commands[-1][7]), {"job_id": 0, "pay_worker": False})
        self.assertEqual(self.job()["status"], "REFUNDED")
        self.assertEqual(self.chain.paid, [(CUSTOMER, REWARD)])

    def test_customer_check_refuses_near_acceptance_deadline(self):
        _, bundle = self.run_to("submit")
        self.chain.now_ms = self.job()["acceptance_deadline_ms"] - 5_000
        sent = len(self.chain.commands)
        code, _, err = self.cli("customer-check", "--customer", CUSTOMER, "--job-id", 0, "--bundle", bundle,
                                "--execute")
        self.assertEqual(code, 2)
        self.assertIn("Too close to the acceptance deadline", err)
        self.assertEqual(len(self.chain.commands), sent)

    def test_customer_check_wrong_customer(self):
        _, bundle = self.run_to("submit")
        code, _, err = self.cli("customer-check", "--customer", "other.testnet", "--job-id", 0,
                                "--bundle", bundle, "--execute")
        self.assertEqual(code, 2)
        self.assertIn("is not the customer", err)


class TimeoutTests(ChainTestCase):
    def test_timeout_on_submitted_waits_and_refunds(self):
        self.run_to("submit")
        deadline = self.job()["acceptance_deadline_ms"]
        self.assertLess(self.chain.now_ms, deadline)
        code, lines, err = self.cli("timeout", "--caller", "anyone.testnet", "--job-id", 0, "--execute")
        self.assertEqual((code, err), (0, ""), lines)
        self.assertGreaterEqual(self.chain.now_ms, deadline)
        self.assertEqual(self.job()["status"], "REFUNDED")
        self.assertEqual(self.chain.paid, [(CUSTOMER, REWARD)])

    def test_timeout_on_accepted_job_refused(self):
        self.run_to("accept")
        sent = len(self.chain.commands)
        code, _, err = self.cli("timeout", "--caller", "anyone.testnet", "--job-id", 0, "--execute")
        self.assertEqual(code, 2)
        self.assertIn("timeout does not apply", err)
        self.assertEqual(len(self.chain.commands), sent)

    def test_timeout_dry_run_does_not_wait_or_send(self):
        self.run_to("submit")
        now = self.chain.now_ms
        code, lines, _ = self.cli("timeout", "--caller", "anyone.testnet", "--job-id", 0)
        self.assertEqual(code, 0)
        self.assertEqual(self.chain.now_ms, now)
        self.assertIn("DRY RUN", "\n".join(lines))


class FailedTransferTests(ChainTestCase):
    """A failed transfer receipt is not a payment: exit 3, a clear message, and a retry path."""

    def test_failed_payout_is_reported_and_retry_pays_the_worker(self):
        self.run_to("submit")
        self.chain.fail_transfers = True
        code, lines, err = self.cli("customer-check", "--customer", CUSTOMER, "--job-id", 0,
                                    "--bundle", self.dir / "bundle.json", "--execute")
        text = "\n".join(lines)
        self.assertEqual((code, err), (chain.EXIT_NEEDS_RETRY, ""), text)
        self.assertIn("job 0: PAYOUT_READY", text)
        self.assertIn("TRANSFER NOT COMPLETED", text)
        self.assertEqual(self.chain.paid, [])
        self.chain.fail_transfers = False
        code, lines, err = self.cli("retry-transfer", "--caller", "anyone.testnet", "--job-id", 0, "--execute")
        self.assertEqual((code, err), (0, ""), lines)
        self.assertEqual(self.job()["status"], "ACCEPTED")
        self.assertEqual(self.chain.paid, [(WORKER, REWARD)])

    def test_failed_refund_after_timeout_is_reported(self):
        self.run_to("submit")
        self.chain.fail_transfers = True
        code, lines, _ = self.cli("timeout", "--caller", "anyone.testnet", "--job-id", 0, "--execute")
        self.assertEqual(code, chain.EXIT_NEEDS_RETRY, lines)
        self.assertEqual(self.job()["status"], "REFUND_READY")
        self.assertIn("transfer to the customer failed", "\n".join(lines))

    def test_retry_refused_without_a_failed_transfer(self):
        self.run_to("accept")
        sent = len(self.chain.commands)
        code, _, err = self.cli("retry-transfer", "--caller", "anyone.testnet", "--job-id", 0, "--execute")
        self.assertEqual(code, 2)
        self.assertIn("no failed transfer to retry", err)
        self.assertEqual(len(self.chain.commands), sent)


class FailureTests(ChainTestCase):
    def session(self):
        return chain.Session(CONTRACT, self.chain, True, self.chain.runner, lambda line: None,
                             self.log_path(), self.chain.sleep)

    def test_failed_assign_logged_and_raised(self):
        self.run_to("create")
        with self.assertRaises(chain.ChainError) as caught:
            self.session().send("assign", "assign", {"job_id": 0, "worker": WORKER}, "mallory.testnet")
        self.assertIn("failed on chain", str(caught.exception))
        entry = self.read_log()["entries"][-1]
        self.assertIs(entry["succeeded"], False)
        self.assertEqual(entry["signer"], "mallory.testnet")
        self.assertEqual(self.job()["status"], "OPEN")

    def test_accept_after_deadline_fails(self):
        _, _ = self.run_to("submit")
        job = self.job()
        self.chain.now_ms = job["acceptance_deadline_ms"] + 1
        with self.assertRaises(chain.ChainError):
            self.session().send("accept", "accept", {"job_id": 0, "artifact_sha256": job["artifact_sha256"]},
                                CUSTOMER)
        self.assertIs(self.read_log()["entries"][-1]["succeeded"], False)
        self.assertEqual(self.job()["status"], "SUBMITTED")

    def test_cli_reports_failed_tx_as_exit_2(self):
        # assign by the customer to the resolver: the contract rejects, the CLI exits 2 with the tx id
        self.run_to("create")
        code, lines, err = self.cli("assign", "--customer", CUSTOMER, "--job-id", 0, "--worker", RESOLVER,
                                    "--execute", "--log", self.log_path())
        self.assertEqual(code, 2)
        self.assertIn("FAILED", "\n".join(lines))
        self.assertIs(self.read_log()["entries"][-1]["succeeded"], False)

    def test_no_transaction_id_means_not_sent(self):
        case = self.order()
        commands = []

        def locked(command):
            commands.append(command)
            return SimpleNamespace(returncode=1, stdout="", stderr="error: keychain locked\n")

        lines, err = [], io.StringIO()
        with contextlib.redirect_stderr(err):
            code = chain.main(["create-job", "--customer", CUSTOMER, "--case", str(case), "--reward-yocto",
                               str(REWARD), "--contract", CONTRACT, "--execute", "--log", str(self.log_path())],
                              rpc=self.chain, runner=locked, out=lines.append, sleep=self.chain.sleep)
        self.assertEqual(code, 2)
        self.assertIn("keychain locked", err.getvalue())
        self.assertEqual(len(commands), 1)
        self.assertFalse(self.log_path().exists())
        with self.assertRaises(chain.ChainError):
            chain.Session(CONTRACT, self.chain, True, locked, lambda line: None, None).send(
                "x", "assign", {"job_id": 0, "worker": WORKER}, CUSTOMER)

    def test_runner_oserror_is_chain_error(self):
        def missing(command):
            raise FileNotFoundError("near")
        with self.assertRaises(chain.ChainError):
            chain.Session(CONTRACT, self.chain, True, missing, lambda line: None, None).send(
                "x", "assign", {"job_id": 0, "worker": WORKER}, CUSTOMER)


class ReceiptTests(ChainTestCase):
    def snapshot(self):
        session = chain.Session(CONTRACT, self.chain, True, self.chain.runner, lambda line: None)
        return chain.take_snapshot(session, [0])

    def test_different_contracts_rejected(self):
        self.run_to("accept")
        snapshot = self.snapshot()
        log = self.read_log()
        log["contract_id"] = "other-contract.testnet"
        with self.assertRaises(chain.ChainError):
            chain.build_receipts(log, snapshot)

    def test_run_log_for_other_contract_not_appended(self):
        self.run_to("create")
        other = chain.Session("other-contract.testnet", self.chain, True, self.chain.runner,
                              lambda line: None, self.log_path())
        with self.assertRaises(chain.ChainError):
            other.record({"step": "x"})

    def test_submitted_job_not_in_receipts(self):
        self.run_to("submit")
        receipts = chain.build_receipts(self.read_log(), self.snapshot())
        self.assertEqual(receipts["jobs"], [])

    def test_refunded_job_receipt(self):
        self.run_to("submit")
        self.cli("timeout", "--caller", CUSTOMER, "--job-id", 0, "--execute", "--log", self.log_path())
        receipts = chain.build_receipts(self.read_log(), self.snapshot())
        self.assertEqual([r["status"] for r in receipts["jobs"]], ["REFUNDED"])

    def test_job_not_created_through_log_is_skipped(self):
        # a job whose job_created entry is missing from the log has no order reference: not a receipt
        self.run_to("accept")
        log = self.read_log()
        log["entries"] = [e for e in log["entries"] if e["step"] != "job_created"]
        self.assertEqual(chain.build_receipts(log, self.snapshot())["jobs"], [])


if __name__ == "__main__":
    unittest.main()
