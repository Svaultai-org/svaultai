

from __future__ import annotations

import json
import logging
import unittest

import vault_complete_search as vcs
import main as main_mod

from vault_complete_search import (
    DOC_TYPE_PASSPORT,
    DOC_TYPE_DRIVER_LICENSE,
    DOC_TYPE_ID_PHOTO,
    DOC_TYPE_NATIONAL_ID,
    DOC_TYPE_RESIDENCE_PERMIT,
    DOC_TYPE_VISA,
    DOC_TYPE_BIRTH_CERTIFICATE,
    DOC_TYPE_BANK_CARD,
    DOC_TYPE_OTHER_DOCUMENT,
    DOC_TYPE_UNKNOWN,
    DOC_TYPE_NOUN,
    extract_requested_doc_type,
)


class TestRequestedDocTypeParser(unittest.TestCase):

    def test_passport_query_returns_passport(self):
        for q in (
            "show my passport",
            "find my passport",
            "Where is my passport?",
            "show passports",
        ):
            with self.subTest(q=q):
                self.assertEqual(
                    extract_requested_doc_type(q), DOC_TYPE_PASSPORT,
                )

    def test_driver_license_query_returns_driver_license(self):
        for q in (
            "show my driver license",
            "show my driver's license",
            "show my drivers license",
            "find my driving licence",
            "where is my driver licence",
        ):
            with self.subTest(q=q):
                self.assertEqual(
                    extract_requested_doc_type(q),
                    DOC_TYPE_DRIVER_LICENSE,
                )

    def test_bare_license_query_returns_driver_license(self):
                                                               
        self.assertEqual(
            extract_requested_doc_type("show my license"),
            DOC_TYPE_DRIVER_LICENSE,
        )

    def test_national_id_query_returns_national_id(self):
        for q in (
            "show my national ID",
            "show my national identification",
            "find national identity",
            "nat id please",
        ):
            with self.subTest(q=q):
                self.assertEqual(
                    extract_requested_doc_type(q),
                    DOC_TYPE_NATIONAL_ID,
                )

    def test_residence_permit_query_returns_residence_permit(self):
        for q in (
            "show my residence permit",
            "show my residency permit",
            "find resident permit",
        ):
            with self.subTest(q=q):
                self.assertEqual(
                    extract_requested_doc_type(q),
                    DOC_TYPE_RESIDENCE_PERMIT,
                )

    def test_visa_query_returns_visa(self):
        for q in (
            "show my visa",
            "find my immigration visa",
            "where is my entry visa",
        ):
            with self.subTest(q=q):
                self.assertEqual(
                    extract_requested_doc_type(q), DOC_TYPE_VISA,
                )

    def test_birth_certificate_query_returns_birth_certificate(self):
        for q in (
            "show my birth certificate",
            "find my birth cert",
        ):
            with self.subTest(q=q):
                self.assertEqual(
                    extract_requested_doc_type(q),
                    DOC_TYPE_BIRTH_CERTIFICATE,
                )

    def test_bank_card_query_returns_bank_card(self):
        for q in (
            "show my bank card",
            "find my debit card",
            "where is my credit card",
        ):
            with self.subTest(q=q):
                self.assertEqual(
                    extract_requested_doc_type(q), DOC_TYPE_BANK_CARD,
                )

    def test_broad_id_queries_return_none(self):
        for q in (
            "show my ID",
            "find my id",
            "show my identification",
            "show me all ID photos",
            "show my documents",
            "show my Kendra Chosen ID",
                            
            "",
            "   ",
        ):
            with self.subTest(q=q):
                self.assertIsNone(extract_requested_doc_type(q))

    def test_nouns_present_for_each_closed_set_type(self):
                                                                
                                                        
        for doc_type in (
            DOC_TYPE_PASSPORT,
            DOC_TYPE_DRIVER_LICENSE,
            DOC_TYPE_NATIONAL_ID,
            DOC_TYPE_RESIDENCE_PERMIT,
            DOC_TYPE_VISA,
            DOC_TYPE_BIRTH_CERTIFICATE,
            DOC_TYPE_BANK_CARD,
            DOC_TYPE_OTHER_DOCUMENT,
            DOC_TYPE_ID_PHOTO,
            DOC_TYPE_UNKNOWN,
        ):
            with self.subTest(doc_type=doc_type):
                self.assertIn(doc_type, DOC_TYPE_NOUN)
                self.assertTrue(DOC_TYPE_NOUN[doc_type])


def _row(*, file_id, file_name, extracted_text,
         content_type="application/pdf", saved_name=None):
    return {
        "id":                    file_id,
        "file_name":             file_name,
        "saved_name":            saved_name or file_name,
        "extracted_text":        extracted_text,
        "extracted_text_status": "complete",
        "content_type":          content_type,
        "encrypted_file_data":   None,
        "storage_mode":          "inline",
    }


_REAL_DL_TEXT = (
    "STATE OF NEW YORK DRIVER LICENSE\n"
    "DL# 123-456-789  CLASS D\n"
    "DOB 01-01-1980  EXP 01-01-2030\n"
    "Holder: LOUIS IODATO\n"
    "Department of Motor Vehicles"
)
_REAL_PASSPORT_TEXT = (
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


class TestFindInVaultRequestedDocTypeGate(unittest.TestCase):

    def _run(self, *, rows, query, monkeypatch_self):
                                                              
                                 
        original_list = main_mod._list_uploaded_files_for_credential_search
        original_decrypt = vcs._decrypt_pdf_bytes
        main_mod._list_uploaded_files_for_credential_search = (
            lambda vid, k: list(rows)
        )
        vcs._decrypt_pdf_bytes = lambda row, key: None
        try:
            raw = vcs.find_in_vault(
                vault_id="v-x", key=b"\x00" * 32,
                query=query, doc_kind="id_photo",
            )
        finally:
            main_mod._list_uploaded_files_for_credential_search = original_list
            vcs._decrypt_pdf_bytes = original_decrypt
        return json.loads(raw)

    def test_passport_query_with_only_driver_licenses_returns_no_passport(self):
        result = self._run(
            rows=[
                _row(
                    file_id="dl-1",
                    file_name="scanned_dl_1.pdf",
                    extracted_text=_REAL_DL_TEXT,
                ),
                _row(
                    file_id="dl-2",
                    file_name="scanned_dl_2.pdf",
                    extracted_text=_REAL_DL_TEXT.replace(
                        "LOUIS IODATO", "JANE DOE",
                    ),
                ),
            ],
            query="show my passport",
            monkeypatch_self=self,
        )
        self.assertEqual(result["requested_doc_type"], DOC_TYPE_PASSPORT)
        self.assertEqual(result["requested_doc_type_label"], "passport")
                                                                 
        self.assertEqual(len(result["hits"]), 0)
                                                            
        self.assertGreaterEqual(result["other_id_docs_count"], 2)
        self.assertIn(
            DOC_TYPE_DRIVER_LICENSE, result["other_id_doc_types"],
        )

    def test_passport_query_with_passport_and_driver_license_returns_only_passport(self):
        result = self._run(
            rows=[
                _row(
                    file_id="dl-1",
                    file_name="scanned_dl.pdf",
                    extracted_text=_REAL_DL_TEXT,
                ),
                _row(
                    file_id="pp-1",
                    file_name="scanned_passport.pdf",
                    extracted_text=_REAL_PASSPORT_TEXT,
                ),
            ],
            query="show my passport",
            monkeypatch_self=self,
        )
        self.assertEqual(result["requested_doc_type"], DOC_TYPE_PASSPORT)
                                         
        ids = {h["file_id"] for h in result["hits"]}
        self.assertEqual(ids, {"pp-1"})
                                                                 
                                   
        for h in result["hits"]:
            self.assertEqual(h["document_type"], DOC_TYPE_PASSPORT)
                                                               
        self.assertGreaterEqual(result["other_id_docs_count"], 1)

    def test_driver_license_query_returns_driver_license_only(self):
        result = self._run(
            rows=[
                _row(
                    file_id="dl-1",
                    file_name="scanned_dl.pdf",
                    extracted_text=_REAL_DL_TEXT,
                ),
                _row(
                    file_id="pp-1",
                    file_name="scanned_passport.pdf",
                    extracted_text=_REAL_PASSPORT_TEXT,
                ),
            ],
            query="show my driver license",
            monkeypatch_self=self,
        )
        self.assertEqual(
            result["requested_doc_type"], DOC_TYPE_DRIVER_LICENSE,
        )
        ids = {h["file_id"] for h in result["hits"]}
        self.assertEqual(ids, {"dl-1"})
        for h in result["hits"]:
            self.assertEqual(
                h["document_type"], DOC_TYPE_DRIVER_LICENSE,
            )

    def test_broad_id_query_returns_both_passport_and_driver_license(self):
        result = self._run(
            rows=[
                _row(
                    file_id="dl-1",
                    file_name="scanned_dl.pdf",
                    extracted_text=_REAL_DL_TEXT,
                ),
                _row(
                    file_id="pp-1",
                    file_name="scanned_passport.pdf",
                    extracted_text=_REAL_PASSPORT_TEXT,
                ),
            ],
            query="show me all ID photos I have in my vault",
            monkeypatch_self=self,
        )
                                                             
                       
        self.assertIsNone(result["requested_doc_type"])
        ids = {h["file_id"] for h in result["hits"]}
        self.assertEqual(ids, {"dl-1", "pp-1"})

    def test_strong_badge_never_appears_for_wrong_doc_type(self):
                                                              
                                                                  
        result = self._run(
            rows=[
                _row(
                    file_id="dl-1",
                    file_name="scanned_dl.pdf",
                    extracted_text=_REAL_DL_TEXT,
                ),
            ],
            query="show my passport",
            monkeypatch_self=self,
        )
        for h in result["hits"]:
            self.assertEqual(h["document_type"], DOC_TYPE_PASSPORT)


class TestEnvelopeSummaryCopy(unittest.TestCase):

    def _build_summary(
        self, *, find_result, query="show my passport",
    ):
        from vault_chat_result_cards import _build_summary_message
        results = find_result.get("hits") or []
        return _build_summary_message(
            results=results,
            is_complete=True,
            query=query,
            query_kind=find_result.get("query_kind") or "id_photo_visual",
            weak_hits_dropped=int(
                (find_result.get("coverage") or {}).get(
                    "weak_hits_dropped"
                ) or 0
            ),
            candidate_id_docs_count=int(
                find_result.get("candidate_id_docs_count") or 0
            ),
            name_mismatch_count=int(
                find_result.get("name_mismatch_count") or 0
            ),
            requested_person_name=(
                find_result.get("requested_person_name") or ""
            ),
            requested_doc_type=(
                find_result.get("requested_doc_type") or ""
            ),
            requested_doc_type_label=(
                find_result.get("requested_doc_type_label") or ""
            ),
            other_id_docs_count=int(
                find_result.get("other_id_docs_count") or 0
            ),
            other_id_doc_types=(
                find_result.get("other_id_doc_types") or []
            ),
        )

    def test_no_passport_no_other_id_docs(self):
        msg = self._build_summary(find_result={
            "hits":                   [],
            "query_kind":             "id_photo_visual",
            "requested_doc_type":     DOC_TYPE_PASSPORT,
            "requested_doc_type_label": "passport",
            "other_id_docs_count":    0,
            "other_id_doc_types":     [],
        })
        self.assertEqual(
            msg, "I couldn't find a passport in your vault.",
        )

    def test_no_passport_but_driver_license_present(self):
        msg = self._build_summary(find_result={
            "hits":                   [],
            "query_kind":             "id_photo_visual",
            "requested_doc_type":     DOC_TYPE_PASSPORT,
            "requested_doc_type_label": "passport",
            "other_id_docs_count":    3,
            "other_id_doc_types":     [DOC_TYPE_DRIVER_LICENSE],
        })
                                                               
                                                              
        self.assertIn(
            "I couldn't find a passport in your vault.", msg,
        )
        self.assertIn("other ID documents", msg)
        self.assertIn("driver licenses", msg)
        self.assertIn("but no passport", msg)

    def test_no_national_id_no_other_id_docs(self):
        msg = self._build_summary(find_result={
            "hits":                   [],
            "query_kind":             "id_photo_visual",
            "requested_doc_type":     DOC_TYPE_NATIONAL_ID,
            "requested_doc_type_label": "national ID",
            "other_id_docs_count":    0,
            "other_id_doc_types":     [],
        })
                                                              
        self.assertEqual(
            msg, "I couldn't find a national ID in your vault.",
        )

    def test_passport_found_singular_copy(self):
        msg = self._build_summary(find_result={
            "hits": [{
                "file_id":       "pp-1",
                "document_type": DOC_TYPE_PASSPORT,
                "classification_strength": "strong_ocr_document",
            }],
            "query_kind":             "id_photo_visual",
            "requested_doc_type":     DOC_TYPE_PASSPORT,
            "requested_doc_type_label": "passport",
            "other_id_docs_count":    0,
            "other_id_doc_types":     [],
        })
        self.assertEqual(msg, "I found 1 matching passport.")

    def test_passport_found_plural_copy(self):
        msg = self._build_summary(find_result={
            "hits": [
                {
                    "file_id":       "pp-1",
                    "document_type": DOC_TYPE_PASSPORT,
                    "classification_strength": "strong_ocr_document",
                },
                {
                    "file_id":       "pp-2",
                    "document_type": DOC_TYPE_PASSPORT,
                    "classification_strength": "visual_confirmed",
                },
            ],
            "query_kind":             "id_photo_visual",
            "requested_doc_type":     DOC_TYPE_PASSPORT,
            "requested_doc_type_label": "passport",
            "other_id_docs_count":    0,
            "other_id_doc_types":     [],
        })
        self.assertEqual(msg, "I found 2 matching passports.")

    def test_driver_license_plural_uses_correct_grammar(self):
        msg = self._build_summary(find_result={
            "hits": [
                {
                    "file_id":       "dl-1",
                    "document_type": DOC_TYPE_DRIVER_LICENSE,
                    "classification_strength": "strong_ocr_document",
                },
                {
                    "file_id":       "dl-2",
                    "document_type": DOC_TYPE_DRIVER_LICENSE,
                    "classification_strength": "visual_confirmed",
                },
            ],
            "query_kind":             "id_photo_visual",
            "requested_doc_type":     DOC_TYPE_DRIVER_LICENSE,
            "requested_doc_type_label": "driver license",
            "other_id_docs_count":    0,
            "other_id_doc_types":     [],
        })
        self.assertEqual(msg, "I found 2 matching driver licenses.")


class TestPrivacyFloorRequestedDocType(unittest.TestCase):

    def test_passport_query_does_not_leak_ocr_values(self):
        records: list[logging.LogRecord] = []

        class _Sink(logging.Handler):
            def emit(self, record):
                records.append(record)

        sink = _Sink(level=logging.DEBUG)
        sink.setLevel(logging.DEBUG)
        names = (
            "vault_complete_search",
            "vault_chat_result_cards",
        )
        for n in names:
            logging.getLogger(n).addHandler(sink)
            logging.getLogger(n).setLevel(logging.DEBUG)

        rows = [
            _row(
                file_id="pp-1",
                file_name="scanned_passport.pdf",
                extracted_text=_REAL_PASSPORT_TEXT,
            ),
        ]
        original_list = main_mod._list_uploaded_files_for_credential_search
        original_decrypt = vcs._decrypt_pdf_bytes
        main_mod._list_uploaded_files_for_credential_search = (
            lambda vid, k: list(rows)
        )
        vcs._decrypt_pdf_bytes = lambda row, key: None
        try:
            vcs.find_in_vault(
                vault_id="v-x", key=b"\x00" * 32,
                query="show my passport", doc_kind="id_photo",
            )
        finally:
            main_mod._list_uploaded_files_for_credential_search = original_list
            vcs._decrypt_pdf_bytes = original_decrypt
            for n in names:
                logging.getLogger(n).removeHandler(sink)

        joined = "\n".join(r.getMessage() for r in records)
                                                                
                                
        for forbidden in (
            "1234567",                          
            "IODATO",                   
            "LOUIS",                       
            "01 JAN 1980",          
            "01 JAN 2030",             
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)


if __name__ == "__main__":                    
    unittest.main()
