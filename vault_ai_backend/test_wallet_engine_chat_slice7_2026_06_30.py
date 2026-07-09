

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from wallet_engine_chat import (
    ALL_WALLET_CHAT_INTENTS,
    WALLET_CHAT_ENVELOPE_TYPE,
    WALLET_CHAT_INTENT_CLARIFY_NETWORK,
    WALLET_CHAT_INTENT_MONERO_SPECIAL,
    WALLET_CHAT_INTENT_OPEN_CRYPTO_WALLET,
    WALLET_CHAT_INTENT_RECEIVE_ADDRESS,
    WALLET_CHAT_INTENT_RECEIVE_QR,
    WALLET_CHAT_INTENT_SEND_DRAFT,
    WALLET_CHAT_INTENT_SHOW_BALANCE,
    WALLET_CHAT_INTENT_SHOW_TRANSACTIONS,
    WALLET_CHAT_INTENT_SHOW_WALLET,
    WALLET_CHAT_INTENT_UNSUPPORTED_ASSET,
    WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
    WALLET_CHAT_LIVE_ASSETS,
    WALLET_CHAT_MSG_CLARIFY_NETWORK,
    WALLET_CHAT_MSG_ENGINE_DISABLED_LITE,
    WALLET_CHAT_MSG_MAINNET_DISABLED,
    WALLET_CHAT_MSG_MONERO_SPECIAL,
    WALLET_CHAT_MSG_SEND_DRAFT,
    WALLET_CHAT_MSG_SEND_DRAFT_MISSING_FIELDS,
    WALLET_CHAT_MSG_TRANSACTIONS_NOT_CONNECTED,
    WALLET_CHAT_MSG_UNSUPPORTED_ASSET,
    WALLET_CHAT_NETWORK_MAINNET,
    WALLET_CHAT_NETWORK_SEPOLIA,
    compose_wallet_engine_chat_envelope,
    parse_wallet_engine_chat_message,
    safe_telemetry_label,
)


class WalletChatParserTests(unittest.TestCase):
                                                                             

    def test_W1_closed_set_intents(self):
        self.assertEqual(
            set(ALL_WALLET_CHAT_INTENTS),
            {
                "open_crypto_wallet",
                "show_wallet",
                "show_balance",
                "receive_address",
                "receive_qr",
                "send_draft",
                "show_transactions",
                "unsupported_asset",
                "unsupported_network",
                "monero_special",
                "clarify_network",
            },
        )

                                                                             
    def test_W2_show_my_crypto_wallet(self):
        out = parse_wallet_engine_chat_message("show my crypto wallet")
        self.assertIsNotNone(out)
        self.assertEqual(out["intent"], WALLET_CHAT_INTENT_SHOW_WALLET)
        self.assertEqual(out["network"], WALLET_CHAT_NETWORK_SEPOLIA)

    def test_W2b_open_my_crypto_vault(self):
        out = parse_wallet_engine_chat_message("open my crypto wallet")
        self.assertIsNotNone(out)
        self.assertEqual(
            out["intent"], WALLET_CHAT_INTENT_OPEN_CRYPTO_WALLET,
        )

                                                                             
    def test_W3_show_my_eth_balance(self):
        out = parse_wallet_engine_chat_message("show my ETH balance")
        self.assertIsNotNone(out)
        self.assertEqual(out["intent"], WALLET_CHAT_INTENT_SHOW_BALANCE)
        self.assertEqual(out["asset"], "ETH")
        self.assertEqual(out["network"], WALLET_CHAT_NETWORK_SEPOLIA)
        self.assertFalse(out["networkExplicit"])

                                                                             
    def test_W4_give_me_eth_receive_address(self):
        out = parse_wallet_engine_chat_message(
            "give me my ETH receive address",
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["intent"], WALLET_CHAT_INTENT_RECEIVE_ADDRESS)
        self.assertEqual(out["asset"], "ETH")

                                                                             
    def test_W5_show_my_eth_qr(self):
        out = parse_wallet_engine_chat_message("show my ETH QR")
        self.assertIsNotNone(out)
        self.assertEqual(out["intent"], WALLET_CHAT_INTENT_RECEIVE_QR)
        self.assertEqual(out["asset"], "ETH")

                                                                             
    def test_W6_show_usdt_erc20_balance(self):
        out = parse_wallet_engine_chat_message(
            "show my USDT ERC20 balance",
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["intent"], WALLET_CHAT_INTENT_SHOW_BALANCE)
        self.assertEqual(out["asset"], "USDT_ERC20")

                                                                             
    def test_W7_give_me_usdc_erc20_qr(self):
        out = parse_wallet_engine_chat_message(
            "give me my USDC ERC20 receive QR",
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["intent"], WALLET_CHAT_INTENT_RECEIVE_QR)
        self.assertEqual(out["asset"], "USDC_ERC20")

                                                                             
    def test_W8_send_eth_on_sepolia(self):
        dest = "0x" + "ab" * 20
        out = parse_wallet_engine_chat_message(
            f"send 0.01 ETH on Sepolia to {dest}",
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["intent"], WALLET_CHAT_INTENT_SEND_DRAFT)
        self.assertEqual(out["asset"], "ETH")
        self.assertEqual(out["network"], WALLET_CHAT_NETWORK_SEPOLIA)
        self.assertTrue(out["networkExplicit"])
        self.assertEqual(out["amount"], "0.01")
        self.assertEqual(out["destinationAddress"], dest)

                                                                             
    def test_W9_send_usdt_erc20(self):
        dest = "0x" + "cd" * 20
        out = parse_wallet_engine_chat_message(
            f"send 10 USDT ERC20 on Sepolia to {dest}",
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["intent"], WALLET_CHAT_INTENT_SEND_DRAFT)
        self.assertEqual(out["asset"], "USDT_ERC20")
        self.assertEqual(out["amount"], "10")
        self.assertEqual(out["destinationAddress"], dest)

                                                                             
    def test_W10_mainnet_send_blocked_when_send_flag_off(self):
                                                                
                                                 
        dest = "0x" + "ef" * 20
        out = parse_wallet_engine_chat_message(
            f"send 0.01 ETH on Ethereum Mainnet to {dest}",
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["intent"], WALLET_CHAT_INTENT_SEND_DRAFT)
        self.assertEqual(out["network"], WALLET_CHAT_NETWORK_MAINNET)
                                          
        env = compose_wallet_engine_chat_envelope(
            out, engine_enabled=True,
            mainnet_receive_enabled=True,
            mainnet_send_enabled=False,
        )
        self.assertEqual(
            env["intent"], WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
        )
        self.assertEqual(env["blockedReason"], "mainnet_disabled")

    def test_W10d_mainnet_send_passes_through_when_flag_on(self):
                                                                    
                                                             
        dest = "0x" + "ef" * 20
        out = parse_wallet_engine_chat_message(
            f"send 0.01 ETH on Ethereum Mainnet to {dest}",
        )
        env = compose_wallet_engine_chat_envelope(
            out, engine_enabled=True,
            mainnet_receive_enabled=True,
            mainnet_send_enabled=True,
        )
        self.assertEqual(env["intent"], WALLET_CHAT_INTENT_SEND_DRAFT)
        self.assertEqual(env["network"], WALLET_CHAT_NETWORK_MAINNET)
        self.assertEqual(env["destinationAddress"], dest)
        self.assertEqual(env["amount"], "0.01")
                                      
        self.assertIn("mainnet", env["message"].lower())
        self.assertIn("real funds", env["message"].lower())

    def test_W10b_balance_on_mainnet_is_blocked_when_flag_off(self):
        out = parse_wallet_engine_chat_message(
            "show my ETH balance on mainnet",
        )
        self.assertIsNotNone(out)
                                                  
        self.assertEqual(out["intent"], WALLET_CHAT_INTENT_SHOW_BALANCE)
        self.assertEqual(out["network"], WALLET_CHAT_NETWORK_MAINNET)
                                                                
        env = compose_wallet_engine_chat_envelope(
            out, engine_enabled=True, mainnet_receive_enabled=False,
        )
        self.assertEqual(
            env["intent"], WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
        )

    def test_W10c_balance_on_mainnet_allowed_when_flag_on(self):
                                                                   
                                                                   
        out = parse_wallet_engine_chat_message(
            "show my ETH balance on mainnet",
        )
        env = compose_wallet_engine_chat_envelope(
            out, engine_enabled=True, mainnet_receive_enabled=True,
        )
        self.assertEqual(env["intent"], WALLET_CHAT_INTENT_SHOW_BALANCE)
        self.assertEqual(env["network"], WALLET_CHAT_NETWORK_MAINNET)
                                                 
        self.assertIn("Mainnet", env["message"])
        self.assertNotIn("Sepolia", env["message"])

                                                                             
    def test_W11_unsupported_assets(self):
        for asset_word, canonical in [
            ("Bitcoin", "BTC"),
            ("BTC", "BTC"),
            ("Solana", "SOL"),
            ("BNB", "BNB"),
        ]:
            out = parse_wallet_engine_chat_message(
                f"show my {asset_word} balance",
            )
            self.assertIsNotNone(out, msg=f"asset_word={asset_word}")
            self.assertEqual(
                out["intent"], WALLET_CHAT_INTENT_UNSUPPORTED_ASSET,
                msg=f"asset_word={asset_word}",
            )
            self.assertEqual(out["asset"], canonical)

    def test_W11b_xmr_is_monero_special(self):
        out = parse_wallet_engine_chat_message("show my Monero balance")
        self.assertIsNotNone(out)
        self.assertEqual(out["intent"], WALLET_CHAT_INTENT_MONERO_SPECIAL)
        self.assertEqual(out["asset"], "XMR")

                                                                             
    def test_W12_parser_output_does_not_echo_message(self):
        original = "send 0.01 ETH to 0xabababababababababababababababababababab"
        out = parse_wallet_engine_chat_message(original)
        self.assertIsNotNone(out)
                                                                  
                   
        for k, v in out.items():
            if isinstance(v, str):
                self.assertNotEqual(
                    v, original,
                    msg=f"Parser key {k} echoed the message verbatim",
                )

                                                                             
    def test_W13_safe_telemetry_label_carries_only_closed_set(self):
        dest = "0x" + "ab" * 20
        parsed = parse_wallet_engine_chat_message(
            f"send 0.05 ETH on Sepolia to {dest}",
        )
        label = safe_telemetry_label(parsed)
                                     
        self.assertEqual(
            label, "intent=send_draft|asset=ETH|network=ethereum_sepolia",
        )
                                                                     
        self.assertNotIn("0x", label)
        self.assertNotIn("0.05", label)

    def test_W13b_safe_telemetry_label_strips_mutated_fields(self):
        label = safe_telemetry_label({
            "intent":  "send_draft_dropbox_secrets",           
            "asset":   "fake_asset",                           
            "network": "polkadot",                             
        })
                                                                    
                               
        self.assertIn("intent=unknown", label)
        self.assertIn("asset=unknown", label)
        self.assertIn("network=unknown", label)

                                                                             
    def test_W14_envelope_never_carries_sensitive_keys(self):
        dest = "0x" + "ab" * 20
        parsed = parse_wallet_engine_chat_message(
            f"send 0.01 ETH on Sepolia to {dest}",
        )
        envelope = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
        )
        banned_keys = (
            "privateKey", "private_key", "seedPhrase",
            "mnemonic", "recoveryPhrase", "encryptedWalletSecret",
            "signedTransaction",
        )
        for k in banned_keys:
            self.assertNotIn(
                k, envelope, msg=f"Envelope must not carry {k}",
            )
                                                                   
        as_json = json.dumps(envelope)
        for k in banned_keys:
            self.assertNotIn(k, as_json)

                                                                             
    def test_W15_send_draft_missing_fields(self):
                     
        parsed = parse_wallet_engine_chat_message("send 0.01 ETH")
        envelope = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
        )
        self.assertEqual(envelope["intent"], WALLET_CHAT_INTENT_SEND_DRAFT)
        self.assertEqual(envelope["blockedReason"], "missing_send_fields")
        self.assertEqual(
            envelope["message"], WALLET_CHAT_MSG_SEND_DRAFT_MISSING_FIELDS,
        )
                    
        parsed = parse_wallet_engine_chat_message(
            "send ETH to 0xababababababababababababababababababababab",
        )
        envelope = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
        )
        self.assertEqual(envelope["blockedReason"], "missing_send_fields")

                                                                             
    def test_W16_engine_disabled_returns_lite_escape_hatch(self):
        for raw in [
            "show my ETH balance",
            "show my crypto wallet",
            "send 0.01 ETH on Sepolia to "
            "0xababababababababababababababababababababab",
        ]:
            parsed = parse_wallet_engine_chat_message(raw)
            envelope = compose_wallet_engine_chat_envelope(
                parsed, engine_enabled=False,
            )
            self.assertEqual(
                envelope["type"], WALLET_CHAT_ENVELOPE_TYPE,
            )
            self.assertEqual(envelope["engineEnabled"], False)
            self.assertEqual(envelope["blockedReason"], "engine_disabled")
            self.assertEqual(
                envelope["message"], WALLET_CHAT_MSG_ENGINE_DISABLED_LITE,
            )
                                                                  
            self.assertIsNone(envelope["amount"])
            self.assertIsNone(envelope["destinationAddress"])

                                                                             
    def test_W17_show_transactions_honest_copy(self):
        parsed = parse_wallet_engine_chat_message("show my ETH transactions")
        envelope = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
        )
        self.assertEqual(
            envelope["intent"], WALLET_CHAT_INTENT_SHOW_TRANSACTIONS,
        )
        self.assertEqual(
            envelope["message"], WALLET_CHAT_MSG_TRANSACTIONS_NOT_CONNECTED,
        )
                                                              
        self.assertNotIn("0x", envelope["message"])

                                                                             
    def test_W18_source_guard_no_signing_imports(self):
        src = Path(__file__).parent / "wallet_engine_chat.py"
        text = src.read_text(encoding="utf-8")
        banned_imports = (
            "eth_account", "web3", "ethereum_transaction",
            "ethereum_sepolia_proxy", "ethereum_wallet",
            "eth_keys", "send_raw_transaction",
            "sign_legacy_eth_transaction",
        )
                                                                 
                         
        scrubbed = re.sub(r"#.*$", "", text, flags=re.MULTILINE)
        scrubbed = re.sub(
            r'"""(.*?)"""', "", scrubbed, flags=re.DOTALL,
        )
        scrubbed = re.sub(
            r"'''(.*?)'''", "", scrubbed, flags=re.DOTALL,
        )
        for name in banned_imports:
            self.assertNotIn(
                name, scrubbed,
                msg=f"wallet_engine_chat.py must not import {name}",
            )

                                                                             
    def test_W19_main_chat_fastpath_does_not_log_payload(self):
        src = Path(__file__).parent / "main.py"
        text = src.read_text(encoding="utf-8")
        marker = "parse_wallet_engine_chat_message"
        idx = text.find(marker)
        self.assertGreater(idx, -1)
                                                            
                   
        block = text[idx:idx + 8000]
        for banned in (
            "decrypted_message",
            "destinationAddress",
            "_wallet_parsed[",
            ".get('amount')",
            "_wallet_parsed['amount']",
            "_wallet_parsed['destinationAddress']",
        ):
                                                                   
                                                                  
            self.assertNotIn(
                f"logger.info({banned!r}", block,
                msg=f"Fast-path must not log {banned}",
            )
            self.assertNotIn(
                f"print({banned}", block,
                msg=f"Fast-path must not print {banned}",
            )
                                             
        self.assertIn("safe_telemetry_label", block)

                                                                             
    def test_W20_unsupported_network_envelope_does_not_carry_address(self):
        dest = "0x" + "fe" * 20
        parsed = parse_wallet_engine_chat_message(
            f"send 0.01 ETH on mainnet to {dest}",
        )
        envelope = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
        )
        self.assertEqual(
            envelope["intent"], WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
        )
        self.assertEqual(envelope["blockedReason"], "mainnet_disabled")
                                                             
                                                                 
        self.assertIsNone(envelope["destinationAddress"])
        self.assertIsNone(envelope["amount"])
                               
        self.assertEqual(envelope["message"], WALLET_CHAT_MSG_MAINNET_DISABLED)

    def test_W20b_unsupported_asset_envelope_uses_pinned_copy(self):
        parsed = parse_wallet_engine_chat_message("show my Bitcoin balance")
        envelope = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
        )
        self.assertEqual(
            envelope["intent"], WALLET_CHAT_INTENT_UNSUPPORTED_ASSET,
        )
                                                                       
        self.assertEqual(
            envelope["message"],
            WALLET_CHAT_MSG_UNSUPPORTED_ASSET.format(asset_label="Bitcoin"),
        )

    def test_W20c_monero_envelope_uses_pinned_copy(self):
                                                               
                                                                  
        for phrasing in [
            "I want to send Monero",
            "send Monero to 0xababababababababababababababababababababab",
            "show my Monero balance",
        ]:
            parsed = parse_wallet_engine_chat_message(phrasing)
            envelope = compose_wallet_engine_chat_envelope(
                parsed, engine_enabled=True,
            )
            self.assertEqual(
                envelope["intent"], WALLET_CHAT_INTENT_MONERO_SPECIAL,
                msg=f"phrasing={phrasing!r}",
            )
            self.assertEqual(
                envelope["message"], WALLET_CHAT_MSG_MONERO_SPECIAL,
            )
            self.assertEqual(envelope["blockedReason"], "monero_special")

                                                                           
    def test_send_draft_envelope_prefills_fields(self):
        dest = "0x" + "12" * 20
        parsed = parse_wallet_engine_chat_message(
            f"send 0.25 ETH on Sepolia to {dest}",
        )
        envelope = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
        )
        self.assertEqual(envelope["intent"], WALLET_CHAT_INTENT_SEND_DRAFT)
        self.assertEqual(envelope["asset"], "ETH")
        self.assertEqual(envelope["network"], WALLET_CHAT_NETWORK_SEPOLIA)
        self.assertEqual(envelope["amount"], "0.25")
        self.assertEqual(envelope["destinationAddress"], dest)
        self.assertEqual(envelope["amountUnit"], "ETH")
        self.assertEqual(envelope["message"], WALLET_CHAT_MSG_SEND_DRAFT)
                                                                    
                         
        self.assertEqual(envelope["engineEnabled"], True)
        self.assertIsNone(envelope["blockedReason"])

                                        
    def test_receive_envelope_mentions_sepolia(self):
        parsed = parse_wallet_engine_chat_message(
            "give me my ETH receive address",
        )
        envelope = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
        )
        self.assertEqual(envelope["asset"], "ETH")
        self.assertIn("Sepolia", envelope["message"])

    def test_balance_envelope_mentions_sepolia(self):
        parsed = parse_wallet_engine_chat_message("show my ETH balance")
        envelope = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
        )
        self.assertEqual(envelope["intent"], WALLET_CHAT_INTENT_SHOW_BALANCE)
        self.assertIn("Sepolia", envelope["message"])

                             
    def test_live_assets_set_is_eth_usdt_usdc(self):
        self.assertEqual(
            WALLET_CHAT_LIVE_ASSETS,
            frozenset({"ETH", "USDT_ERC20", "USDC_ERC20"}),
        )

                                      
    def test_non_wallet_message_returns_none(self):
        for msg in [
            "what's the weather?",
            "summarize my pdfs",
            "save my netflix password",
            "",
        ]:
            self.assertIsNone(parse_wallet_engine_chat_message(msg))


if __name__ == "__main__":
    unittest.main()
