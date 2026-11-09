"""Read-only NEAR JSON-RPC client (standard library only).

Read-only by construction: ``_call`` is the single place that talks to the transport and it
refuses every JSON-RPC method outside {query, block, tx} and every query request type outside
{call_function, view_account, view_access_key_list}, so this module cannot broadcast a
transaction even if misused. Mainnet is deliberately not a preset.

Trust model, stated plainly: the answer of a single RPC node is trusted. There is no
light-client or state-proof verification, so a malicious or faulty node could return false data.
Only testnet is preset; any other endpoint must be passed explicitly via ``rpc_url``.
"""

import base64
import json
import re
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

NETWORKS = {"testnet": "https://rpc.testnet.fastnear.com"}
EXPLORERS = {"testnet": "https://testnet.nearblocks.io"}
MAX_RESPONSE_BYTES = 1_048_576
ALLOWED_METHODS = frozenset({"query", "block", "tx"})
ALLOWED_REQUEST_TYPES = frozenset({"call_function", "view_account", "view_access_key_list"})
FINALITIES = frozenset({"final", "optimistic"})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
ACCOUNT_ID = re.compile(r"(?=.{2,64}\Z)[a-z0-9]+([._-][a-z0-9]+)*\Z")
METHOD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,255}\Z")
TX_HASH = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,64}\Z")


class RpcError(RuntimeError):
    pass


def _read_limited(stream, limit=MAX_RESPONSE_BYTES):
    """Read at most ``limit`` bytes from a file-like object; RpcError if more are available."""
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise RpcError(f"Response larger than {limit} bytes")
    return data


def urllib_transport(url, body, timeout_s):
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept-Encoding": "identity",
        "User-Agent": "forecast-evidence-swarm"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            if response.status != 200:
                raise RpcError(f"HTTP status {response.status}")
            return _read_limited(response)
    except RpcError:
        raise
    except (urllib.error.URLError, socket.timeout, OSError, ValueError) as exc:
        raise RpcError(f"Transport failure: {exc}") from exc


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RpcError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _loads(raw, what):
    try:
        if not isinstance(raw, (bytes, bytearray)):
            raise TypeError("not bytes")
        return json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except RpcError:
        raise
    except (TypeError, UnicodeDecodeError, ValueError) as exc:
        raise RpcError(f"{what} is not valid UTF-8 JSON: {exc}") from exc


def _check(pattern, value, what):
    if type(value) is not str or not pattern.match(value):
        raise RpcError(f"Invalid {what}: {value!r}")
    return value


def _check_finality(finality):
    if finality not in FINALITIES:
        raise RpcError(f"Invalid finality: {finality!r}")
    return finality


def _describe_error(error):
    if type(error) is not dict:
        return str(error)
    cause = error.get("cause") if type(error.get("cause")) is dict else {}
    parts = [str(part) for part in (error.get("name"), cause.get("name"), error.get("message"),
                                    error.get("data")) if part not in (None, "")]
    return " | ".join(parts) or json.dumps(error, sort_keys=True)


def _int(value, what):
    if type(value) is not int:
        raise RpcError(f"Unexpected {what} in RPC response: {value!r}")
    return value


class NearRpc:
    def __init__(self, network="testnet", rpc_url=None, transport=None, timeout_s=15,
                 deadline_s=45, retries=2, clock=time.monotonic, sleep=time.sleep):
        if rpc_url is None:
            if network not in NETWORKS:
                raise RpcError(f"Unknown network without rpc_url: {network!r}")
            rpc_url = NETWORKS[network]
        if type(rpc_url) is not str:
            raise RpcError("rpc_url must be a string")
        parts = urlsplit(rpc_url)
        local = parts.scheme == "http" and (parts.hostname or "") in LOCAL_HOSTS
        if not (parts.scheme == "https" and parts.hostname or local):
            raise RpcError("RPC URL must be https:// (http:// only for localhost)")
        self.network, self.rpc_url = network, rpc_url
        self._transport = transport or urllib_transport
        self._timeout_s, self._deadline_s, self._retries = timeout_s, deadline_s, max(0, int(retries))
        self._clock, self._sleep = clock, sleep

    def _call(self, method, params):
        if method not in ALLOWED_METHODS:
            raise RpcError(f"JSON-RPC method not allowed (read-only client): {method!r}")
        if method == "query" and (type(params) is not dict
                                  or params.get("request_type") not in ALLOWED_REQUEST_TYPES):
            raise RpcError("Query request_type not allowed (read-only client)")
        body = json.dumps({"jsonrpc": "2.0", "id": "fes", "method": method, "params": params},
                          separators=(",", ":"), sort_keys=True).encode("utf-8")
        start = self._clock()
        for attempt in range(self._retries + 1):
            remaining = self._deadline_s - (self._clock() - start)
            if remaining <= 0:
                raise RpcError(f"Deadline of {self._deadline_s}s exceeded")
            try:
                raw = self._transport(self.rpc_url, body, min(self._timeout_s, remaining))
                break
            except RpcError:
                backoff = 0.25 * (2 ** attempt)
                if attempt >= self._retries or self._clock() - start + backoff >= self._deadline_s:
                    raise
                self._sleep(backoff)
        document = _loads(raw, "RPC response")
        if type(document) is not dict:
            raise RpcError("RPC response is not a JSON object")
        if "error" in document:
            raise RpcError(f"RPC error: {_describe_error(document['error'])}")
        if "result" not in document:
            raise RpcError("RPC response has neither result nor error")
        return document["result"]

    def _query(self, request_type, finality, **fields):
        result = self._call("query", {"request_type": request_type,
                                      "finality": _check_finality(finality), **fields})
        if type(result) is not dict:
            raise RpcError("Unexpected query result type")
        if "error" in result:
            raise RpcError(f"Query error: {result['error']}")
        return result

    def view(self, contract_id, method, args=None, finality="final"):
        _check(ACCOUNT_ID, contract_id, "account id")
        _check(METHOD_NAME, method, "method name")
        _check_finality(finality)
        if args is not None and type(args) is not dict:
            raise RpcError("args must be None or a dict")
        try:
            encoded = json.dumps({} if args is None else args, separators=(",", ":"),
                                 sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise RpcError(f"args not JSON-serialisable: {exc}") from exc
        result = self._query("call_function", finality, account_id=contract_id, method_name=method,
                             args_base64=base64.b64encode(encoded).decode("ascii"))
        data = result.get("result")
        if type(data) is not list or not all(type(b) is int and 0 <= b < 256 for b in data):
            raise RpcError("call_function result is not a byte list")
        value = _loads(bytes(data), "Contract return value")
        logs = result.get("logs", [])
        return {"value": value, "block_height": _int(result.get("block_height"), "block_height"),
                "block_hash": str(result.get("block_hash")), "logs": logs if type(logs) is list else []}

    def view_account(self, account_id, finality="final"):
        _check(ACCOUNT_ID, account_id, "account id")
        return self._query("view_account", finality, account_id=account_id)

    def view_access_keys(self, account_id, finality="final"):
        _check(ACCOUNT_ID, account_id, "account id")
        return self._query("view_access_key_list", finality, account_id=account_id)

    def block(self, finality="final"):
        result = self._call("block", {"finality": _check_finality(finality)})
        header = result.get("header") if type(result) is dict else None
        if type(header) is not dict:
            raise RpcError("Block result has no header")
        stamp = header.get("timestamp")
        if type(stamp) is not int:
            stamp = header.get("timestamp_nanosec")
            try:
                stamp = int(stamp)
            except (TypeError, ValueError) as exc:
                raise RpcError("Block header has no usable timestamp") from exc
        return {"height": _int(header.get("height"), "height"), "hash": str(header.get("hash")),
                "timestamp_ms": stamp // 1_000_000}

    def tx_status(self, tx_hash, sender_id):
        _check(TX_HASH, tx_hash, "tx hash")
        _check(ACCOUNT_ID, sender_id, "account id")
        result = self._call("tx", {"tx_hash": tx_hash, "sender_account_id": sender_id,
                                   "wait_until": "FINAL"})
        if type(result) is not dict:
            raise RpcError("Unexpected tx result type")
        return result


def explorer_tx_url(network, tx_hash):
    return f"{EXPLORERS[network]}/txns/{tx_hash}"


def explorer_account_url(network, account_id):
    return f"{EXPLORERS[network]}/address/{account_id}"
