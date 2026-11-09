import base64
import io
import json
import unittest

from forecast_swarm import near_rpc
from forecast_swarm.near_rpc import NearRpc, RpcError

TX = "9" * 44
OK_VIEW = {"result": {"result": list(b'{"a":1}'), "logs": ["l"], "block_height": 7, "block_hash": "H"}}


def raw(obj):
    return json.dumps(obj).encode()


class FakeTransport:
    def __init__(self, *queue):
        self.queue, self.calls = list(queue), []

    def __call__(self, url, body, timeout_s):
        self.calls.append((url, json.loads(body), timeout_s))
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def client(*queue, **kw):
    transport = FakeTransport(*queue)
    return NearRpc(transport=transport, sleep=lambda s: None, **kw), transport


class ViewTests(unittest.TestCase):
    def test_happy_path(self):
        rpc, t = client(raw({"jsonrpc": "2.0", "id": "fes", **OK_VIEW}))
        out = rpc.view("job.testnet", "get_job", {"z": 1, "id": 3})
        self.assertEqual(out, {"value": {"a": 1}, "block_height": 7, "block_hash": "H", "logs": ["l"]})
        url, body, timeout = t.calls[0]
        self.assertEqual(url, "https://rpc.testnet.fastnear.com")
        self.assertEqual((body["method"], body["id"], body["jsonrpc"]), ("query", "fes", "2.0"))
        p = body["params"]
        self.assertEqual((p["request_type"], p["finality"], p["account_id"], p["method_name"]),
                         ("call_function", "final", "job.testnet", "get_job"))
        self.assertEqual(base64.b64decode(p["args_base64"]), b'{"id":3,"z":1}')
        self.assertEqual(timeout, 15)

    def test_default_args_empty_object(self):
        rpc, t = client(raw(OK_VIEW))
        rpc.view("job.testnet", "m")
        self.assertEqual(base64.b64decode(t.calls[0][1]["params"]["args_base64"]), b"{}")

    def test_contract_error_in_result(self):
        rpc, _ = client(raw({"result": {"error": "wasm execution failed: Smart contract panicked: boom"}}))
        with self.assertRaisesRegex(RpcError, "panicked: boom"):
            rpc.view("job.testnet", "m")

    def test_rpc_error_object(self):
        rpc, t = client(raw({"error": {"name": "HANDLER_ERROR", "cause": {"name": "UNKNOWN_ACCOUNT"},
                                       "message": "Server error", "data": "account x does not exist"}}))
        with self.assertRaises(RpcError) as ctx:
            rpc.view("nope.testnet", "m")
        for part in ("HANDLER_ERROR", "UNKNOWN_ACCOUNT", "Server error", "does not exist"):
            self.assertIn(part, str(ctx.exception))
        self.assertEqual(len(t.calls), 1)  # JSON-RPC errors are not retried

    def test_bad_responses(self):
        for payload in (b"not json", b"\xff\xfe", b"[1]", b"{}", b'{"result":1,"result":2}'):
            rpc, _ = client(payload)
            with self.assertRaises(RpcError, msg=payload):
                rpc.view("job.testnet", "m")

    def test_non_json_contract_value(self):
        rpc, _ = client(raw({"result": {"result": list(b"xx"), "block_height": 1, "block_hash": "h"}}))
        with self.assertRaises(RpcError):
            rpc.view("job.testnet", "m")


class RetryTests(unittest.TestCase):
    def test_retry_then_success(self):
        sleeps = []
        t = FakeTransport(RpcError("boom"), raw(OK_VIEW))
        rpc = NearRpc(transport=t, sleep=sleeps.append)
        self.assertEqual(rpc.view("job.testnet", "m")["value"], {"a": 1})
        self.assertEqual((len(t.calls), len(sleeps)), (2, 1))

    def test_retries_exhausted(self):
        rpc, t = client(RpcError("a"), RpcError("b"), RpcError("c"), raw(OK_VIEW))
        with self.assertRaisesRegex(RpcError, "c"):
            rpc.view("job.testnet", "m")
        self.assertEqual(len(t.calls), 3)

    def test_zero_retries(self):
        rpc, t = client(RpcError("a"), raw(OK_VIEW), retries=0)
        with self.assertRaises(RpcError):
            rpc.view("job.testnet", "m")
        self.assertEqual(len(t.calls), 1)

    def test_deadline_enforced(self):
        clk = FakeClock()
        t = FakeTransport(*[RpcError("slow") for _ in range(10)])

        def slow(url, body, timeout_s):
            clk.now += 20
            return t(url, body, timeout_s)
        rpc = NearRpc(transport=slow, clock=clk, sleep=clk.sleep, timeout_s=15, deadline_s=45, retries=9)
        with self.assertRaises(RpcError):
            rpc.view("job.testnet", "m")
        self.assertLessEqual(len(t.calls), 3)
        self.assertLessEqual(clk.now, 45 + 20)
        self.assertEqual([c[2] for c in t.calls][:3], [15, 15, 4.25][:len(t.calls)])

    def test_timeout_capped_by_remaining(self):
        clk = FakeClock()
        t = FakeTransport(raw(OK_VIEW))
        NearRpc(transport=t, clock=clk, sleep=clk.sleep, timeout_s=15, deadline_s=5).view("job.testnet", "m")
        self.assertEqual(t.calls[0][2], 5)


class ValidationTests(unittest.TestCase):
    def test_rejected_before_transport(self):
        rpc, t = client()
        bad = [
            lambda: rpc.view("Bad_Account", "m"), lambda: rpc.view("a", "m"),
            lambda: rpc.view("a" * 65, "m"), lambda: rpc.view("a..b", "m"),
            lambda: rpc.view("job.testnet", "1bad"), lambda: rpc.view("job.testnet", "a-b"),
            lambda: rpc.view("job.testnet", "m", finality="nope"),
            lambda: rpc.view("job.testnet", "m", args=[1]),
            lambda: rpc.view("job.testnet", "m", args={"x": object()}),
            lambda: rpc.view_account("BAD"), lambda: rpc.view_access_keys("x y"),
            lambda: rpc.block(finality="x"),
            lambda: rpc.tx_status("0OIl" * 10, "job.testnet"), lambda: rpc.tx_status("abc", "job.testnet"),
            lambda: rpc.tx_status(TX, "BAD"),
        ]
        for fn in bad:
            with self.assertRaises(RpcError):
                fn()
        self.assertEqual(t.calls, [])

    def test_urls(self):
        for url in ("http://rpc.example.com", "ftp://x", "rpc.example.com", "https://", "http://localhost.evil.com"):
            with self.assertRaises(RpcError, msg=url):
                NearRpc(rpc_url=url)
        for url in ("http://127.0.0.1:3030", "http://localhost:3030", "http://[::1]:3030", "https://rpc.example.com"):
            self.assertEqual(NearRpc(rpc_url=url).rpc_url, url)

    def test_networks(self):
        self.assertEqual(NearRpc().rpc_url, near_rpc.NETWORKS["testnet"])
        self.assertEqual(NearRpc().network, "testnet")
        with self.assertRaises(RpcError):
            NearRpc(network="mainnet")
        self.assertNotIn("mainnet", near_rpc.NETWORKS)
        self.assertEqual(NearRpc(network="custom", rpc_url="https://x.example").network, "custom")

    def test_call_allow_list(self):
        rpc, t = client()
        for method in ("broadcast_tx_commit", "send_tx", "broadcast_tx_async", "status"):
            with self.assertRaises(RpcError):
                rpc._call(method, {})
        with self.assertRaises(RpcError):
            rpc._call("query", {"request_type": "view_state"})
        with self.assertRaises(RpcError):
            rpc._call("query", {})
        self.assertEqual(t.calls, [])


class ShapeTests(unittest.TestCase):
    def test_view_account(self):
        result = {"amount": "1", "locked": "0", "code_hash": "c", "storage_usage": 5,
                  "block_height": 1, "block_hash": "h"}
        rpc, t = client(raw({"result": result}))
        self.assertEqual(rpc.view_account("a.testnet", "optimistic"), result)
        self.assertEqual(t.calls[0][1]["params"],
                         {"request_type": "view_account", "finality": "optimistic", "account_id": "a.testnet"})

    def test_view_account_error(self):
        rpc, _ = client(raw({"result": {"error": "account a.testnet does not exist while viewing"}}))
        with self.assertRaisesRegex(RpcError, "does not exist"):
            rpc.view_account("a.testnet")

    def test_view_access_keys(self):
        result = {"keys": [{"public_key": "ed25519:x", "access_key": {"nonce": 1, "permission": "FullAccess"}}],
                  "block_height": 1, "block_hash": "h"}
        rpc, t = client(raw({"result": result}))
        self.assertEqual(rpc.view_access_keys("a.testnet"), result)
        self.assertEqual(t.calls[0][1]["params"]["request_type"], "view_access_key_list")

    def test_block_timestamps(self):
        for header in ({"height": 9, "hash": "H", "timestamp": 1_700_000_000_123_456_789},
                       {"height": 9, "hash": "H", "timestamp_nanosec": "1700000000123456789"}):
            rpc, t = client(raw({"result": {"header": header}}))
            self.assertEqual(rpc.block(), {"height": 9, "hash": "H", "timestamp_ms": 1_700_000_000_123})
            self.assertEqual((t.calls[0][1]["method"], t.calls[0][1]["params"]), ("block", {"finality": "final"}))

    def test_block_malformed(self):
        for result in ({}, {"header": {"height": 1, "hash": "h"}}):
            rpc, _ = client(raw({"result": result}))
            with self.assertRaises(RpcError):
                rpc.block()

    def test_tx_status(self):
        rpc, t = client(raw({"result": {"status": {"SuccessValue": ""}}}))
        self.assertEqual(rpc.tx_status(TX, "a.testnet"), {"status": {"SuccessValue": ""}})
        self.assertEqual((t.calls[0][1]["method"], t.calls[0][1]["params"]),
                         ("tx", {"tx_hash": TX, "sender_account_id": "a.testnet", "wait_until": "FINAL"}))

    def test_explorer_urls(self):
        self.assertEqual(near_rpc.explorer_tx_url("testnet", TX), f"https://testnet.nearblocks.io/txns/{TX}")
        self.assertEqual(near_rpc.explorer_account_url("testnet", "a.testnet"),
                         "https://testnet.nearblocks.io/address/a.testnet")


class ReadLimitedTests(unittest.TestCase):
    def test_limit(self):
        self.assertEqual(near_rpc._read_limited(io.BytesIO(b"abc"), 3), b"abc")
        with self.assertRaises(RpcError):
            near_rpc._read_limited(io.BytesIO(b"abcd"), 3)
        self.assertEqual(near_rpc.MAX_RESPONSE_BYTES, 1_048_576)


if __name__ == "__main__":
    unittest.main()
