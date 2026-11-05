"""Synthetic fixtures for the harmless-checklist false positive; no server I/O."""
import ast
from pathlib import Path
import unittest

from bank_document_detection import has_substantive_bank_data


CHECKLIST = """SVaultAI demo travel checklist
Fictional sample content for a disposable demonstration vault only.

Pack a charger, travel adapter and reusable water bottle.
The demo library card renewal date is November 15, 2026.
No real identity documents, account numbers or private information are included.
"""


class BankDocumentEvidenceTests(unittest.TestCase):
    def test_exact_reported_harmless_checklist_is_not_bank_data(self):
        self.assertFalse(has_substantive_bank_data(CHECKLIST))

    def test_bank_words_and_negated_details_alone_are_not_data(self):
        samples = [None, "", "No real bank account numbers are included.",
                   "No IBAN, routing number, or SWIFT code is stored here.",
                   "SwiftUI notes for a travel-routing checklist.",
                   "Learning Swift programming today.", "SWIFT PROGRAMMING notes",
                   "Swift: programming for iOS",
                   "Bank account number: not provided", "IBAN: none", "SWIFT: N/A",
                   "No bank account number: 000123456789", "Without routing number: 000000000",
                   "No real SWIFT code: DEMOUS00", "Account number: 000123456789",
                   "Library account number: 000123456789", "Routing number: 12345"]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertFalse(has_substantive_bank_data(sample))

    def test_labelled_synthetic_details_remain_detectable(self):
        # Fictional, non-operational fixtures; the detector establishes shape,
        # never whether a financial identifier is valid or usable.
        samples = ["Bank account number: 000123456789",
                   "Example Bank\nAccount no: 000123-456789",
                   "Routing number: 000000000", "IBAN: DE00 0000 0000 0000 0000 00",
                   "SWIFT: DEMOUS00", "BIC code: DEMOUS00XXX",
                   "No details appear in the public summary.\nBank account number: 000123456789",
                   "No fee. Bank account number: 000123456789"]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(has_substantive_bank_data(sample))

    def test_real_upload_classifier_uses_the_gate_without_importing_server(self):
        # Run the actual classification function with unrelated login parsing
        # disabled. Importing main would initialize server/database services.
        tree = ast.parse(Path(__file__).with_name("main.py").read_text())
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == "_classify_secret_from_text")
        namespace = {"Optional": __import__("typing").Optional,
                     "extract_multiple_credentials": lambda _: [],
                     "_is_high_confidence_login": lambda _: False,
                     "_is_valid_secret_payload": lambda payload: bool(payload["fields"]),
                     "_normalize_service_name": lambda value: value.lower(),
                     "has_substantive_bank_data": has_substantive_bank_data}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "actual-classifier", "exec"), namespace)
        classify = namespace["_classify_secret_from_text"]
        self.assertEqual(classify(CHECKLIST, "checklist.txt")["payloads"], [])
        positive = classify("Bank account number: 000123456789", "synthetic-bank.txt")
        self.assertEqual(positive["detected_type"], "bank")
        self.assertEqual(len(positive["payloads"]), 1)


if __name__ == "__main__":
    unittest.main()
