from __future__ import annotations

import json
import unittest
from decimal import Decimal

from _test_fake_mainnet_store import FakeMainnetStore
from ops.repair_mainnet_unsigned_drafts import (
    _PRODUCTION_ACK_VALUE,
    _repair_refusal_reason,
    _safe_report,
)


_NETWORK = "ethereum_mainnet"
_FROM = "0x" + "ab" * 20
_DEST = "0x" + "cd" * 20


def _register(store: FakeMainnetStore, *, nonce: int = 0):
    return store.register_draft(
        vault_id="v-1",
        network_id=_NETWORK,
        sender_address=_FROM,
        asset="ETH",
        destination_address=_DEST,
        value_wei=1,
        data_hex="0x",
        nonce=nonce,
        gas_limit=21000,
        gas_price=1_000_000_000,
        chain_id=1,
        transaction_to=_DEST,
        ttl_secs=600,
    )


class MainnetDraftStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FakeMainnetStore()

    def test_abandoned_unsigned_draft_does_not_block_new_draft(self):
        first = _register(self.store, nonce=0)
        self.assertIsNotNone(first)

        second = _register(self.store, nonce=1)
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)

        old, old_err = self.store.load_draft_readonly(
            draft_id=first, vault_id="v-1", network_id=_NETWORK,
        )
        self.assertIsNone(old)
        self.assertEqual(old_err, "unknown_or_expired_draft")

    def test_active_signing_claim_still_blocks_new_draft(self):
        first = _register(self.store)
        claim, err = self.store.claim_draft(
            draft_id=first, vault_id="v-1", network_id=_NETWORK,
        )
        self.assertIsNotNone(claim)
        self.assertIsNone(err)

        second = _register(self.store, nonce=1)
        self.assertIsNone(second)

    def test_signed_unresolved_draft_still_blocks_new_draft(self):
        first = _register(self.store)
        claim, _ = self.store.claim_draft(
            draft_id=first, vault_id="v-1", network_id=_NETWORK,
        )
        consumed = self.store.consume_claimed_draft(
            draft_id=first, claim_token=claim, local_tx_hash="0x" + "12" * 32,
        )
        self.assertTrue(consumed)

        second = _register(self.store, nonce=1)
        self.assertIsNone(second)

    def test_explicitly_rejected_terminal_draft_does_not_block(self):
        first = _register(self.store)
        claim, _ = self.store.claim_draft(
            draft_id=first, vault_id="v-1", network_id=_NETWORK,
        )
        self.assertTrue(self.store.consume_claimed_draft(
            draft_id=first, claim_token=claim, local_tx_hash="0x" + "34" * 32,
        ))
        self.assertTrue(self.store.record_broadcast_outcome(
            draft_id=first, claim_token=claim, outcome="explicitly_rejected",
        ))

        second = _register(self.store, nonce=1)
        self.assertIsNotNone(second)

    def test_ciphertext_first_scope_uses_sender_lookup_hash(self):
        hash_a = b"a" * 32
        hash_b = b"b" * 32
        first = self.store.register_draft_ciphertext_first(
            vault_id="v-1",
            network_id=_NETWORK,
            sender_address_lookup_hash=hash_a,
            draft_payload_ciphertext=b"ct-a",
            nonce=0,
            gas_limit=21000,
            gas_price=1_000_000_000,
            chain_id=1,
        )
        self.assertIsNotNone(first)

        other_wallet = self.store.register_draft_ciphertext_first(
            vault_id="v-1",
            network_id=_NETWORK,
            sender_address_lookup_hash=hash_b,
            draft_payload_ciphertext=b"ct-b",
            nonce=0,
            gas_limit=21000,
            gas_price=1_000_000_000,
            chain_id=1,
        )
        self.assertIsNotNone(other_wallet)

        replacement = self.store.register_draft_ciphertext_first(
            vault_id="v-1",
            network_id=_NETWORK,
            sender_address_lookup_hash=hash_a,
            draft_payload_ciphertext=b"ct-a2",
            nonce=1,
            gas_limit=21000,
            gas_price=1_000_000_000,
            chain_id=1,
        )
        self.assertIsNotNone(replacement)
        self.assertNotEqual(first, replacement)

    def test_legacy_hashless_unsigned_ciphertext_draft_does_not_block(self):
        first = self.store.register_draft_ciphertext_first(
            vault_id="v-1",
            network_id=_NETWORK,
            sender_address_lookup_hash=b"a" * 32,
            draft_payload_ciphertext=b"ct-a",
            nonce=0,
            gas_limit=21000,
            gas_price=1_000_000_000,
            chain_id=1,
        )
        self.assertIsNotNone(first)
        self.store._drafts[first]["sender_address_lookup_hash"] = None

        replacement = self.store.register_draft_ciphertext_first(
            vault_id="v-1",
            network_id=_NETWORK,
            sender_address_lookup_hash=b"a" * 32,
            draft_payload_ciphertext=b"ct-a2",
            nonce=1,
            gas_limit=21000,
            gas_price=1_000_000_000,
            chain_id=1,
        )

        self.assertIsNotNone(replacement)
        self.assertNotEqual(first, replacement)
        old, old_err = self.store.load_draft_readonly(
            draft_id=first, vault_id="v-1", network_id=_NETWORK,
        )
        self.assertIsNone(old)
        self.assertEqual(old_err, "unknown_or_expired_draft")

    def test_legacy_hashless_signed_ciphertext_draft_still_blocks(self):
        first = self.store.register_draft_ciphertext_first(
            vault_id="v-1",
            network_id=_NETWORK,
            sender_address_lookup_hash=b"a" * 32,
            draft_payload_ciphertext=b"ct-a",
            nonce=0,
            gas_limit=21000,
            gas_price=1_000_000_000,
            chain_id=1,
        )
        self.assertIsNotNone(first)
        self.store._drafts[first]["sender_address_lookup_hash"] = None
        claim, err = self.store.claim_draft(
            draft_id=first, vault_id="v-1", network_id=_NETWORK,
        )
        self.assertIsNone(err)
        self.assertTrue(self.store.consume_claimed_draft(
            draft_id=first,
            claim_token=claim,
            local_tx_hash="0x" + "56" * 32,
        ))

        replacement = self.store.register_draft_ciphertext_first(
            vault_id="v-1",
            network_id=_NETWORK,
            sender_address_lookup_hash=b"a" * 32,
            draft_payload_ciphertext=b"ct-a2",
            nonce=1,
            gas_limit=21000,
            gas_price=1_000_000_000,
            chain_id=1,
        )

        self.assertIsNone(replacement)


class MainnetRepairToolSafetyTests(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "network_id": _NETWORK,
            "chain_id": 1,
            "consumed_at": None,
            "local_tx_hash": None,
            "broadcast_outcome": None,
            "claim_token": None,
            "claim_expires_at_active": False,
        }
        row.update(overrides)
        return row

    def _reason(self, row, **overrides):
        kwargs = {
            "draft_id": "draft-1",
            "is_production": False,
            "ack_value": "",
        }
        kwargs.update(overrides)
        return _repair_refusal_reason([row], **kwargs)

    def test_repair_allows_only_safe_unsigned_unbroadcast_draft(self):
        self.assertEqual(self._reason(self._row()), "")

    def test_repair_refuses_missing_exact_draft_id(self):
        self.assertEqual(
            self._reason(self._row(), draft_id=None),
            "apply_requires_exact_draft_id",
        )

    def test_repair_refuses_production_without_acknowledgement(self):
        self.assertEqual(
            self._reason(self._row(), is_production=True, ack_value=""),
            "production_ack_required",
        )
        self.assertEqual(
            self._reason(
                self._row(),
                is_production=True,
                ack_value=_PRODUCTION_ACK_VALUE,
            ),
            "",
        )

    def test_repair_refuses_signed_or_submitted_records(self):
        self.assertEqual(
            self._reason(self._row(local_tx_hash="0x" + "12" * 32)),
            "unsafe_draft_state",
        )
        self.assertEqual(
            self._reason(self._row(
                consumed_at=1,
                local_tx_hash="0x" + "34" * 32,
                broadcast_outcome="submitted",
            )),
            "unsafe_draft_state",
        )

    def test_repair_refuses_active_signing_claim(self):
        self.assertEqual(
            self._reason(self._row(
                claim_token="opaque",
                claim_expires_at_active=True,
            )),
            "unsafe_draft_state",
        )

    def test_repair_refuses_wrong_network_or_chain(self):
        self.assertEqual(
            self._reason(self._row(network_id="ethereum_sepolia")),
            "unsafe_draft_state",
        )
        self.assertEqual(
            self._reason(self._row(chain_id=11155111)),
            "unsafe_draft_state",
        )

    def test_repair_report_is_json_serializable(self):
        report = _safe_report([
            self._row(
                draft_id="draft-1",
                created_at=Decimal("1785420793.037522"),
                expires_at=Decimal("1785424393.037522"),
                nonce=1,
            ),
        ])
        json.dumps(report)
        self.assertEqual(report[0]["draftRef"], "draft-1")
        self.assertEqual(report[0]["createdAt"], 1785420793.037522)


if __name__ == "__main__":
    unittest.main()
