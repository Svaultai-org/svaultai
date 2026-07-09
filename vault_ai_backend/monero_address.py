

from __future__ import annotations

import hashlib
import re
from typing import Optional


_KECCAK_RC = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
    0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)

_KECCAK_ROT = (
    ( 0,  1, 62, 28, 27),
    (36, 44,  6, 55, 20),
    ( 3, 10, 43, 25, 39),
    (41, 45, 15, 21,  8),
    (18,  2, 61, 56, 14),
)

_MASK64 = (1 << 64) - 1


def _rotl64(x: int, n: int) -> int:
    n &= 63
    return ((x << n) | (x >> (64 - n))) & _MASK64


def _keccak_f1600(state: list[int]) -> None:
    for rc in _KECCAK_RC:
        C = [state[x] ^ state[x + 5] ^ state[x + 10]
             ^ state[x + 15] ^ state[x + 20] for x in range(5)]
        D = [C[(x - 1) % 5] ^ _rotl64(C[(x + 1) % 5], 1)
             for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] ^= D[x]

        B = [0] * 25
        for x in range(5):
            for y in range(5):
                B[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl64(
                    state[x + 5 * y], _KECCAK_ROT[y][x],
                )

        for x in range(5):
            for y in range(5):
                state[x + 5 * y] = (
                    B[x + 5 * y]
                    ^ ((~B[((x + 1) % 5) + 5 * y]) & _MASK64
                       & B[((x + 2) % 5) + 5 * y])
                )

        state[0] ^= rc


def keccak256_monero(data: bytes) -> bytes:

    rate = 136
    state = [0] * 25
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != 0:
        padded.append(0x00)
    padded[-1] |= 0x80

    for i in range(0, len(padded), rate):
        block = padded[i:i + rate]
        for j in range(rate // 8):
            lane = int.from_bytes(
                block[j * 8:(j + 1) * 8], "little", signed=False,
            )
            state[j] ^= lane
        _keccak_f1600(state)

    out = bytearray()
    for j in range(4):
        out.extend(state[j].to_bytes(8, "little"))
    return bytes(out)


MONERO_MAINNET_CHAIN_LABEL: str = "monero_mainnet"


MONERO_MAINNET_PRIMARY_PREFIX:    int = 0x12
MONERO_MAINNET_INTEGRATED_PREFIX: int = 0x13
MONERO_MAINNET_SUBADDRESS_PREFIX: int = 0x2A


PRIMARY_ADDRESS_LEN: int = 95
INTEGRATED_ADDRESS_LEN: int = 106
SUBADDRESS_LEN: int = 95


PRIMARY_RAW_LEN:    int = 69
INTEGRATED_RAW_LEN: int = 77
SUBADDRESS_RAW_LEN: int = 69


_MONERO_B58_ALPHABET = (
    "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
)
_MONERO_B58_INDEX = {c: i for i, c in enumerate(_MONERO_B58_ALPHABET)}


_ENC_BLOCK_SIZES = (0, 2, 3, 5, 6, 7, 9, 10, 11)
_MONERO_ENC_FULL_BLOCK = 8
_MONERO_ENC_FULL_CHARS = 11


_MONERO_ADDRESS_RE = re.compile(
    r"^[1-9A-HJ-NP-Za-km-z]{95}$",
)
_MONERO_INTEGRATED_ADDRESS_RE = re.compile(
    r"^[1-9A-HJ-NP-Za-km-z]{106}$",
)


def _monero_address_shape_ok(s: str) -> bool:
    return bool(
        _MONERO_ADDRESS_RE.match(s)
        or _MONERO_INTEGRATED_ADDRESS_RE.match(s),
    )


def _monero_keccak256(raw: bytes) -> bytes:

    try:
        return hashlib.new("keccak_256", raw).digest()
    except (ValueError, AttributeError):
        pass
    try:
        from Crypto.Hash import keccak as _keccak
        k = _keccak.new(digest_bits=256)
        k.update(raw)
        return k.digest()
    except Exception:
        pass
    return keccak256_monero(raw)


def _decode_block(block: str) -> bytes:
    if not block:
        return b""
    if len(block) not in {2, 3, 5, 6, 7, 9, 10, 11}:
        raise ValueError("invalid monero-base58 block size")
    n = 0
    for c in block:
        idx = _MONERO_B58_INDEX.get(c)
        if idx is None:
            raise ValueError("invalid base58 character in monero address")
        n = n * 58 + idx
    out_len = _ENC_BLOCK_SIZES.index(len(block))
    if n >= (1 << (8 * out_len)):
        raise ValueError("monero-base58 block overflow")
    return n.to_bytes(out_len, "big")


def monero_base58_decode(s: str) -> bytes:

    if not isinstance(s, str) or not s:
        raise ValueError("empty monero-base58 input")
    out = bytearray()
    i = 0
    while i < len(s):
        take = min(_MONERO_ENC_FULL_CHARS, len(s) - i)
        block = s[i:i + take]
        out.extend(_decode_block(block))
        i += take
    return bytes(out)


def _classify_prefix(prefix_byte: int) -> Optional[str]:
    if prefix_byte == MONERO_MAINNET_PRIMARY_PREFIX:
        return "primary"
    if prefix_byte == MONERO_MAINNET_INTEGRATED_PREFIX:
        return "integrated"
    if prefix_byte == MONERO_MAINNET_SUBADDRESS_PREFIX:
        return "subaddress"
    return None


def _validate_decoded_address(
    raw: bytes, expected_kind: Optional[str] = None,
) -> Optional[str]:

    if len(raw) not in (PRIMARY_RAW_LEN, INTEGRATED_RAW_LEN):
        return None
    prefix = raw[0]
    kind = _classify_prefix(prefix)
    if kind is None:
        return None
    if kind in ("primary", "subaddress") and len(raw) != PRIMARY_RAW_LEN:
        return None
    if kind == "integrated" and len(raw) != INTEGRATED_RAW_LEN:
        return None
    payload = raw[:-4]
    checksum = raw[-4:]
    try:
        expected_checksum = _monero_keccak256(payload)[:4]
    except RuntimeError:
        return None
    if expected_checksum != checksum:
        return None
    if expected_kind is not None and kind != expected_kind:
        return None
    return kind


def is_valid_monero_address(raw: Optional[str]) -> bool:

    if not isinstance(raw, str):
        return False
    s = raw.strip()
    if not s:
        return False
    if not (
        _MONERO_ADDRESS_RE.match(s)
        or _MONERO_INTEGRATED_ADDRESS_RE.match(s)
    ):
        return False
    try:
        decoded = monero_base58_decode(s)
    except ValueError:
        return False
    return _validate_decoded_address(decoded) is not None


def is_valid_monero_primary_or_subaddress(raw: Optional[str]) -> bool:

    if not isinstance(raw, str):
        return False
    s = raw.strip()
    if not s:
        return False
    if not _MONERO_ADDRESS_RE.match(s):
        return False
    try:
        decoded = monero_base58_decode(s)
    except ValueError:
        return False
    kind = _validate_decoded_address(decoded)
    return kind in ("primary", "subaddress")


def keccak_256_available() -> bool:

    try:
        _monero_keccak256(b"")
        return True
    except RuntimeError:
        return False


__all__ = [
    "MONERO_MAINNET_CHAIN_LABEL",
    "MONERO_MAINNET_PRIMARY_PREFIX",
    "MONERO_MAINNET_INTEGRATED_PREFIX",
    "MONERO_MAINNET_SUBADDRESS_PREFIX",
    "PRIMARY_ADDRESS_LEN",
    "INTEGRATED_ADDRESS_LEN",
    "SUBADDRESS_LEN",
    "monero_base58_decode",
    "is_valid_monero_address",
    "is_valid_monero_primary_or_subaddress",
    "keccak_256_available",
]
