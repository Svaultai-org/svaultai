import importlib.util
from pathlib import Path
import struct
import unittest


module_path = Path(__file__).resolve().parents[1] / "tools" / "verify_android_elf.py"
spec = importlib.util.spec_from_file_location("verify_android_elf", module_path)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def fixture(bits=64, machine=183, alignment=16384, relro_end=16384, offset=0, include_relro=True):
    data = bytearray(1024)
    data[:7] = b"\x7fELF" + bytes([2 if bits == 64 else 1, 1, 1])
    struct.pack_into("<HH", data, 16, 3, machine)
    count = 2 if include_relro else 1
    if bits == 64:
        struct.pack_into("<Q", data, 32, 64)
        struct.pack_into("<HH", data, 54, 56, count)
        struct.pack_into("<IIQQQQQQ", data, 64, 1, 6, offset, 0, 0, 1024 - offset, 32768, alignment)
        if include_relro:
            struct.pack_into("<IIQQQQQQ", data, 120, 0x6474E552, 4, 0, 8192, 0, 0, relro_end - 8192, 1)
    else:
        struct.pack_into("<I", data, 28, 52)
        struct.pack_into("<HH", data, 42, 32, count)
        struct.pack_into("<IIIIIIII", data, 52, 1, offset, 0, 0, 1024 - offset, 32768, 6, alignment)
        if include_relro:
            struct.pack_into("<IIIIIIII", data, 84, 0x6474E552, 0, 8192, 0, 0, relro_end - 8192, 4, 1)
    return bytes(data)


def symbol_table(names=verifier.EXPECTED_EXPORTS, kind="FUNC", index="9"):
    return "\n".join(f" {i}: 00001000 12 {kind} GLOBAL DEFAULT {index} {name}" for i, name in enumerate(sorted(names), 1))


class VerificationTests(unittest.TestCase):
    def test_accepts_all_four_architectures_with_actual_layout(self):
        for abi, (bits, machine) in verifier.ABI_FORMATS.items():
            with self.subTest(abi=abi):
                result = verifier.verify_layout(fixture(bits=bits, machine=machine), abi)
                self.assertEqual(result["relro_segments"][0]["end_modulo_16384"], 0)

    def test_load_flags_without_actual_alignment_fail(self):
        with self.assertRaisesRegex(ValueError, "load_not_16kb_aligned"):
            verifier.verify_layout(fixture(alignment=4096), "arm64-v8a")

    def test_load_alignment_alone_cannot_hide_relro_failure(self):
        for end in (24576, 28672):
            with self.subTest(end=end), self.assertRaisesRegex(ValueError, "relro_end_not_16kb_aligned"):
                verifier.verify_layout(fixture(relro_end=end), "arm64-v8a")

    def test_load_offset_must_match_virtual_address(self):
        with self.assertRaisesRegex(ValueError, "load_offset_address_mismatch"):
            verifier.verify_layout(fixture(offset=256), "arm64-v8a")

    def test_abi_and_elf_machine_cannot_be_mislabeled(self):
        with self.assertRaisesRegex(ValueError, "wrong_elf_machine_or_type"):
            verifier.verify_layout(fixture(machine=62), "arm64-v8a")

    def test_missing_relro_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing_load_or_relro"):
            verifier.verify_layout(fixture(include_relro=False), "arm64-v8a")

    def test_truncated_and_wrong_endian_headers_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_elf_header"):
            verifier.verify_layout(b"\x7fELF", "arm64-v8a")
        data = bytearray(fixture())
        data[5] = 2
        with self.assertRaisesRegex(ValueError, "invalid_elf_format"):
            verifier.verify_layout(bytes(data), "arm64-v8a")

    def test_relro_must_fit_loaded_memory(self):
        with self.assertRaisesRegex(ValueError, "relro_outside_load"):
            verifier.verify_layout(fixture(relro_end=49152), "arm64-v8a")

    def test_exact_seven_ffi_exports_preserved(self):
        self.assertEqual(set(verifier.verify_exports(symbol_table())), verifier.EXPECTED_EXPORTS)

    def test_missing_or_new_ffi_export_rejected(self):
        for names in (verifier.EXPECTED_EXPORTS - {"vaultai_pbkdf2_hmac_sha256"}, verifier.EXPECTED_EXPORTS | {"vaultai_other"}):
            with self.assertRaisesRegex(ValueError, "ffi_exports_changed"):
                verifier.verify_exports(symbol_table(names))

    def test_undefined_or_nonfunction_ffi_export_rejected(self):
        for kind, index in (("FUNC", "UND"), ("OBJECT", "9")):
            with self.assertRaisesRegex(ValueError, "invalid_ffi_export"):
                verifier.verify_exports(symbol_table(kind=kind, index=index))

    def test_rebuild_script_is_offline_locked_and_checks_before_replace(self):
        source = (module_path.parents[1] / "build-android-macos.sh").read_text()
        self.assertIn("--locked --offline", source)
        self.assertIn("28.2.13676358", source)
        self.assertIn("common-page-size=16384", source)
        self.assertIn('"$work_dir/originals/$abi/libvaultai_opaque_client.so"', source)
        self.assertLess(source.index('--report "$work_dir/verified-build.json"'), source.index("install -m 644"))
        self.assertNotIn("keytool ", source)
        self.assertNotIn("flutter build", source)


if __name__ == "__main__":
    unittest.main()
