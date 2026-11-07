"""Synthetic TRX fee-balance checks; no chain calls or transactions."""

from routes import crypto_wallet_routes as route
import tron_rpc


ADDRESS = "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"


def test_trx_fee_balance_returns_exact_sun_without_wallet_creation(
    monkeypatch,
):
    monkeypatch.setenv("VAULTAI_CRYPTO_TRON_ENABLED", "true")
    monkeypatch.setenv("TRON_API_BASE_URL", "https://synthetic.invalid")
    calls = []

    def read_balance(base_url, api_key, address):
        calls.append((base_url, address))
        return 1_234_567

    monkeypatch.setattr(tron_rpc, "tron_get_trx_balance_sun_at_url", read_balance)
    result = route._tron_balance("TRX", ADDRESS, {"vault_id": "synthetic"})

    assert calls == [("https://synthetic.invalid", ADDRESS)]
    assert result["balanceStatus"] == "available"
    assert result["trxBalanceSun"] == "1234567"
    assert result["baseUnits"] == "1234567"
    assert result["availableAmount"] == "1.234567"
    assert result["asset"] == "TRX"
    assert not route._tron_supported_asset("TRX")


def test_trx_fee_balance_fails_closed_on_provider_error(monkeypatch):
    monkeypatch.setenv("VAULTAI_CRYPTO_TRON_ENABLED", "true")
    monkeypatch.setenv("TRON_API_BASE_URL", "https://synthetic.invalid")

    def unavailable(*_args):
        raise tron_rpc.TronRpcError("rpc_error")

    monkeypatch.setattr(tron_rpc, "tron_get_trx_balance_sun_at_url", unavailable)
    result = route._tron_balance("TRX", ADDRESS, {"vault_id": "synthetic"})

    assert result["balanceStatus"] == "unavailable"
    assert result["availableAmount"] is None
    assert "trxBalanceSun" not in result
    assert result["reason"] == "rpc_error"
