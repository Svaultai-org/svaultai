"""2026-07-13: Flutter <-> Python signed-transaction compatibility.

The mainnet broadcast route decodes the incoming signed transaction
using `evm_signed_tx_verify.decode_and_recover` and compares every
field to the drafted values. If the Flutter client's signer
emits a byte pattern that the Python decoder cannot read, ALL
mainnet sends would fail. This suite locks in bidirectional
compatibility for the currently-supported EIP-155 legacy format.

Approach:
  * A canonical test vector below encodes a specific set of legacy
    tx fields signed by the deterministic RFC 6979 signature scheme
    that both `eth_account` (Python, via `coincurve`) and pointycastle
    (Dart, used by `signLegacyEthTransaction`) produce.
  * This Python test feeds that exact vector into the decoder and
    asserts every field parses back to the original inputs.
  * The companion Dart test in
    `vault_ai_frontend/test/flutter_signer_backend_compat_test.dart`
    signs the SAME inputs with `signLegacyEthTransaction` and
    asserts the output is byte-identical to this same vector.

If either signer's output ever drifts from the vector, both tests
fail — surfacing a real client/backend incompatibility BEFORE it
reaches production mainnet broadcast.
"""

from __future__ import annotations

import unittest


CANONICAL_MAINNET_PRIV_KEY_HEX = "0x" + "00" * 31 + "01"
CANONICAL_MAINNET_SENDER      = "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"
CANONICAL_MAINNET_TO          = "0x1111111111111111111111111111111111111111"
CANONICAL_MAINNET_NONCE       = 42
CANONICAL_MAINNET_GAS_PRICE   = 30_000_000_000
CANONICAL_MAINNET_GAS_LIMIT   = 21_000
CANONICAL_MAINNET_VALUE_WEI   = 1_000_000_000_000_000
CANONICAL_MAINNET_DATA_HEX    = "0x"
CANONICAL_MAINNET_CHAIN_ID    = 1


CANONICAL_MAINNET_SIGNED_TX_HEX = (
    "0xf86b2a8506fc23ac0082520894"
    "1111111111111111111111111111111111111111"
    "87038d7ea4c680008026"
    "a039f4ba24838a18898f1585c090b3fe757ca26777469ff3f2b1051574528ebe9f"
    "a017d121ac8e32d562638af46baf25a8f97b72a3f1718ed0772509ffcddacc76e1"
)


class FlutterSignerBackendCompat(unittest.TestCase):

    def test_canonical_vector_decodes_via_verifier(self):
        from evm_signed_tx_verify import decode_and_recover
        d = decode_and_recover(CANONICAL_MAINNET_SIGNED_TX_HEX)
        self.assertIsNotNone(d,
            msg="canonical Flutter-compat vector must decode via "
                "evm_signed_tx_verify.decode_and_recover")
        self.assertEqual(d.nonce,     CANONICAL_MAINNET_NONCE)
        self.assertEqual(d.gas_price, CANONICAL_MAINNET_GAS_PRICE)
        self.assertEqual(d.gas_limit, CANONICAL_MAINNET_GAS_LIMIT)
        self.assertEqual(d.value_wei, CANONICAL_MAINNET_VALUE_WEI)
        self.assertEqual(d.chain_id_from_v, CANONICAL_MAINNET_CHAIN_ID)
        self.assertEqual(d.to_lower,
            CANONICAL_MAINNET_TO.lower())
        self.assertEqual(d.data_hex, "0x")
        self.assertEqual(
            d.recovered_sender_lower,
            CANONICAL_MAINNET_SENDER.lower(),
        )
        self.assertTrue(d.local_tx_hash.startswith("0x"))
        self.assertEqual(len(d.local_tx_hash), 66)

    def test_canonical_vector_verifies_against_matching_draft(self):
        from evm_signed_tx_verify import verify_signed_tx_against_draft
        draft = {
            "sender_address":      CANONICAL_MAINNET_SENDER,
            "transaction_to":      CANONICAL_MAINNET_TO,
            "value_wei":           CANONICAL_MAINNET_VALUE_WEI,
            "data_hex":            CANONICAL_MAINNET_DATA_HEX,
            "nonce":               CANONICAL_MAINNET_NONCE,
            "gas_limit":           CANONICAL_MAINNET_GAS_LIMIT,
            "gas_price":           CANONICAL_MAINNET_GAS_PRICE,
            "chain_id":            CANONICAL_MAINNET_CHAIN_ID,
        }
        result = verify_signed_tx_against_draft(
            raw_signed_tx_hex=CANONICAL_MAINNET_SIGNED_TX_HEX,
            draft=draft,
        )
        self.assertTrue(result.ok,
            msg=f"verify failed: reason={result.reason} field={result.field}")


    def test_canonical_vector_v_encodes_correct_chain_id(self):
        from evm_signed_tx_verify import decode_and_recover
        d = decode_and_recover(CANONICAL_MAINNET_SIGNED_TX_HEX)


        self.assertIn(d.v, (37, 38))

    def test_flipping_one_field_rejects(self):
        """A single-byte tweak that changes the value_wei must
        fail verification against a draft that expects the original
        value. Locks in that the decoder actually reads the value
        field."""
        from evm_signed_tx_verify import verify_signed_tx_against_draft
        draft = {
            "sender_address":      CANONICAL_MAINNET_SENDER,
            "transaction_to":      CANONICAL_MAINNET_TO,
            "value_wei":           CANONICAL_MAINNET_VALUE_WEI + 1,
            "data_hex":            CANONICAL_MAINNET_DATA_HEX,
            "nonce":               CANONICAL_MAINNET_NONCE,
            "gas_limit":           CANONICAL_MAINNET_GAS_LIMIT,
            "gas_price":           CANONICAL_MAINNET_GAS_PRICE,
            "chain_id":            CANONICAL_MAINNET_CHAIN_ID,
        }
        result = verify_signed_tx_against_draft(
            raw_signed_tx_hex=CANONICAL_MAINNET_SIGNED_TX_HEX,
            draft=draft,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "value_wei_mismatch")


if __name__ == "__main__":
    unittest.main()
