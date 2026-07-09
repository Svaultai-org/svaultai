

from __future__ import annotations

import base64
import json
import logging
import unittest
from unittest.mock import patch

import vault_credential_draft as cdraft
import vault_secure_item_draft as sidraft
import vault_secure_item_save as vsi
import vault_complete_search as vcs
import main as main_mod


def _fake_encrypt(plain: str, key: bytes) -> str:
    k = key[0] if key else 0
    return base64.b64encode(
        bytes(b ^ k for b in plain.encode("utf-8")),
    ).decode("ascii")


def _fake_decrypt(blob: str, key: bytes) -> str:
    k = key[0] if key else 0
    raw = base64.b64decode(blob.encode("ascii"))
    return bytes(b ^ k for b in raw).decode("utf-8")


def _patch_crypto():
    return (
        patch("vault_core.encrypt_message", side_effect=_fake_encrypt),
        patch("vault_core.decrypt_message", side_effect=_fake_decrypt),
    )


class _IntegrationBase(unittest.TestCase):


    def setUp(self):
        self.key = b"\x07" * 32
        self._rows: list[dict] = []
        self._patches = _patch_crypto()
        for p in self._patches:
            p.start()
        sidraft._reset_store_for_test()
        cdraft._reset_store_for_test()
                                                                 
        self._log_records: list[logging.LogRecord] = []
        self._log_handler = self._make_handler()
        for name in (
            "vault_secure_item_save",
            "vault_secure_item_draft",
            "vault_secure_item_card_envelope",
            "vault_saved_item_taxonomy",
            "vault_saved_item_chat_intent",
            "vault_credential_draft",
            "vault_pending_draft_confirm",
            "vault_complete_search",
            "vault_chat_result_cards",
        ):
            log = logging.getLogger(name)
            log.addHandler(self._log_handler)
            log.setLevel(logging.DEBUG)

    def tearDown(self):
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass
        sidraft._reset_store_for_test()
        cdraft._reset_store_for_test()
        for name in (
            "vault_secure_item_save",
            "vault_secure_item_draft",
            "vault_secure_item_card_envelope",
            "vault_saved_item_taxonomy",
            "vault_saved_item_chat_intent",
            "vault_credential_draft",
            "vault_pending_draft_confirm",
            "vault_complete_search",
            "vault_chat_result_cards",
        ):
            logging.getLogger(name).removeHandler(self._log_handler)

    def _make_handler(self) -> logging.Handler:
        records = self._log_records

        class _Sink(logging.Handler):
            def emit(self, record):
                records.append(record)

        sink = _Sink(level=logging.DEBUG)
        sink.setLevel(logging.DEBUG)
        return sink

    def _exec(self, action, payload):
                                                           
        if action == "delete":
                                    
            self._rows = [
                r for r in self._rows
                if not (
                    r["vault_id"] == payload.get("vault_id")
                    and r["item_type"] == payload.get("item_type")
                    and (r.get("service") or "").lower()
                       == (payload.get("service") or "").lower()
                )
            ]
            return
        if action == "update":
                                                                   
            for r in self._rows:
                if (
                    r["vault_id"] == payload.get("vault_id")
                    and r["item_type"] == payload.get("item_type")
                    and (r.get("service") or "").lower()
                       == (payload.get("service") or "").lower()
                ):
                    r["encrypted_data"] = payload["encrypted_data"]
                    return
                                                    
                           
        self._rows.append(payload)

    def _reader(self, vault_id: str, category: str):
        out = []
        for i, r in enumerate(self._rows):
            if r.get("item_type") != category:
                continue
            out.append({
                "id":             f"row-{i}",
                "item_type":      r["item_type"],
                "service":        r["service"],
                "encrypted_data": r["encrypted_data"],
                "created_at":     1_700_000_000.0 + i,
            })
        return out

    def _send(self, *, message: str, tier: str = vsi.TIER_FREE):
        return vsi.route_secure_item_message(
            vault_id="v-int",
            key=self.key,
            user_message=message,
            db_executor=self._exec,
            db_reader=self._reader,
            user_tier=tier,
        )

    def _joined_logs(self) -> str:
        return "\n".join(r.getMessage() for r in self._log_records)

    def _assert_no_leak(self, *forbidden: str):
        joined = self._joined_logs()
        for needle in forbidden:
            with self.subTest(forbidden=needle):
                self.assertNotIn(needle, joined)


_INSTAGRAM_USER = "snoworchard686"
_INSTAGRAM_PASS = "YOWlu)c*XlqDjw6z%w6V"


class FlowAGeneratedLogin(_IntegrationBase):


    def _stage_draft_and_simulate_save(self):
                                                                      
                                                    
        cdraft.store_draft(
            vault_id="v-int",
            service_name="Instagram",
            username=_INSTAGRAM_USER,
            password=_INSTAGRAM_PASS,
        )
                                                                  
                                                                 
        latest = cdraft.get_draft(
            vault_id="v-int", service_name="Instagram",
        )
        self.assertIsNotNone(latest)
        self.assertEqual(latest.username, _INSTAGRAM_USER)
        self.assertEqual(latest.password, _INSTAGRAM_PASS)
                                                           
                                                                  
        envelope = {
            "category": "login",
            "title":    "Instagram",
            "fields":   {
                "username": _INSTAGRAM_USER,
                "password": _INSTAGRAM_PASS,
            },
            "notes":    None,
            "item_id":  "row-instagram",
        }
        encrypted = _fake_encrypt(
            json.dumps(envelope, ensure_ascii=False), self.key,
        )
        self._rows.append({
            "vault_id":       "v-int",
            "item_type":      "login",
            "service":        "Instagram",
            "encrypted_data": encrypted,
        })
        return {"band": vsi.BAND_SAVED}

    def test_flow_a_full_lifecycle(self):
                                                                     
        result = self._stage_draft_and_simulate_save()
        self.assertEqual(result["band"], vsi.BAND_SAVED)
                                                                   
        self.assertEqual(len(self._rows), 1)
        row = self._rows[0]
        self.assertEqual(row["item_type"], "login")
        self.assertEqual(row["service"], "Instagram")
        decoded = json.loads(
            _fake_decrypt(row["encrypted_data"], self.key),
        )
                                                                       
        self.assertEqual(decoded["category"], "login")
        self.assertEqual(decoded["title"], "Instagram")
        self.assertIsInstance(decoded["fields"], dict)
        self.assertEqual(
            decoded["fields"]["username"], _INSTAGRAM_USER,
        )
        self.assertEqual(
            decoded["fields"]["password"], _INSTAGRAM_PASS,
        )

                                     
        retrieve = self._send(message="show my Instagram login")
        self.assertEqual(retrieve["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(retrieve["envelope"])
        self.assertEqual(envelope["count"], 1)
        card = envelope["items"][0]
                                                             
        self.assertTrue(envelope["reveal"])
        self.assertEqual(
            card["preview"]["username"], _INSTAGRAM_USER,
        )
        self.assertEqual(
            card["preview"]["password"], _INSTAGRAM_PASS,
        )

                                                                         
        fields, _notes, _cat, _title = vsi._normalise_record_to_fields(
            decoded,
        )
        self.assertEqual(fields["username"], _INSTAGRAM_USER)
        self.assertEqual(fields["password"], _INSTAGRAM_PASS)

                                                                    
        new_password = "qB-r0t8t#new-pass#xz"
        new_envelope = dict(decoded)
        new_envelope["fields"] = dict(decoded["fields"])
        new_envelope["fields"]["password"] = new_password
        self._rows[0]["encrypted_data"] = _fake_encrypt(
            json.dumps(new_envelope, ensure_ascii=False), self.key,
        )
                                                         
        retrieve2 = self._send(message="show my Instagram login")
        env2 = json.loads(retrieve2["envelope"])
        self.assertEqual(env2["count"], 1)
        self.assertEqual(
            env2["items"][0]["preview"]["password"], new_password,
        )

                                                              
        before = len(self._rows)
        deleted = vsi._execute_delete_row(
            vault_id="v-int",
            item_type="login",
            service="Instagram",
            db_executor=self._exec,
        )
        self.assertEqual(deleted, 1)
        self.assertEqual(len(self._rows), before - 1)

                                                                      
        retrieve3 = self._send(message="show my Instagram login")
                                                                
                               
        self.assertNotEqual(retrieve3.get("band"), vsi.BAND_RETRIEVED)

                                                                
        self._assert_no_leak(_INSTAGRAM_USER, _INSTAGRAM_PASS, new_password)


_IMEI = "352099001761481"


class FlowBSecureItemImei(_IntegrationBase):

    def test_flow_b_imei_full_lifecycle(self):
                                               
        result = self._send(message=f"save my imei {_IMEI}")
        self.assertEqual(result["band"], vsi.BAND_DRAFTED)
                                                           
        confirm = self._send(message="save it")
        self.assertEqual(confirm["band"], vsi.BAND_SAVED)
        self.assertEqual(len(self._rows), 1)
        row = self._rows[0]
        self.assertEqual(row["item_type"], "imei")
        decoded = json.loads(
            _fake_decrypt(row["encrypted_data"], self.key),
        )
                                           
        self.assertIn("fields", decoded)
        self.assertEqual(decoded["fields"]["imei_1"], _IMEI)

                      
        retrieve = self._send(message="show my imei")
        self.assertEqual(retrieve["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(retrieve["envelope"])
        card = envelope["items"][0]
                                                                    
                                                                  
        self.assertEqual(card["type"], "imei")

                                                       
        deleted = vsi._execute_delete_row(
            vault_id="v-int",
            item_type="imei",
            service=row["service"],
            db_executor=self._exec,
        )
        self.assertEqual(deleted, 1)
                                                    
        retrieve2 = self._send(message="show my imei")
        self.assertNotEqual(retrieve2.get("band"), vsi.BAND_RETRIEVED)

                        
        self._assert_no_leak(_IMEI)


class FlowCIdPrecision(unittest.TestCase):


    _REAL_DL = (
        "STATE OF NEW YORK DRIVER LICENSE\n"
        "DL# 123-456-789  CLASS D\n"
        "DOB 01-01-1980  EXP 01-01-2030\n"
        "Holder: LOUIS IODATO\n"
        "Department of Motor Vehicles"
    )
    _REAL_PASSPORT = (
        "UNITED STATES OF AMERICA PASSPORT\n"
        "Passport No. 1234567\n"
        "Surname: IODATO\n"
        "Given Names: LOUIS\n"
        "Nationality: USA\n"
        "Date of Birth: 01 JAN 1980\n"
        "Place of Birth: New York, USA\n"
        "Date of Expiration: 01 JAN 2030\n"
        "Department of State"
    )

    def _row(self, *, file_id, file_name, extracted_text):
        return {
            "id":                    file_id,
            "file_name":             file_name,
            "saved_name":            file_name,
            "extracted_text":        extracted_text,
            "extracted_text_status": "complete",
            "content_type":          "application/pdf",
            "encrypted_file_data":   None,
            "storage_mode":          "inline",
        }

    def _run(self, *, rows, query):
        original_list = main_mod._list_uploaded_files_for_credential_search
        original_decrypt = vcs._decrypt_pdf_bytes
        main_mod._list_uploaded_files_for_credential_search = (
            lambda vid, k: list(rows)
        )
        vcs._decrypt_pdf_bytes = lambda r, k: None
        try:
            raw = vcs.find_in_vault(
                vault_id="v-int", key=b"\x00" * 32,
                query=query, doc_kind="id_photo",
            )
        finally:
            main_mod._list_uploaded_files_for_credential_search = original_list
            vcs._decrypt_pdf_bytes = original_decrypt
        return json.loads(raw)

    def test_passport_query_with_only_DL_returns_no_passport(self):
        result = self._run(
            rows=[
                self._row(
                    file_id="dl-1",
                    file_name="image2 (1).jpg",
                    extracted_text=self._REAL_DL,
                ),
                self._row(
                    file_id="dl-2",
                    file_name="img_9688.jpg",
                    extracted_text=self._REAL_DL,
                ),
                self._row(
                    file_id="dl-3",
                    file_name="img_7109.jpg",
                    extracted_text=self._REAL_DL,
                ),
            ],
            query="show my passport",
        )
                                                     
        self.assertEqual(len(result["hits"]), 0)
        self.assertEqual(result["requested_doc_type"], "passport")
        self.assertGreaterEqual(result["other_id_docs_count"], 3)
        self.assertIn(
            "driver_license", result["other_id_doc_types"],
        )

    def test_driver_license_query_returns_only_DL(self):
        result = self._run(
            rows=[
                self._row(
                    file_id="dl-1",
                    file_name="scanned_dl.pdf",
                    extracted_text=self._REAL_DL,
                ),
                self._row(
                    file_id="pp-1",
                    file_name="scanned_passport.pdf",
                    extracted_text=self._REAL_PASSPORT,
                ),
            ],
            query="show my driver license",
        )
        self.assertEqual(
            result["requested_doc_type"], "driver_license",
        )
        for h in result["hits"]:
            self.assertEqual(h["document_type"], "driver_license")

    def test_broad_id_query_returns_both(self):
        result = self._run(
            rows=[
                self._row(
                    file_id="dl-1",
                    file_name="scanned_dl.pdf",
                    extracted_text=self._REAL_DL,
                ),
                self._row(
                    file_id="pp-1",
                    file_name="scanned_passport.pdf",
                    extracted_text=self._REAL_PASSPORT,
                ),
            ],
            query="show my ID",
        )
        self.assertIsNone(result["requested_doc_type"])
        ids = {h["file_id"] for h in result["hits"]}
        self.assertEqual(ids, {"dl-1", "pp-1"})


_BTC = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"
_SEED = (
    "mountain river apple thunder sapphire orchid cinnamon "
    "valley horizon crystal velvet tiger"
)


class FlowDCryptoVaultLite(_IntegrationBase):

    def test_flow_d_free_user_blocked_upgraded_user_full_lifecycle(self):
                                                                      
        result = self._send(
            message=f"save my BTC wallet {_BTC}",
            tier=vsi.TIER_FREE,
        )
        self.assertEqual(result["band"], vsi.BAND_TIER_REQUIRED)
        self.assertEqual(len(self._rows), 0)
        self.assertIsNone(
            sidraft.get_latest_secure_item_draft(vault_id="v-int"),
        )

                                                    
        upgraded = self._send(
            message=f"save my BTC wallet {_BTC}",
            tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(upgraded["band"], vsi.BAND_DRAFTED)
                                                                    
        confirm = self._send(
            message="yeah save it", tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(confirm["band"], vsi.BAND_SAVED)
        self.assertEqual(len(self._rows), 1)
        row = self._rows[0]
        self.assertEqual(row["item_type"], "crypto_wallet_address")
        decoded = json.loads(
            _fake_decrypt(row["encrypted_data"], self.key),
        )
                                           
        self.assertEqual(decoded["fields"]["wallet_address"], _BTC)

                                                                 
        retrieve = self._send(
            message="show my BTC wallet", tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(retrieve["band"], vsi.BAND_RETRIEVED)
        envelope = json.loads(retrieve["envelope"])
        for card in envelope["items"]:
            self.assertEqual(card["type"], "crypto_wallet_address")

                                                         
        warn = self._send(
            message=f"save my Bitcoin seed phrase {_SEED}",
            tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(warn["band"], vsi.BAND_WARN_DRAFTED)
        self.assertIn("extremely sensitive", warn["message"])
                                                               
        for word in _SEED.split():
            with self.subTest(word=word):
                self.assertNotIn(word, warn["message"])

                                                
        confirm2 = self._send(
            message="save it", tier=vsi.TIER_UPGRADED,
        )
        self.assertEqual(confirm2["band"], vsi.BAND_SAVED)
        seed_row = [r for r in self._rows
                    if r["item_type"] == "crypto_seed_phrase"]
        self.assertEqual(len(seed_row), 1)
        seed_decoded = json.loads(
            _fake_decrypt(seed_row[0]["encrypted_data"], self.key),
        )
        self.assertEqual(seed_decoded["fields"]["seed_phrase"], _SEED)

                                
        deleted = vsi._execute_delete_row(
            vault_id="v-int",
            item_type="crypto_wallet_address",
            service=row["service"],
            db_executor=self._exec,
        )
        self.assertEqual(deleted, 1)
        retrieve_after_delete = self._send(
            message="show my BTC wallet", tier=vsi.TIER_UPGRADED,
        )
        self.assertNotEqual(
            retrieve_after_delete.get("band"), vsi.BAND_RETRIEVED,
        )

                                                                     
        self._assert_no_leak(_BTC, _SEED)
        for word in _SEED.split():
            with self.subTest(word=word):
                self.assertNotIn(word, self._joined_logs())


class FlowEFileRetrieval(unittest.TestCase):


    def _row(self, *, file_id, file_name, extracted_text=""):
        return {
            "id":                    file_id,
            "file_name":             file_name,
            "saved_name":            file_name,
            "extracted_text":        extracted_text,
            "extracted_text_status": "complete",
            "content_type":          "application/pdf",
            "encrypted_file_data":   None,
            "storage_mode":          "inline",
        }

    def _run(self, *, rows, query):
        original_list = main_mod._list_uploaded_files_for_credential_search
        original_decrypt = vcs._decrypt_pdf_bytes
        main_mod._list_uploaded_files_for_credential_search = (
            lambda vid, k: list(rows)
        )
        vcs._decrypt_pdf_bytes = lambda r, k: None
        try:
            raw = vcs.find_in_vault(
                vault_id="v-int", key=b"\x00" * 32,
                query=query,
            )
        finally:
            main_mod._list_uploaded_files_for_credential_search = original_list
            vcs._decrypt_pdf_bytes = original_decrypt
        return json.loads(raw)

    def test_exact_name_finds_the_file(self):
        result = self._run(
            rows=[
                self._row(
                    file_id="f-1",
                    file_name="2024_tax_return.pdf",
                    extracted_text=(
                        "FORM 1040 — Tax Return 2024. "
                        "Filed jointly. Refund: 1240 USD."
                    ),
                ),
            ],
            query="tax return",
        )
                                                                 
                                        
        ids = {h["file_id"] for h in result["hits"]}
        self.assertIn("f-1", ids)

    def test_wrong_name_finds_nothing(self):
        result = self._run(
            rows=[
                self._row(
                    file_id="f-1",
                    file_name="2024_tax_return.pdf",
                    extracted_text=(
                        "FORM 1040 — Tax Return 2024. "
                        "Filed jointly. Refund: 1240 USD."
                    ),
                ),
            ],
            query="quarterly earnings spreadsheet 2019",
        )
                                                                 
                                        
        ids = {h["file_id"] for h in result["hits"]}
        self.assertNotIn("f-1", ids)


if __name__ == "__main__":                    
    unittest.main()
