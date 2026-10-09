"""Real RPC adapter boundary exercised with synthetic HTTP only."""
import json
import httpx
import pytest
import evm_rpc


def install(monkeypatch, reply):
    seen = []
    def handle(_transport, request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=reply, request=request)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    return seen


def test_storage_read_whitelisted_and_batch_ids_reordered(monkeypatch):
    assert "eth_getStorageAt" in evm_rpc.ALLOWED_RPC_METHODS
    seen = install(monkeypatch, [
        {"id": 2, "jsonrpc": "2.0", "result": "0xabc"},
        {"id": 1, "jsonrpc": "2.0", "result": "0x1"}])
    result = evm_rpc.emit_readonly_rpc_batch_at_url("https://rpc.example.invalid", [
        ("eth_chainId", []), ("eth_getStorageAt", ["0x"+"ab"*20, "0x0", "0x123"])])
    assert [r["result"] for r in result] == ["0x1", "0xabc"]
    assert seen[0][1]["method"] == "eth_getStorageAt"


@pytest.mark.parametrize("reply", [
    {}, [], [{"id": 1, "jsonrpc": "2.0", "result": "0x1"}],
    [{"id": 1, "jsonrpc": "2.0", "result": "0x1"}]*2,
    [{"id": True, "jsonrpc": "2.0", "result": "0x1"}, {"id": 2, "jsonrpc": "2.0", "result": "0x1"}],
    [{"id": 1, "jsonrpc": "2.0", "error": "secret"}, {"id": 2, "jsonrpc": "2.0", "result": "0x1"}],
    [{"id": 1, "jsonrpc": "2.0"}, {"id": 2, "jsonrpc": "2.0", "result": "0x1"}],
])
def test_partial_duplicate_or_error_batch_never_accepted(monkeypatch, reply):
    install(monkeypatch, reply)
    with pytest.raises(evm_rpc.EvmRpcError) as failure:
        evm_rpc.emit_readonly_rpc_batch_at_url("https://rpc.example.invalid", [("eth_chainId", []), ("eth_blockNumber", [])])
    assert "secret" not in str(failure.value)


@pytest.mark.parametrize("method", ["eth_sendRawTransaction", "eth_sign", "eth_estimateGas", "personal_unlockAccount"])
def test_batch_can_never_dispatch_mutating_or_unsigned_authority_calls(monkeypatch, method):
    seen = install(monkeypatch, [])
    with pytest.raises(evm_rpc.EvmRpcError, match="method_forbidden"):
        evm_rpc.emit_readonly_rpc_batch_at_url("https://rpc.example.invalid", [(method, [])])
    assert seen == []
