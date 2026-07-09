

from __future__ import annotations

import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


CHUNK_NONCE_BYTES = 12
CHUNK_TAG_BYTES = 16
CHUNK_INDEX_AAD_BYTES = 4


def _index_aad(chunk_index: int) -> bytes:
    if chunk_index < 0:
        raise ValueError("chunk_index must be non-negative")
    if chunk_index > 0xFFFFFFFF:
        raise ValueError("chunk_index exceeds 32-bit range")
    return struct.pack(">I", chunk_index)


def encrypt_chunk(plaintext: bytes, key: bytes, chunk_index: int) -> bytes:


    aesgcm = AESGCM(key)
    nonce = os.urandom(CHUNK_NONCE_BYTES)
    ct_and_tag = aesgcm.encrypt(nonce, plaintext, _index_aad(chunk_index))
    return nonce + ct_and_tag


def decrypt_chunk(frame: bytes, key: bytes, chunk_index: int) -> bytes:


    if len(frame) < CHUNK_NONCE_BYTES + CHUNK_TAG_BYTES:
        raise ValueError("Chunk frame too short")
    nonce = frame[:CHUNK_NONCE_BYTES]
    ct_and_tag = frame[CHUNK_NONCE_BYTES:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct_and_tag, _index_aad(chunk_index))


def _encrypt_chunk_with_nonce(
    plaintext: bytes, key: bytes, chunk_index: int, nonce: bytes
) -> bytes:
    if len(nonce) != CHUNK_NONCE_BYTES:
        raise ValueError("nonce must be exactly 12 bytes")
    aesgcm = AESGCM(key)
    ct_and_tag = aesgcm.encrypt(nonce, plaintext, _index_aad(chunk_index))
    return nonce + ct_and_tag
