

import os
import sys

from cryptography.exceptions import InvalidTag

                                                      
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chunked_aead import (
    CHUNK_NONCE_BYTES,
    CHUNK_TAG_BYTES,
    encrypt_chunk,
    decrypt_chunk,
    _encrypt_chunk_with_nonce,
)


def assert_eq(actual, expected, label):
    if actual != expected:
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")
        sys.exit(1)
    print(f"  OK    {label}")


def assert_raises(exc, fn, label):
    try:
        fn()
    except exc:
        print(f"  OK    {label} (raised {exc.__name__})")
        return
    except Exception as e:
        print(f"  FAIL  {label}: raised {type(e).__name__}, expected {exc.__name__}")
        sys.exit(1)
    print(f"  FAIL  {label}: did not raise {exc.__name__}")
    sys.exit(1)


def main():
    key = os.urandom(32)
    plaintext = b"vaultai chunk one " * 1024          

                        
    frame = encrypt_chunk(plaintext, key, chunk_index=0)
    assert_eq(
        len(frame),
        CHUNK_NONCE_BYTES + len(plaintext) + CHUNK_TAG_BYTES,
        "frame length = 12 + N + 16",
    )

                   
    out = decrypt_chunk(frame, key, chunk_index=0)
    assert_eq(out, plaintext, "round-trip restores plaintext")

                                               
    assert_raises(
        InvalidTag,
        lambda: decrypt_chunk(frame, key, chunk_index=1),
        "wrong chunk_index rejects",
    )

                                                 
    tampered = bytearray(frame)
    tampered[CHUNK_NONCE_BYTES + 5] ^= 0x01                              
    assert_raises(
        InvalidTag,
        lambda: decrypt_chunk(bytes(tampered), key, chunk_index=0),
        "tampered ciphertext rejects",
    )

                                       
    wrong_key = os.urandom(32)
    assert_raises(
        InvalidTag,
        lambda: decrypt_chunk(frame, wrong_key, chunk_index=0),
        "wrong key rejects",
    )

                        
    assert_raises(
        ValueError,
        lambda: decrypt_chunk(b"\x00" * 27, key, chunk_index=0),
        "frame too short rejects",
    )

                           
    assert_raises(
        ValueError,
        lambda: encrypt_chunk(b"x", key, chunk_index=-1),
        "negative chunk_index rejects",
    )
    assert_raises(
        ValueError,
        lambda: encrypt_chunk(b"x", key, chunk_index=0x1_0000_0000),
        ">32-bit chunk_index rejects",
    )

                                                                          
    vec_key = bytes.fromhex(
        "000102030405060708090a0b0c0d0e0f"
        "101112131415161718191a1b1c1d1e1f"
    )
    vec_nonce = bytes.fromhex("0102030405060708090a0b0c")
    vec_plaintext = b"hello vaultai 9.8.A"
    vec_index = 7

    vec_frame = _encrypt_chunk_with_nonce(
        vec_plaintext, vec_key, vec_index, vec_nonce
    )
    out_vec = decrypt_chunk(vec_frame, vec_key, chunk_index=vec_index)
    assert_eq(out_vec, vec_plaintext, "test vector decrypts")

                                                     
    print()
    print("=== DETERMINISTIC TEST VECTOR ===")
    print(f"key (hex):        {vec_key.hex()}")
    print(f"nonce (hex):      {vec_nonce.hex()}")
    print(f"chunk_index:      {vec_index}")
    print(f"plaintext (utf8): {vec_plaintext.decode()}")
    print(f"frame (hex):      {vec_frame.hex()}")
    print("==================================")

    print("\nAll chunked AEAD tests passed.")


if __name__ == "__main__":
    main()
