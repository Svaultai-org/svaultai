"""Standalone loopback-only native PAXG test fixture, NEVER a production app.

Before start, review this file and migrate the explicitly disposable QA database.
Required env: VAULTAI_PAXG_LOOPBACK_FIXTURE=isolated-local-only and
VAULTAI_PAXG_TEST_DATABASE_URL=postgresql://svaultai_concierge_tests@127.0.0.1:55438/svaultai_paxg_transaction_qa
Run with a sanitized environment. No real account, signer secret, external RPC,
indexer, payment provider, or real-money broadcast is reachable. Only the real
PAXG encrypted-draft SQL/control flow is exercised against synthetic fixtures.
"""
import os
import base64
from pathlib import Path
import secrets
import sys
from urllib.parse import urlparse

BACKEND = Path(__file__).resolve().parents[1] / "vault_ai_backend"
SENDER = "0x7e5f4552091a69125d5dfcb7b8c2659029395bdf"
NETWORK = "ethereum_mainnet"
ASSET = "PAXG_ERC20"
VAULT = "paxg-native-isolated-fixture-" + secrets.token_hex(16)
AUTH = "native-paxg-fixture-only"
IDENTITY = ("svaultai_paxg_transaction_qa", "svaultai_concierge_tests", "127.0.0.1", 55438)


def create_app():
    if os.getenv("VAULTAI_PAXG_LOOPBACK_FIXTURE") != "isolated-local-only":
        raise RuntimeError("Explicit isolated fixture mode is required")
    dsn = os.getenv("VAULTAI_PAXG_TEST_DATABASE_URL", "")
    parsed = urlparse(dsn)
    if (parsed.scheme != "postgresql" or parsed.hostname != "127.0.0.1"
            or parsed.port != 55438 or parsed.path != "/svaultai_paxg_transaction_qa"
            or parsed.username != "svaultai_concierge_tests" or parsed.password is not None):
        raise RuntimeError("Only the explicitly disposable loopback QA database is permitted")
    if os.getenv("DATABASE_URL", dsn) != dsn:
        raise RuntimeError("DATABASE_URL must not identify another database")
    # Refuse an inherited credential-bearing environment, rather than quietly
    # overriding real provider credentials while carrying them in this process.
    if any(value and (name.endswith("API_KEY") or "PRIVATE_KEY" in name
                      or name in ("STRIPE_SECRET_KEY", "VAULT_SESSION_SECRET"))
           for name, value in os.environ.items()):
        raise RuntimeError("Sanitized environment required; provider/signing credentials are forbidden")
    os.environ.update({
        "DATABASE_URL": dsn, "PYTHON_DOTENV_DISABLED": "1",
        "VAULT_SESSION_SECRET": secrets.token_urlsafe(48),
        "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED": "true",
        "VAULTAI_ASSETS_PAXG_ENABLED": "true",
        "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED": "true",
        "VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED": "true",
        "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED": "true",
        "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED": "false",
        "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED_FILE": "/nonexistent-qa-fixture/pause",
        "VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT": "1000",
        "ETHEREUM_MAINNET_RPC_URL": "https://rpc.example.invalid/isolated-fixture",
    })
    sys.path.insert(0, str(BACKEND))
    import httpx
    import psycopg2
    from fastapi import Depends, FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
    import crypto_mainnet_control_store as store
    import evm_rpc
    import evm_transaction_history
    from evm_signed_tx_verify import compute_local_tx_hash
    import vault_config
    import verified_assets
    from crypto_entitlement import require_crypto_entitlement
    from device_gate import verify_trusted_device
    from routes import crypto_wallet_routes as routes

    def connect():
        conn = psycopg2.connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()")
                if cur.fetchone() != IDENTITY:
                    raise RuntimeError("QA database identity mismatch")
                cur.execute("SELECT version_num FROM alembic_version")
                if cur.fetchone() != ("0049_kag_encrypted_draft_binding",):
                    raise RuntimeError("QA database must already be migrated to reviewed head0049")
            conn.commit()
            return conn
        except Exception:
            conn.close()
            raise

    probe = connect()
    probe.close()

    def forbidden(*_args, **_kwargs):
        raise RuntimeError("External I/O and unrelated fixture mutations are forbidden")

    httpx.HTTPTransport.handle_request = forbidden
    evm_transaction_history._http_get = forbidden
    store.get_db = connect
    routes._mainnet_store = store
    routes.get_db = forbidden
    routes._save_wallet_account_record = forbidden
    vault_config._db_pause_override = lambda: False
    vault_config.reset_for_tests()
    verified_assets.reset_verification_cache()
    routes.reset_mainnet_safety_state_for_tests()
    counts = {"draft_estimates": 0, "fake_broadcast_calls": 0, "secret_reads": 0}
    submitted = set()
    wallet = {"encryptedWalletSecret": None}

    def record(vault_id, service):
        if vault_id != VAULT or service != "ETH:ethereum_mainnet" or not wallet["encryptedWalletSecret"]:
            return None
        return {"schema": "crypto_wallet_account_v1", "asset": "ETH", "network": NETWORK,
                "walletLabel": "Synthetic native fixture", "publicAddress": SENDER,
                "encryptedWalletSecret": wallet["encryptedWalletSecret"],
                "keyOrigin": "generated_client_side", "signingMode": "client_side",
                "backupStatus": "encrypted_backup_saved"}

    routes._load_wallet_account_record = record
    evm_rpc.eth_chain_id_at_url = lambda _url: 1
    evm_rpc.eth_block_number_at_url = lambda _url: 19_000_001
    evm_rpc.eth_get_transaction_count_at_url = lambda *_a, **_kw: 7
    evm_rpc.eth_gas_price_wei_at_url = lambda _url: 10**9
    evm_rpc.eth_get_balance_wei_at_url = lambda *_a, **_kw: 10**18
    evm_rpc.erc20_balance_of_at_url = lambda *_a, **_kw: 10 * 10**18

    def probe_contract(_url, method, _params):
        if method == "eth_getCode":
            return {"result": "0x60016000"}
        if method == "eth_call":
            return {"result": "0x" + format(18, "064x")}
        raise RuntimeError("Unexpected fake provider operation")

    evm_rpc._emit_rpc_at_url = probe_contract

    def estimate(*_a, **_kw):
        counts["draft_estimates"] += 1
        return 60_000

    evm_rpc.eth_estimate_gas_at_url = estimate

    def fake_broadcast(_url, raw):
        # This is intentionally NOT connected to a blockchain/provider.
        value = compute_local_tx_hash(raw)
        if value is None:
            raise RuntimeError("Invalid fixture signed transaction")
        counts["fake_broadcast_calls"] += 1
        submitted.add(value.lower())
        return value

    evm_rpc.eth_send_raw_transaction_at_url = fake_broadcast
    evm_rpc.eth_get_transaction_by_hash_at_url = lambda _url, value: (
        {"hash": value} if value.lower() in submitted else None)
    evm_rpc.eth_get_transaction_receipt_at_url = lambda _url, value: (
        {"status": "0x1", "blockNumber": "0x123"} if value.lower() in submitted else None)

    def principal(request: Request):
        if request.headers.get("authorization") != "Bearer " + AUTH:
            raise HTTPException(status_code=401, detail="Fixture bearer required")
        return {"vault_id": VAULT}

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(routes.router)
    app.dependency_overrides[verify_trusted_device] = principal
    app.dependency_overrides[require_crypto_entitlement] = principal
    base = f"/crypto/wallet/network/{NETWORK}/{ASSET}"
    allowed = {"/__qa/health", "/__qa/wallet-envelope", "/__qa/evidence",
               base + "/send/draft", base + "/send/broadcast", base + "/encrypted-secret"}

    @app.middleware("http")
    async def limit_fixture_surface(request: Request, call_next):
        if request.url.path not in allowed:
            return JSONResponse(status_code=404, content={"detail": "Not an allowed isolated fixture route"})
        if request.url.path == base + "/encrypted-secret":
            counts["secret_reads"] += 1
        return await call_next(request)

    @app.get("/__qa/health")
    def health():
        return {"isolated_qa": True, "native_fixture": True,
                "fixture": "paxg-encrypted-draft-v1", "database": IDENTITY[0],
                "network": NETWORK, "chain_id": 1, "external_rpc_disabled": True,
                "sender": SENDER}

    class WalletEnvelope(BaseModel):
        encryptedWalletSecret: str = Field(min_length=8, max_length=8192)
        model_config = {"extra": "forbid"}

    @app.post("/__qa/wallet-envelope")
    def install(payload: WalletEnvelope, _principal=Depends(principal)):
        # This fixture accepts only the client's versioned AES-GCM binary
        # envelope representation. It never unwraps it or accepts a key field.
        encoded = payload.encryptedWalletSecret
        try:
            decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Opaque encrypted envelope required") from None
        if len(decoded) < 29 or decoded[0] != 1:
            raise HTTPException(status_code=400, detail="Opaque encrypted envelope required")
        wallet["encryptedWalletSecret"] = payload.encryptedWalletSecret
        return {"installed": True, "isolated_qa": True, "storage": "process-memory-only"}

    @app.get("/__qa/evidence")
    def evidence(_principal=Depends(principal)):
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT count(*),count(*) FILTER(WHERE consumed_at IS NOT NULL),
                    bool_and(sender_address_lower IS NULL AND asset IS NULL AND destination_address IS NULL
                             AND value_wei_str IS NULL AND data_hex IS NULL AND transaction_to IS NULL),
                    bool_and(octet_length(paxg_intent_commitment)=32)
                    FROM crypto_mainnet_drafts WHERE vault_id=%s""", (VAULT,))
                total, consumed, metadata_null, binding_valid = cur.fetchone()
        return {"isolated_qa": True, "native_fixture": True, **counts,
                "draft_rows": total, "consumed_rows": consumed,
                "readable_metadata_all_null": metadata_null,
                "commitments_all_valid_length": binding_valid,
                "fake_transaction_hashes": sorted(submitted), "real_funds_sent": False}

    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=18082, log_level="warning", access_log=False)
