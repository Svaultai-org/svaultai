

from __future__ import annotations

import inspect
import json
import os
import unittest
from typing import Any, Optional

import vault_relationship_graph as rg


def _migration_0012_source() -> str:
    path = os.path.join(
        os.path.dirname(__file__),
        "migrations", "versions",
        "0012_vault_file_relationships.py",
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _file_facts(
    *,
    file_id: str,
    file_name: str = "doc.pdf",
    folder_path: Optional[str] = None,
    import_id: Optional[str] = None,
    content_sha256: Optional[str] = None,
    document_purpose: str = "generic_text",
    topics: Optional[list] = None,
    entities: Optional[dict] = None,
    categories: Optional[list] = None,
    travel_signals: Optional[dict] = None,
    financial_signals: Optional[dict] = None,
    legal_signals: Optional[dict] = None,
    identity_signals: Optional[dict] = None,
    archive_signals: Optional[dict] = None,
    embedding_vector: Optional[list] = None,
) -> dict:
    return {
        "file_id":             file_id,
        "file_name":           file_name,
        "folder_path":         folder_path,
        "import_id":           import_id,
        "content_sha256":      content_sha256,
        "document_purpose":    document_purpose,
        "topics":              topics or [],
        "entities":            entities or {},
        "detected_categories": categories or [],
        "travel_signals":      travel_signals or {},
        "financial_signals":   financial_signals or {},
        "legal_signals":       legal_signals or {},
        "identity_signals":    identity_signals or {},
        "archive_signals":     archive_signals or {},
        "embedding_vector":    embedding_vector,
    }


SENTINELS = (
    "hunter2", "SUPERSECRET-XYZ-123",
    "Patrick62109", "MKSherm81765", "e&t082826",
    "sunshine6856", "loul82!Bridge",
    "plaintext-extracted-text-leak",
)


def _signals_to_string(decisions) -> str:

    return json.dumps(decisions, default=str)


class MigrationSchemaGuardTests(unittest.TestCase):
    def setUp(self):
        self.src = _migration_0012_source()

    def test_table_exists(self):
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS vault_file_relationships",
            self.src,
        )

    def test_required_columns_present(self):
        for col in (
            "relationship_id", "vault_id",
            "file_a_id", "file_b_id",
            "relationship_type", "confidence",
            "reasons_jsonb", "evidence_jsonb",
            "analysis_version",
            "created_at", "updated_at",
        ):
            self.assertIn(col, self.src, f"missing column: {col}")

    def test_type_enum_includes_all_python_constants(self):
        for rel in rg.RELATIONSHIP_TYPES:
            self.assertTrue(
                f'"{rel}"' in self.src or f"'{rel}'" in self.src,
                f"migration must declare relationship_type {rel!r}",
            )

    def test_ordered_pair_check_constraint(self):
        self.assertIn(
            "vault_file_relationships_ordered_chk",
            self.src,
        )

    def test_distinct_pair_check_constraint(self):
        self.assertIn(
            "vault_file_relationships_distinct_chk",
            self.src,
        )

    def test_confidence_bounded_check_constraint(self):
        self.assertIn(
            "vault_file_relationships_confidence_chk",
            self.src,
        )

    def test_unique_index_on_pair_plus_type(self):
        self.assertIn(
            "vault_file_relationships_uniq_idx",
            self.src,
        )

    def test_per_side_lookup_indexes(self):
                                                        
                                                          
        self.assertIn(
            "vault_file_relationships_vault_a_idx",
            self.src,
        )
        self.assertIn(
            "vault_file_relationships_vault_b_idx",
            self.src,
        )

    def test_reversible(self):
        self.assertIn(
            "DROP TABLE IF EXISTS vault_file_relationships",
            self.src,
        )


class MakeDecisionTests(unittest.TestCase):
    def test_sub_threshold_drops_silently(self):
        d = rg._make_decision(
            relationship_type=rg.REL_SAME_FOLDER,
            confidence=0.10,                                
            reasons=["some reason"],
            evidence={},
        )
        self.assertIsNone(d)

    def test_invalid_type_drops_silently(self):
        d = rg._make_decision(
            relationship_type="not_a_real_type",
            confidence=0.9,
            reasons=["x"],
            evidence={},
        )
        self.assertIsNone(d)

    def test_empty_reasons_drops_silently(self):
        d = rg._make_decision(
            relationship_type=rg.REL_DUPLICATE,
            confidence=1.0,
            reasons=[],
            evidence={},
        )
        self.assertIsNone(d)

    def test_confidence_clamped_to_one(self):
        d = rg._make_decision(
            relationship_type=rg.REL_DUPLICATE,
            confidence=1.5,
            reasons=["dupe"],
            evidence={},
        )
        self.assertEqual(d["confidence"], 1.0)

    def test_evidence_keys_whitelisted(self):
                                                             
                                               
        d = rg._make_decision(
            relationship_type=rg.REL_SAME_PERSON,
            confidence=0.8,
            reasons=["same person name: Maureen"],
            evidence={
                "shared_entity_names":  ["Maureen"],
                "decrypted_summary":    "BAD",
                "extracted_text":       "BAD",
                "password":             "hunter2",
            },
        )
        self.assertEqual(
            list(d["evidence"].keys()), ["shared_entity_names"],
        )

    def test_reasons_capped(self):
        too_many = [f"r{i}" for i in range(10)]
        d = rg._make_decision(
            relationship_type=rg.REL_SAME_FOLDER,
            confidence=0.5,
            reasons=too_many,
            evidence={},
        )
        self.assertLessEqual(
            len(d["reasons"]), rg._MAX_REASONS_PER_ROW,
        )


class DuplicateDetectorTests(unittest.TestCase):
    def test_identical_hash_is_duplicate(self):
        a = _file_facts(
            file_id="a", content_sha256="abc123",
        )
        b = _file_facts(
            file_id="b", content_sha256="abc123",
        )
        d = rg._detect_duplicate(a, b)
        self.assertEqual(d["relationship_type"], rg.REL_DUPLICATE)
        self.assertEqual(d["confidence"], 1.0)
        self.assertTrue(d["evidence"]["content_sha256_match"])

    def test_different_hash_not_duplicate(self):
        a = _file_facts(file_id="a", content_sha256="aaa")
        b = _file_facts(file_id="b", content_sha256="bbb")
        self.assertIsNone(rg._detect_duplicate(a, b))

    def test_missing_hash_not_duplicate(self):
        a = _file_facts(file_id="a")
        b = _file_facts(file_id="b", content_sha256="abc")
        self.assertIsNone(rg._detect_duplicate(a, b))


class NearDuplicateDetectorTests(unittest.TestCase):
    def test_high_cosine_is_near_duplicate(self):
                                           
        a = _file_facts(
            file_id="a",
            embedding_vector=[1.0, 0.0, 0.0, 0.0],
        )
        b = _file_facts(
            file_id="b",
            embedding_vector=[1.0, 0.0, 0.0, 0.0],
        )
        d = rg._detect_near_duplicate(a, b)
        self.assertIsNotNone(d)
        self.assertEqual(d["relationship_type"], rg.REL_NEAR_DUPLICATE)

    def test_low_cosine_not_near_duplicate(self):
        a = _file_facts(
            file_id="a",
            embedding_vector=[1.0, 0.0, 0.0, 0.0],
        )
        b = _file_facts(
            file_id="b",
            embedding_vector=[0.0, 1.0, 0.0, 0.0],
        )
        self.assertIsNone(rg._detect_near_duplicate(a, b))


class SemanticRelatedDetectorTests(unittest.TestCase):
    def test_medium_cosine_is_semantic_related(self):
                                                           
                                                      
        a = _file_facts(
            file_id="a",
            embedding_vector=[1.0, 1.0, 1.0, 0.0],
        )
        b = _file_facts(
            file_id="b",
            embedding_vector=[1.0, 1.0, 0.0, 0.0],
        )
        d = rg._detect_semantic_related(a, b)
        self.assertIsNotNone(d)
        self.assertEqual(d["relationship_type"], rg.REL_SEMANTIC_RELATED)

    def test_very_high_cosine_is_skipped_for_near_dup_path(self):
                                                        
                           
        a = _file_facts(
            file_id="a",
            embedding_vector=[1.0, 0.0, 0.0, 0.0],
        )
        b = _file_facts(
            file_id="b",
            embedding_vector=[1.0, 0.0, 0.0, 0.0],
        )
        self.assertIsNone(rg._detect_semantic_related(a, b))


class SamePersonDetectorTests(unittest.TestCase):
    def test_shared_name_is_same_person(self):
        a = _file_facts(
            file_id="a",
            entities={"names": ["Maureen Smith"]},
        )
        b = _file_facts(
            file_id="b",
            entities={"names": ["Maureen Smith", "Other"]},
        )
        d = rg._detect_same_person(a, b)
        self.assertEqual(d["relationship_type"], rg.REL_SAME_PERSON)
        self.assertIn("Maureen Smith", d["reasons"][0])
        self.assertIn(
            "Maureen Smith", d["evidence"]["shared_entity_names"],
        )

    def test_identity_signal_bumps_confidence(self):
        plain = _file_facts(
            file_id="a",
            entities={"names": ["Maureen"]},
        )
        with_id = _file_facts(
            file_id="b",
            entities={"names": ["Maureen"]},
            identity_signals={
                "any_present": True, "doc_types": ["passport"],
            },
        )
        d_plain = rg._detect_same_person(plain, plain)
                                                           
                                                       
        d_id = rg._detect_same_person(plain, with_id)
        self.assertGreater(d_id["confidence"], d_plain["confidence"])

    def test_no_shared_name_not_same_person(self):
        a = _file_facts(
            file_id="a",
            entities={"names": ["Maureen"]},
        )
        b = _file_facts(
            file_id="b",
            entities={"names": ["Alex"]},
        )
        self.assertIsNone(rg._detect_same_person(a, b))


class SameCompanyDetectorTests(unittest.TestCase):
    def test_shared_email_domain_is_same_company(self):
        a = _file_facts(
            file_id="a",
            entities={"email_domains": ["wellsfargo.com"]},
        )
        b = _file_facts(
            file_id="b",
            entities={"email_domains": ["wellsfargo.com", "other.com"]},
        )
        d = rg._detect_same_company(a, b)
        self.assertEqual(d["relationship_type"], rg.REL_SAME_COMPANY)
        self.assertIn(
            "wellsfargo.com",
            d["evidence"]["shared_email_domains"],
        )

    def test_no_shared_domain_not_same_company(self):
        a = _file_facts(
            file_id="a",
            entities={"email_domains": ["a.com"]},
        )
        b = _file_facts(
            file_id="b",
            entities={"email_domains": ["b.com"]},
        )
        self.assertIsNone(rg._detect_same_company(a, b))


class SameTripDetectorTests(unittest.TestCase):
    def test_passport_plus_visa_is_same_trip(self):
        passport = _file_facts(
            file_id="a",
            travel_signals={
                "any_present": True,
                "doc_types":   ["passport"],
            },
            entities={"names": ["Doha"]},
        )
        visa = _file_facts(
            file_id="b",
            travel_signals={
                "any_present": True,
                "doc_types":   ["visa"],
            },
            entities={"names": ["Doha"]},
        )
        d = rg._detect_same_trip(passport, visa)
        self.assertEqual(d["relationship_type"], rg.REL_SAME_TRIP)
                                                   
        self.assertIn("passport", d["evidence"]["shared_doc_types"])
        self.assertIn("visa", d["evidence"]["shared_doc_types"])
                                               
        self.assertGreaterEqual(d["confidence"], 0.7)

    def test_only_one_travel_doc_not_same_trip(self):
        passport = _file_facts(
            file_id="a",
            travel_signals={
                "any_present": True, "doc_types": ["passport"],
            },
        )
        random = _file_facts(file_id="b")
        self.assertIsNone(rg._detect_same_trip(passport, random))


class SameFinancialAccountDetectorTests(unittest.TestCase):
    def test_wells_fargo_statement_plus_tax_doc(self):
        statement = _file_facts(
            file_id="a",
            financial_signals={
                "any_present": True,
                "doc_types":   ["bank_statement"],
            },
            entities={"names": ["Wells Fargo"]},
        )
        tax = _file_facts(
            file_id="b",
            financial_signals={
                "any_present": True,
                "doc_types":   ["tax_return"],
            },
            entities={"names": ["Wells Fargo"]},
        )
        d = rg._detect_same_financial_account(statement, tax)
        self.assertEqual(
            d["relationship_type"], rg.REL_SAME_FINANCIAL_ACCOUNT,
        )
        self.assertIn(
            "Wells Fargo", d["evidence"]["shared_entity_names"],
        )

    def test_two_financial_docs_without_shared_entity_not_paired(self):
        a = _file_facts(
            file_id="a",
            financial_signals={
                "any_present": True, "doc_types": ["bank_statement"],
            },
            entities={"names": ["Wells Fargo"]},
        )
        b = _file_facts(
            file_id="b",
            financial_signals={
                "any_present": True, "doc_types": ["bank_statement"],
            },
            entities={"names": ["Bank Of America"]},
        )
        self.assertIsNone(rg._detect_same_financial_account(a, b))


class FrontBackPairDetectorTests(unittest.TestCase):
    def test_id_front_back_with_matching_stem(self):
        a = _file_facts(
            file_id="a",
            file_name="maureen_id_front.jpg",
            identity_signals={
                "any_present": True, "doc_types": ["driver_license"],
            },
        )
        b = _file_facts(
            file_id="b",
            file_name="maureen_id_back.jpg",
            identity_signals={
                "any_present": True, "doc_types": ["driver_license"],
            },
        )
        d = rg._detect_front_back_pair(a, b)
        self.assertEqual(
            d["relationship_type"], rg.REL_FRONT_BACK_PAIR,
        )
        self.assertGreaterEqual(d["confidence"], 0.80)
        self.assertIn("/", d["evidence"]["filename_pattern"])

    def test_two_front_files_not_a_pair(self):
        a = _file_facts(
            file_id="a", file_name="id_front_alex.jpg",
        )
        b = _file_facts(
            file_id="b", file_name="id_front_alex_v2.jpg",
        )
        self.assertIsNone(rg._detect_front_back_pair(a, b))

    def test_different_stems_not_a_pair(self):
        a = _file_facts(file_id="a", file_name="alex_id_front.jpg")
        b = _file_facts(file_id="b", file_name="maureen_id_back.jpg")
        self.assertIsNone(rg._detect_front_back_pair(a, b))


class SameImportBatchDetectorTests(unittest.TestCase):
    def test_same_batch_is_weak_relationship(self):
        a = _file_facts(file_id="a", import_id="batch-1")
        b = _file_facts(file_id="b", import_id="batch-1")
        d = rg._detect_same_import_batch(a, b)
        self.assertEqual(
            d["relationship_type"], rg.REL_SAME_IMPORT_BATCH,
        )
                                
        self.assertLess(d["confidence"], 0.5)

    def test_different_batches_not_paired(self):
        a = _file_facts(file_id="a", import_id="batch-1")
        b = _file_facts(file_id="b", import_id="batch-2")
        self.assertIsNone(rg._detect_same_import_batch(a, b))


class SameFolderDetectorTests(unittest.TestCase):
    def test_same_folder_is_weak_relationship(self):
        a = _file_facts(
            file_id="a", folder_path="/Family/Maureen/IDs",
        )
        b = _file_facts(
            file_id="b", folder_path="/Family/Maureen/IDs",
        )
        d = rg._detect_same_folder(a, b)
        self.assertEqual(d["relationship_type"], rg.REL_SAME_FOLDER)
        self.assertLess(d["confidence"], 0.5)

    def test_different_folders_not_paired(self):
        a = _file_facts(
            file_id="a", folder_path="/Family/Maureen",
        )
        b = _file_facts(
            file_id="b", folder_path="/Family/Alex",
        )
        self.assertIsNone(rg._detect_same_folder(a, b))


class ArchiveContainsSignalDetectorTests(unittest.TestCase):
    def test_archive_with_matching_inner_entity(self):
        archive = _file_facts(
            file_id="zip-1",
            file_name="backup.zip",
            archive_signals={
                "format":           "zip",
                "inner_file_count": 1,
                "inner_files": [
                    {
                        "path":         "notes.md",
                        "is_text":      True,
                        "entity_names": ["Wells Fargo"],
                        "topics":       ["finance"],
                    },
                ],
            },
        )
        other = _file_facts(
            file_id="doc-1",
            entities={"names": ["Wells Fargo"]},
        )
        d = rg._detect_archive_contains_signal(archive, other)
        self.assertEqual(
            d["relationship_type"], rg.REL_ARCHIVE_CONTAINS_SIGNAL,
        )
        self.assertEqual(
            d["evidence"]["archive_file_id"], "zip-1",
        )

    def test_archive_without_overlap_no_relationship(self):
        archive = _file_facts(
            file_id="zip-1",
            archive_signals={
                "format":           "zip",
                "inner_file_count": 1,
                "inner_files": [
                    {"path": "a.txt",
                     "entity_names": ["Unrelated"], "topics": []},
                ],
            },
        )
        other = _file_facts(
            file_id="doc-1",
            entities={"names": ["Wells Fargo"]},
        )
        self.assertIsNone(
            rg._detect_archive_contains_signal(archive, other),
        )


class SupportingDocumentDetectorTests(unittest.TestCase):
    def test_application_form_plus_id_with_shared_name(self):
        form = _file_facts(
            file_id="f",
            document_purpose="application_form",
            entities={"names": ["Maureen"]},
        )
        id_doc = _file_facts(
            file_id="i",
            document_purpose="generic_text",
            entities={"names": ["Maureen"]},
            identity_signals={
                "any_present": True, "doc_types": ["driver_license"],
            },
        )
        d = rg._detect_supporting_document(form, id_doc)
        self.assertEqual(
            d["relationship_type"], rg.REL_SUPPORTING_DOCUMENT,
        )
        self.assertIn(
            "driver_license", d["evidence"]["shared_doc_types"],
        )

    def test_two_forms_not_a_supporting_pair(self):
        a = _file_facts(
            file_id="a", document_purpose="application_form",
            entities={"names": ["Maureen"]},
        )
        b = _file_facts(
            file_id="b", document_purpose="insurance_form",
            entities={"names": ["Maureen"]},
        )
        self.assertIsNone(rg._detect_supporting_document(a, b))


class ConfidenceOrderingTests(unittest.TestCase):
    def test_duplicate_is_strongest(self):
        d = rg._detect_duplicate(
            _file_facts(file_id="a", content_sha256="x"),
            _file_facts(file_id="b", content_sha256="x"),
        )
        self.assertGreaterEqual(d["confidence"], 0.95)

    def test_same_folder_weaker_than_same_person(self):
        folder = rg._detect_same_folder(
            _file_facts(file_id="a", folder_path="/x"),
            _file_facts(file_id="b", folder_path="/x"),
        )
        person = rg._detect_same_person(
            _file_facts(file_id="a",
                        entities={"names": ["Maureen"]}),
            _file_facts(file_id="b",
                        entities={"names": ["Maureen"]}),
        )
        self.assertLess(folder["confidence"], person["confidence"])

    def test_same_import_batch_weaker_than_semantic_related(self):
        batch = rg._detect_same_import_batch(
            _file_facts(file_id="a", import_id="b1"),
            _file_facts(file_id="b", import_id="b1"),
        )
        semantic = rg._detect_semantic_related(
            _file_facts(file_id="a",
                        embedding_vector=[1.0, 1.0, 1.0, 0.0]),
            _file_facts(file_id="b",
                        embedding_vector=[1.0, 1.0, 0.0, 0.0]),
        )
        self.assertLess(batch["confidence"], semantic["confidence"])

    def test_unrelated_same_folder_alone_is_weak_only(self):


        d = rg._detect_same_folder(
            _file_facts(file_id="a", folder_path="/Misc"),
            _file_facts(file_id="b", folder_path="/Misc"),
        )
        self.assertLess(d["confidence"], 0.5)


class FindRelationshipsInFilesTests(unittest.TestCase):
    def test_pairs_are_ordered_file_a_less_than_file_b(self):
        files = [
            _file_facts(file_id="zzz", content_sha256="x"),
            _file_facts(file_id="aaa", content_sha256="x"),
        ]
        decisions = rg.find_relationships_in_files(files)
        for d in decisions:
            self.assertLess(d["file_a_id"], d["file_b_id"])

    def test_self_pair_skipped(self):
        files = [
            _file_facts(file_id="a", content_sha256="x"),
            _file_facts(file_id="a", content_sha256="x"),
        ]
        decisions = rg.find_relationships_in_files(files)
                                                         
        self.assertEqual(decisions, [])

    def test_one_pair_can_have_multiple_relationship_types(self):
        a = _file_facts(
            file_id="aaa",
            folder_path="/Family",
            entities={"names": ["Maureen"]},
            content_sha256=None,
        )
        b = _file_facts(
            file_id="bbb",
            folder_path="/Family",
            entities={"names": ["Maureen"]},
            content_sha256=None,
        )
        decisions = rg.find_relationships_in_files([a, b])
        types = {d["relationship_type"] for d in decisions}
                                                         
                                
        self.assertIn(rg.REL_SAME_PERSON, types)
        self.assertIn(rg.REL_SAME_FOLDER, types)

    def test_detector_exception_doesnt_break_walk(self):
                                           
        from unittest.mock import patch
        with patch.object(
            rg, "_detect_duplicate",
            side_effect=RuntimeError("boom"),
        ):
            files = [
                _file_facts(file_id="aaa",
                            entities={"names": ["Maureen"]}),
                _file_facts(file_id="bbb",
                            entities={"names": ["Maureen"]}),
            ]
            decisions = rg.find_relationships_in_files(files)
                                                
        self.assertTrue(any(
            d["relationship_type"] == rg.REL_SAME_PERSON
            for d in decisions
        ))


class SafetyTests(unittest.TestCase):
    def test_sentinel_entity_name_never_in_reasons(self):


        for sentinel in SENTINELS:
            a = _file_facts(
                file_id="a",
                entities={"names": ["Maureen"]},             
            )
            b = _file_facts(
                file_id="b",
                entities={"names": ["Maureen"]},
                identity_signals={
                    "any_present": True,
                    "doc_types":   ["passport"],
                },
            )
            d = rg._detect_same_person(a, b)
            payload = json.dumps(d, default=str)
            self.assertNotIn(sentinel, payload)

    def test_extracted_text_never_referenced_in_module(self):


        src = inspect.getsource(rg)
        self.assertNotIn("decrypt_message", src)
        self.assertNotIn("decrypt_bytes", src)
                                                            
                                                          
    def test_module_never_executes_user_content(self):
        src = inspect.getsource(rg)
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(forbidden, src)

    def test_evidence_keys_are_closed_set(self):
                                                              
                                                   
        src = inspect.getsource(rg._safe_evidence)
        for key in (
            "shared_entity_names",
            "shared_topics",
            "shared_categories",
            "shared_doc_types",
            "embedding_cosine",
            "filename_pattern",
            "content_sha256_match",
            "import_id",
            "folder_path",
            "shared_email_domains",
            "archive_file_id",
            "inner_file_count",
        ):
            self.assertIn(key, src)

    def test_no_decision_persists_below_floor(self):
        d = rg._make_decision(
            relationship_type=rg.REL_SAME_FOLDER,
            confidence=0.1,
            reasons=["x"],
            evidence={"folder_path": "/x"},
        )
        self.assertIsNone(d)


class DBLayerSourceGuardTests(unittest.TestCase):
    def test_upsert_uses_natural_key(self):
        src = inspect.getsource(rg.upsert_relationship)
        self.assertIn(
            "ON CONFLICT (\n                vault_id, file_a_id, file_b_id, relationship_type\n            )",
            src,
        )

    def test_get_relationships_for_file_reads_both_sides(self):
        src = inspect.getsource(rg.get_relationships_for_file)
        self.assertIn("file_a_id = %s OR file_b_id = %s", src)
                       
        self.assertIn("vault_id = %s", src)

    def test_get_relationships_for_file_sorts_by_confidence(self):
        src = inspect.getsource(rg.get_relationships_for_file)
        self.assertIn("ORDER BY confidence DESC", src)

    def test_load_file_facts_is_vault_scoped(self):
        src = inspect.getsource(rg.load_file_facts_for_vault)
        self.assertIn("u.vault_id = %s", src)

    def test_load_file_facts_only_reads_safe_columns(self):
        src = inspect.getsource(rg.load_file_facts_for_vault)
                                                 
        self.assertNotIn("encrypted_file_data", src)
                                                                
                                                             
        for safe_col in (
            "content_sha256",
            "import_id",
            "topics_jsonb",
            "entities_jsonb",
            "archive_signals_jsonb",
        ):
            self.assertIn(safe_col, src)


if __name__ == "__main__":
    unittest.main()
