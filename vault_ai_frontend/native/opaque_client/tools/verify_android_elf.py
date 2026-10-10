"""Fail-closed verification of built Android libraries; no key or store access."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from datetime import datetime, timezone


ABI_FORMATS = {
    "arm64-v8a": (64, 183),
    "armeabi-v7a": (32, 40),
    "x86_64": (64, 62),
    "x86": (32, 3),
}
EXPECTED_EXPORTS = {
    "vaultai_opaque_client_link_anchor",
    "vaultai_opaque_client_start_registration",
    "vaultai_opaque_client_finish_registration",
    "vaultai_opaque_client_start_login",
    "vaultai_opaque_client_finish_login",
    "vaultai_pbkdf2_hmac_sha256",
    "vaultai_opaque_client_free_string",
}
PAGE_SIZE = 16384


def verify_layout(data, abi):
    if abi not in ABI_FORMATS:
        raise ValueError("unsupported_abi")
    bits, machine = ABI_FORMATS[abi]
    wide = bits == 64
    minimum_header = 64 if wide else 52
    if len(data) < minimum_header or data[:4] != b"\x7fELF":
        raise ValueError("invalid_elf_header")
    if data[4:7] != bytes([2 if wide else 1, 1, 1]):
        raise ValueError("invalid_elf_format")
    if struct.unpack_from("<HH", data, 16) != (3, machine):
        raise ValueError("wrong_elf_machine_or_type")
    phoff = struct.unpack_from("<Q" if wide else "<I", data, 32 if wide else 28)[0]
    entry_size, count = struct.unpack_from("<HH", data, 54 if wide else 42)
    if entry_size != (56 if wide else 32) or not 1 <= count <= 64:
        raise ValueError("invalid_program_header_count_or_size")
    if phoff < minimum_header or phoff + count * entry_size > len(data):
        raise ValueError("truncated_program_headers")
    loads, relro = [], []
    for index in range(count):
        position = phoff + index * entry_size
        if wide:
            kind, flags, offset, vaddr, _, filesz, memsz, alignment = struct.unpack_from("<IIQQQQQQ", data, position)
        else:
            kind, offset, vaddr, _, filesz, memsz, flags, alignment = struct.unpack_from("<IIIIIIII", data, position)
        if filesz > memsz or offset + filesz > len(data):
            raise ValueError("invalid_segment_bounds")
        if kind == 1:
            if alignment < PAGE_SIZE or alignment & (alignment - 1):
                raise ValueError("load_not_16kb_aligned")
            if offset % alignment != vaddr % alignment:
                raise ValueError("load_offset_address_mismatch")
            loads.append({"offset": offset, "virtual_address": vaddr, "memory_size": memsz, "alignment": alignment, "flags": flags})
        if kind == 0x6474E552:
            if memsz == 0 or (vaddr + memsz) % PAGE_SIZE:
                raise ValueError("relro_end_not_16kb_aligned")
            relro.append({"virtual_address": vaddr, "memory_size": memsz, "end_modulo_16384": (vaddr + memsz) % PAGE_SIZE})
    if not loads or not relro:
        raise ValueError("missing_load_or_relro")
    for region in relro:
        if not any(segment["virtual_address"] <= region["virtual_address"] and region["virtual_address"] + region["memory_size"] <= segment["virtual_address"] + segment["memory_size"] for segment in loads):
            raise ValueError("relro_outside_load")
    return {"bits": bits, "machine": machine, "load_segments": loads, "relro_segments": relro}


def verify_exports(symbol_output):
    exports = set()
    for line in symbol_output.splitlines():
        fields = line.split()
        if len(fields) < 8 or not fields[0].rstrip(":").isdigit():
            continue
        name = fields[7].split("@")[0]
        if not name.startswith("vaultai_"):
            continue
        if fields[3:6] != ["FUNC", "GLOBAL", "DEFAULT"] or fields[6] == "UND":
            raise ValueError("invalid_ffi_export")
        exports.add(name)
    if exports != EXPECTED_EXPORTS:
        raise ValueError("ffi_exports_changed")
    return sorted(exports)


def verify_library(path, abi, readelf):
    data = path.read_bytes()
    layout = verify_layout(data, abi)
    headers = subprocess.run([str(readelf), "--program-headers", "--wide", str(path)], check=True, capture_output=True, text=True).stdout
    symbols = subprocess.run([str(readelf), "--dyn-syms", "--wide", str(path)], check=True, capture_output=True, text=True).stdout
    exports = verify_exports(symbols)
    return {"abi": abi, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), **layout, "ffi_exports": exports}, headers, symbols


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readelf", required=True, type=Path)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--lockfile", required=True, type=Path)
    parser.add_argument("--rustc-version", required=True)
    parser.add_argument("--cargo-version", required=True)
    args = parser.parse_args()
    results = []
    evidence = []
    for abi in ABI_FORMATS:
        result, headers, symbols = verify_library(args.directory / abi / "libvaultai_opaque_client.so", abi, args.readelf)
        results.append(result)
        evidence.append((abi, headers, symbols))
    report = {
        "schema": "svaultai_android_opaque_16kb_verification_v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "ndk_revision": "28.2.13676358",
        "rustc": args.rustc_version,
        "cargo": args.cargo_version,
        "rust_source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "cargo_lock_sha256": hashlib.sha256(args.lockfile.read_bytes()).hexdigest(),
        "page_size": PAGE_SIZE,
        "all_four_abis_verified": True,
        "libraries": results,
        "remaining_gate": "Final APK/AAB native dependencies and zip alignment, plus actual 16KB Android runtime testing. No app signing, store upload or functional auth result is claimed by ELF checks.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    for abi, headers, symbols in evidence:
        (args.report.parent / (args.report.stem + "-" + abi + "-readelf.txt")).write_text(headers + "\n" + symbols)
    print(json.dumps({"all_four_abis_verified": True, "report": str(args.report)}))


if __name__ == "__main__":
    main()
