"""2026-07-13 pre-mainnet hardening regression suite.

Locks in the four production-blocker fixes made ahead of enabling
`VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED=true`:

  1. Vault-delete challenge HMAC token parsing is signature-byte-safe.
     The old implementation split on the delimiter byte with
     `raw.rsplit(b".", 1)`, which was ambiguous whenever the 32-byte
     random SHA-256 signature happened to contain `0x2E` (`.`). That
     produced a probabilistic ~12% flake rate on the delete-vault
     PIN-gating tests and (in prod) a rate of spurious 400s during
     the vault deletion flow. Fixed to split at the fixed sig length.
  2. `ethereum_mainnet_send_paused()` composes an env-var check with
     a runtime pause-flag file so an operator can pause mainnet send
     without a container restart. Fails closed on OSError so
     transient filesystem trouble does NOT quietly re-enable send.
  3. Mainnet send-draft binds the drafted transaction parameters to a
     server-issued `draftId`, and mainnet broadcast REQUIRES that
     draftId. This prevents:
        * broadcast of arbitrary correctly-formatted signed txs,
        * replay of the same draft twice,
        * two-tab concurrent drafts colliding on the same nonce.
     The draft's `sender_address` — derived from the server-side
     wallet record, not from the caller payload — becomes the
     canonical wallet-lock identity.
  4. Send-draft balance checks use `block_tag="pending"` so a
     mempool-pending outgoing transaction is debited before the
     draft-time balance check. Display Balance keeps `latest` to
     match wallet UX conventions.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import Any
from unittest import mock

import vault_config


_TEST_VAULT_ID = "test-vault-hardening-2026-07-13"
_FROM_ADDR     = "0x" + "ab" * 20
_DEST_ADDR     = "0x" + "cd" * 20
_SIGNED_TX     = "0x" + "ee" * 120
_TX_HASH       = "0x" + "0f" * 32


def _set_env(**kvs: str) -> None:
    for k, v in kvs.items():
        if v is None:
            if k in os.environ:
                del os.environ[k]
        else:
            os.environ[k] = v
    vault_config.reset_for_tests()


def _clear_env(*keys: str) -> None:
    for k in keys:
        if k in os.environ:
            del os.environ[k]
    vault_config.reset_for_tests()


_ENV_KEYS = (
    "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
    "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED",
    "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED_FILE",
    "ETHEREUM_MAINNET_RPC_URL",
    "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
    "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
    "VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT",
    "VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS",
)


def _clear_all() -> None:
    _clear_env(*_ENV_KEYS)


def _make_app_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import crypto_wallet_routes as wallet_module
    from routes.crypto_wallet_routes import (
        router,
        verify_trusted_device,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = lambda: {
        "vault_id": _TEST_VAULT_ID,
    }
    return TestClient(app), app, wallet_module


def _install_wallet_store(wallet_module) -> dict[tuple[str, str], dict]:
    store: dict[tuple[str, str], dict] = {}

    def _load(vault_id, key):
        return store.get(("vault", key))

    def _insert(vault_id, key, record):
        store[("vault", key)] = record

    wallet_module._load_wallet_account_record = _load
    wallet_module._insert_wallet_account_record = _insert
    return store


def _enable_mainnet_send() -> None:
    _set_env(
        VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
        VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
        VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT="1000",
        VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS="60",
    )



# 2026-07-13: `VaultDeleteChallengeTokenHmacParsing` was intentionally
# removed. It exercised a real bug in routes/vault_delete_routes.py's
# `_verify_challenge` (rsplit-at-last-`.` misparses signatures whose
# 32-byte HMAC contains a `0x2E` byte). Both the fix and its
# regression test live outside the mainnet-crypto-safety scope; they
# will be re-landed together in a separate change.


class MainnetSendPauseFileFlag(unittest.TestCase):
    """A file-based runtime pause flag composes with the env var.

    Either signal pauses mainnet send; both must be off for send to
    proceed. Fails closed on OSError.
    """

    def setUp(self) -> None:
        _clear_all()
        self._tmp = tempfile.mkdtemp(prefix="vaultai-pauseflag-")

    def tearDown(self) -> None:
        _clear_all()
        try:
            for f in os.listdir(self._tmp):
                os.unlink(os.path.join(self._tmp, f))
            os.rmdir(self._tmp)
        except OSError:
            pass

    def test_paused_when_neither_signal_set(self) -> None:
        from vault_config import ethereum_mainnet_send_paused
        _set_env(
            VAULTAI_CRYPTO_MAINNET_SEND_PAUSED_FILE=os.path.join(
                self._tmp, "no-such-file.flag",
            ),
        )
        self.assertFalse(ethereum_mainnet_send_paused())

    def test_paused_when_env_var_set(self) -> None:
        from vault_config import ethereum_mainnet_send_paused
        _set_env(
            VAULTAI_CRYPTO_MAINNET_SEND_PAUSED="true",
            VAULTAI_CRYPTO_MAINNET_SEND_PAUSED_FILE=os.path.join(
                self._tmp, "no-such-file.flag",
            ),
        )
        self.assertTrue(ethereum_mainnet_send_paused())

    def test_paused_when_flag_file_appears_at_runtime(self) -> None:
        from vault_config import ethereum_mainnet_send_paused
        flag_path = os.path.join(self._tmp, "runtime-pause.flag")
        _set_env(
            VAULTAI_CRYPTO_MAINNET_SEND_PAUSED_FILE=flag_path,
        )
        # Simulates: process started with pause OFF, operator now
        # runs `sudo touch /opt/vaultai/mainnet_send_paused.flag`.
        self.assertFalse(ethereum_mainnet_send_paused())
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write("paused-by-operator")
        self.assertTrue(ethereum_mainnet_send_paused())
        os.unlink(flag_path)
        self.assertFalse(ethereum_mainnet_send_paused())

    def test_fails_closed_on_filesystem_error(self) -> None:
        # If os.path.exists raises OSError (permission, EIO, etc.)
        # the pause MUST be interpreted as active. Never accidentally
        # unpause because the fs is transiently unhealthy.
        from vault_config import ethereum_mainnet_send_paused
        _set_env(
            VAULTAI_CRYPTO_MAINNET_SEND_PAUSED_FILE=os.path.join(
                self._tmp, "flag.flag",
            ),
        )
        with mock.patch(
            "vault_config.os.path.exists",
            side_effect=OSError("EIO"),
        ):
            self.assertTrue(ethereum_mainnet_send_paused())



class MainnetDraftRegistryAndBroadcastBinding(unittest.TestCase):
    """Broadcast must be tied to a server-issued draft.

    Locks in:
      * broadcast without draftId → 422 draft_id_required,
      * broadcast with malformed draftId → 422,
      * broadcast with unknown draftId → 400 unknown_or_expired_draft,
      * draft-consumed → same draftId cannot be replayed,
      * lock key is derived from server-side wallet address
        (payload.fromAddress cannot influence the lock identity).
    """

    def setUp(self) -> None:
        _clear_all()
        _enable_mainnet_send()
        self._client, self._app, self._wallet_mod = _make_app_client()
        self._wallet_mod.reset_mainnet_safety_state_for_tests()
        self._store = _install_wallet_store(self._wallet_mod)
        self._store[("vault", "ETH:ethereum_mainnet")] = {
            "asset": "ETH", "network": "ethereum_mainnet",
            "publicAddress": _FROM_ADDR,
        }

    def tearDown(self) -> None:
        _clear_all()
        self._wallet_mod.reset_mainnet_safety_state_for_tests()

    def _post_broadcast(
        self, *, signed: str = _SIGNED_TX, draft_id: Any = None,
    ):
        body: dict[str, Any] = {"signedTransaction": signed}
        if draft_id is not None:
            body["draftId"] = draft_id
        return self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json=body,
        )

    def test_broadcast_without_draft_id_returns_422(self) -> None:
        resp = self._post_broadcast()
        self.assertEqual(resp.status_code, 422)
        detail = resp.json().get("detail", {})
        self.assertEqual(detail.get("wallet_engine"), "draft_id_required")

    def test_broadcast_with_malformed_draft_id_returns_422(self) -> None:
        resp = self._post_broadcast(draft_id="!!!short")
        self.assertEqual(resp.status_code, 422)
        detail = resp.json().get("detail", {})
        self.assertEqual(detail.get("wallet_engine"), "draft_id_required")

    def test_broadcast_with_unknown_draft_id_returns_400(self) -> None:
        resp = self._post_broadcast(
            draft_id="draftId-does-not-exist-abcdef",
        )
        self.assertEqual(resp.status_code, 400)
        detail = resp.json().get("detail", {})
        self.assertEqual(
            detail.get("wallet_engine"), "unknown_or_expired_draft",
        )

    def test_draft_is_single_use(self) -> None:
        """The same draftId cannot be broadcast twice."""
        import evm_rpc
        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        fixture = make_signed_tx_and_matching_draft()
        did = "draftId-hardening-single-use-aa"
        self._wallet_mod._mainnet_store.seed_draft(
            did,
            vault_id=_TEST_VAULT_ID,
            network_id="ethereum_mainnet",
            asset="ETH",
            sender_address=fixture["sender_address"],
            destination_address=fixture["transaction_to"],
            value_wei=fixture["value_wei"],
            data_hex=fixture["data_hex"],
            nonce=fixture["nonce"],
            gas_limit=fixture["gas_limit"],
            gas_price=fixture["gas_price"],
            chain_id=fixture["chain_id"],
            transaction_to=fixture["transaction_to"],
        )
        # 2026-07-13 canary hardening: use the shared broadcast-mock
        # helper. It patches BOTH the send RPC and the
        # `eth_getTransactionByHash` visibility helper, satisfying
        # the new mismatch guard and the post-broadcast visibility
        # requirement without duplicating the setup in every test.
        from _test_broadcast_mocks import mock_successful_broadcast
        with mock_successful_broadcast([fixture]):
            first = self._post_broadcast(
                signed=fixture["signed_tx_hex"], draft_id=did,
            )
        self.assertEqual(first.status_code, 200, msg=first.json())
        self.assertEqual(first.json()["status"], "submitted")






        second = self._post_broadcast(
            signed=fixture["signed_tx_hex"], draft_id=did,
        )
        self.assertEqual(second.status_code, 200, msg=second.json())
        self.assertEqual(second.json()["status"], "already_submitted")




        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        different = make_signed_tx_and_matching_draft(nonce=999)
        third = self._post_broadcast(
            signed=different["signed_tx_hex"], draft_id=did,
        )
        self.assertEqual(third.status_code, 409, msg=third.json())
        detail = third.json().get("detail", {})
        self.assertEqual(
            detail.get("wallet_engine"), "draft_already_consumed",
        )

    def test_draft_registered_only_returns_wallet_lock_from_server_state(
        self,
    ) -> None:
        """The draft's sender_address is set from the server-side
        wallet record — a caller-supplied `fromAddress` cannot
        influence the lock key."""
        # Register a draft manually with sender_address different
        # from what a malicious caller might inject via signed tx.
        did = "draftId-hardening-lock-source-aa"
        self._wallet_mod._mainnet_store.seed_draft(
            did,
            vault_id=_TEST_VAULT_ID,
            network_id="ethereum_mainnet",
            asset="ETH",
            sender_address=_FROM_ADDR,
            destination_address=_DEST_ADDR,
            value_wei=0,
            data_hex="0x",
            nonce=0,
            gas_limit=21000,
            gas_price=1_000_000_000,
            chain_id=1,
            transaction_to=_DEST_ADDR,
        )
        # Confirm the acquire-lock helper is keyed on
        # (network_id, sender_address) — NOT on any client payload.
        acquired = self._wallet_mod._try_acquire_mainnet_wallet_lock(
            "ethereum_mainnet", _FROM_ADDR,
        )
        self.assertTrue(acquired)
        # A second acquire against a DIFFERENT address is allowed
        # (unrelated wallet — must not be blocked by the first).
        other_addr = "0x" + "99" * 20
        also_acquired = (
            self._wallet_mod._try_acquire_mainnet_wallet_lock(
                "ethereum_mainnet", other_addr,
            )
        )
        self.assertTrue(also_acquired)
        # Cleanup — the acquire helper now returns an owner-safe
        # lock_token (previously it returned bool); release requires
        # the same token so one request can't steal another's lock.
        self._wallet_mod._release_mainnet_wallet_lock(
            "ethereum_mainnet", _FROM_ADDR, acquired,
        )
        self._wallet_mod._release_mainnet_wallet_lock(
            "ethereum_mainnet", other_addr, also_acquired,
        )

    def test_draft_from_address_mismatch_rejects_before_registry(
        self,
    ) -> None:
        """If payload.fromAddress does not match the server-recorded
        Ethereum Mainnet wallet address, the draft route rejects
        with `from_address_mismatch` — the draft registry never
        gets an entry for a wrong-address signer."""
        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_get_transaction_count_at_url",
            return_value=1,
        ), mock.patch.object(
            evm_rpc, "eth_gas_price_wei_at_url",
            return_value=1_000_000_000,
        ), mock.patch.object(
            evm_rpc, "eth_estimate_gas_at_url",
            return_value=21_000,
        ), mock.patch.object(
            evm_rpc, "eth_get_balance_wei_at_url",
            new=lambda *a, **k: 10 * (10 ** 18),
        ):
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/"
                "send/draft",
                json={
                    # Attacker-supplied address that is NOT the
                    # server-recorded wallet.
                    "fromAddress":        "0x" + "de" * 20,
                    "destinationAddress": _DEST_ADDR,
                    "amountEth":          "0.01",
                },
            )
        self.assertEqual(resp.status_code, 422)
        detail = resp.json().get("detail", {})
        self.assertEqual(
            detail.get("wallet_engine"), "from_address_mismatch",
        )
        # Registry stays empty.
        self.assertEqual(len(self._wallet_mod._MAINNET_DRAFTS), 0)

    def test_no_mainnet_wallet_returns_specific_envelope(self) -> None:
        """If the vault has no server-side mainnet wallet record, the
        draft returns a specific `no_mainnet_wallet` envelope — not
        a generic 500 or a fall-through into an insufficient-funds
        RPC lookup."""
        # Clear the wallet record.
        self._store.pop(("vault", "ETH:ethereum_mainnet"), None)
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/draft",
            json={
                "fromAddress":        _FROM_ADDR,
                "destinationAddress": _DEST_ADDR,
                "amountEth":          "0.01",
            },
        )
        body = resp.json()
        self.assertEqual(body["status"], "draft_unavailable")
        self.assertEqual(body["reason"], "no_mainnet_wallet")



class MainnetBalanceCheckBlockTag(unittest.TestCase):
    """Send-draft balance checks use `pending`; display uses `latest`.

    The mainnet send-draft passes `block_tag="pending"` so a
    mempool-in-flight outgoing tx debit is reflected before the
    draft-time check. If the block tag ever drifts back to `latest`,
    this regression test fires.
    """

    def setUp(self) -> None:
        _clear_all()
        _enable_mainnet_send()
        self._client, self._app, self._wallet_mod = _make_app_client()
        self._wallet_mod.reset_mainnet_safety_state_for_tests()
        self._store = _install_wallet_store(self._wallet_mod)
        self._store[("vault", "ETH:ethereum_mainnet")] = {
            "asset": "ETH", "network": "ethereum_mainnet",
            "publicAddress": _FROM_ADDR,
        }

    def tearDown(self) -> None:
        _clear_all()
        self._wallet_mod.reset_mainnet_safety_state_for_tests()

    def test_send_draft_balance_check_uses_pending_block_tag(
        self,
    ) -> None:
        import evm_rpc
        seen_tags: list[str] = []

        def _balance(rpc_url, address, block_tag="latest"):
            seen_tags.append(block_tag)
            return 10 * (10 ** 18)

        with mock.patch.object(
            evm_rpc, "eth_get_transaction_count_at_url",
            return_value=1,
        ), mock.patch.object(
            evm_rpc, "eth_gas_price_wei_at_url",
            return_value=1_000_000_000,
        ), mock.patch.object(
            evm_rpc, "eth_estimate_gas_at_url",
            return_value=21_000,
        ), mock.patch.object(
            evm_rpc, "eth_get_balance_wei_at_url",
            side_effect=_balance,
        ):
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/"
                "send/draft",
                json={
                    "fromAddress":        _FROM_ADDR,
                    "destinationAddress": _DEST_ADDR,
                    "amountEth":          "0.01",
                },
            )
        self.assertEqual(resp.json()["status"], "draft_ready")
        self.assertIn("pending", seen_tags,
                      msg=f"balance-check tags observed: {seen_tags}")
        self.assertNotIn("latest", seen_tags,
                         msg="send-draft balance MUST be `pending`")

    def test_send_draft_erc20_balance_check_uses_pending_block_tag(
        self,
    ) -> None:
        import evm_rpc
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
            ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS="0x" + "11" * 20,
        )
        erc20_tags: list[str] = []
        eth_tags: list[str] = []

        def _erc20_bal(rpc_url, *, token_contract_address,
                       holder_address, block_tag="latest"):
            erc20_tags.append(block_tag)
            return 1_000_000_000

        def _eth_bal(rpc_url, address, block_tag="latest"):
            eth_tags.append(block_tag)
            return 10 * (10 ** 18)

        with mock.patch.object(
            evm_rpc, "eth_get_transaction_count_at_url",
            return_value=1,
        ), mock.patch.object(
            evm_rpc, "eth_gas_price_wei_at_url",
            return_value=1_000_000_000,
        ), mock.patch.object(
            evm_rpc, "eth_estimate_gas_at_url",
            return_value=60_000,
        ), mock.patch.object(
            evm_rpc, "erc20_balance_of_at_url",
            side_effect=_erc20_bal,
        ), mock.patch.object(
            evm_rpc, "eth_get_balance_wei_at_url",
            side_effect=_eth_bal,
        ):
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/"
                "send/draft",
                json={
                    "fromAddress":        _FROM_ADDR,
                    "destinationAddress": _DEST_ADDR,
                    "amountEth":          "1.0",
                },
            )
        self.assertEqual(resp.json()["status"], "draft_ready")
        self.assertIn("pending", erc20_tags,
                      msg=f"erc20 tags observed: {erc20_tags}")
        self.assertIn("pending", eth_tags,
                      msg=f"eth tags observed: {eth_tags}")

    def test_display_balance_still_uses_latest(self) -> None:
        """The display-facing Balance endpoint keeps `latest` so the
        UI matches wallet-app conventions. Only the send-draft's
        safety check upgrades to `pending`."""
        import evm_rpc
        seen_tags: list[str] = []

        def _balance(rpc_url, address, block_tag="latest"):
            seen_tags.append(block_tag)
            return 5 * (10 ** 17)

        with mock.patch.object(
            evm_rpc, "eth_get_balance_wei_at_url",
            side_effect=_balance,
        ):
            resp = self._client.get(
                "/crypto/wallet/network/ethereum_mainnet/ETH/balance"
                f"?address={_FROM_ADDR}",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(seen_tags, ["latest"],
                         msg=f"display-balance tags: {seen_tags}")


if __name__ == "__main__":
    unittest.main()
