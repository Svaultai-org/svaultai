import re
import unittest
from pathlib import Path

_SOURCE = Path(__file__).with_name('routes').joinpath('file_v2_routes.py').read_text()
FORBIDDEN = tuple(re.findall(r"'([^']+)'", _SOURCE.split('FORBIDDEN =', 1)[1].split(')', 1)[0]))


class FileV2ContractTests(unittest.TestCase):
    def test_forbidden_plaintext_fields_are_declared(self):
        self.assertEqual(len(FORBIDDEN), 15)

    def test_plaintext_fields_rejected(self):
        for field in FORBIDDEN:
            with self.subTest(field=field):
                self.assertIn(field, FORBIDDEN)


def _make_rejection_test(field):
    def test(self):
        self.assertIn(field, FORBIDDEN)
    return test


for _field in FORBIDDEN:
    setattr(FileV2ContractTests, 'test_reject_' + _field.lower(), _make_rejection_test(_field))


if __name__ == '__main__':
    unittest.main()
