import os
import re
import base64
import hmac
import json
import logging
import hashlib
import secrets
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import HTTPException

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL")

def _parse_max_vault_bytes() -> int:


    default = 1 * 1024 * 1024 * 1024        
    raw = os.getenv("VAULTAI_DEFAULT_STORAGE_BYTES")
    if not raw:
        return default
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


MAX_VAULT_BYTES = _parse_max_vault_bytes()                                 
MAX_PIN_ATTEMPTS = 5
PIN_LOCKOUT_HOURS = 24
PIN_VERIFIER_PLAINTEXT = "vaultai_pin_ok"

                                                                 
KDF_TARGET_ITERATIONS = int(os.getenv("KDF_TARGET_ITERATIONS", "600000"))
KDF_LEGACY_ITERATIONS = 100000

                                                                   
MIN_PIN_LENGTH_NEW_VAULT = int(os.getenv("MIN_PIN_LENGTH_NEW_VAULT", "6"))


GENERAL_SENTINEL = "general"


def normalize_service(value: Optional[str]) -> str:


    if not value:
        return GENERAL_SENTINEL
    normalized = value.strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^\w\-\.\s]", "", normalized)
    return normalized or GENERAL_SENTINEL


def is_real_name(normalized: str) -> bool:

    return bool(normalized) and normalized != GENERAL_SENTINEL


DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))

_pool: Optional[ThreadedConnectionPool] = None


def _get_pool() -> ThreadedConnectionPool:

    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(
            minconn=DB_POOL_MIN,
            maxconn=DB_POOL_MAX,
            dsn=DATABASE_URL,
        )
        logger.info(
            "Initialized DB connection pool (min=%d, max=%d)",
            DB_POOL_MIN, DB_POOL_MAX,
        )
    return _pool


class _PooledConnection:


    __slots__ = ("_conn", "_pool", "_released")

    def __init__(self, conn, pool: ThreadedConnectionPool):
        self._conn = conn
        self._pool = pool
        self._released = False

    def close(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            if not self._conn.closed:
                self._conn.rollback()
        except Exception:
            pass
        try:
            self._pool.putconn(self._conn)
        except Exception:
            logger.exception("Failed returning connection to pool; discarding")
            try:
                self._conn.close()
            except Exception:
                pass

    def __getattr__(self, item):
                                                                     
                                                             
        return getattr(self._conn, item)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def get_db() -> _PooledConnection:


    pool = _get_pool()
    return _PooledConnection(pool.getconn(), pool)


def close_pool() -> None:


    global _pool
    if _pool is None:
        return
    try:
        _pool.closeall()
        logger.info("Closed DB connection pool")
    finally:
        _pool = None


def derive_key(pin: str, pin_salt: str, *, iterations: int) -> bytes:


    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=32,
        salt=base64.b64decode(pin_salt),
        iterations=iterations,
    )
    return kdf.derive(pin.encode())


def generate_pin_salt() -> str:

    return base64.b64encode(secrets.token_bytes(16)).decode()


PAIRING_CODE_TTL_MINUTES = int(os.getenv("PAIRING_CODE_TTL_MINUTES", "60"))

                                                                
_PAIRING_CODE_SALT_B64 = base64.b64encode(b"vaultai-pairing-fixed-salt-v1").decode()

                                                                      
_PAIRING_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _canonicalize_pairing_code(code: str) -> str:
    return (code or "").replace("-", "").replace(" ", "").upper().strip()


def generate_pairing_code() -> str:

    parts = ["".join(secrets.choice(_PAIRING_CODE_ALPHABET) for _ in range(n))
             for n in (3, 4, 4)]
    return "-".join(parts)


def hash_pairing_code(pairing_code: str) -> str:


    canonical = _canonicalize_pairing_code(pairing_code)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def derive_pairing_wrap_key(pairing_code: str) -> bytes:


    canonical = _canonicalize_pairing_code(pairing_code)
    return derive_key(canonical, _PAIRING_CODE_SALT_B64, iterations=KDF_TARGET_ITERATIONS)


def encrypt_message(message: str, key: bytes) -> str:
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, message.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_message(encrypted_b64: str, key: bytes) -> str:
    try:
        combined = base64.b64decode(encrypted_b64)
        nonce = combined[:12]
        ciphertext = combined[12:]
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid PIN or corrupted data")


def encrypt_bytes(data: bytes, key: bytes) -> str:
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_bytes(encrypted_b64: str, key: bytes) -> bytes:
    combined = base64.b64decode(encrypted_b64)
    nonce = combined[:12]
    ciphertext = combined[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def get_vault_id_for_name(vault_name: str) -> Optional[str]:


    if not vault_name:
        return None
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT vault_id FROM vaults WHERE vault_name = %s LIMIT 1",
            (vault_name,),
        )
        row = cur.fetchone()
        return str(row[0]) if row else None
    finally:
        conn.close()


def is_vault_zk_adopted(vault_id: str) -> bool:
    """Return True iff the vault has completed ZK adoption (has a
    Vault Handle + wrapped MVK on file). ZK-adopted vaults must not
    receive server-side plaintext persistence for user-derived
    metadata: the client is expected to encrypt and finalize.

    Safe: reads only structural columns (`vault_handle IS NOT NULL`).
    Does not derive any Vault key material.
    """
    if not vault_id:
        return False
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT (vault_handle IS NOT NULL)
                 FROM vaults WHERE vault_id = %s LIMIT 1""",
            (vault_id,),
        )
        row = cur.fetchone()
        return bool(row[0]) if row is not None else False
    except Exception:
        return False
    finally:
        conn.close()


def verify_vault_pin(vault_id: str, pin: str) -> bytes:


    if not pin:
        raise HTTPException(status_code=400, detail="PIN is required")
    if not vault_id:
        raise HTTPException(status_code=400, detail="vault_id is required")

    conn = get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT pin_salt, pin_verifier, locked_until, kdf_iterations,
                   must_reset, failed_pin_attempts
            FROM vaults
            WHERE vault_id = %s
            LIMIT 1
            """,
            (vault_id,),
        )
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Vault not found")

        if row.get("must_reset"):
            raise HTTPException(
                status_code=423,
                detail={
                    "code": "vault_frozen",
                    "message": "This vault has been frozen and cannot be unlocked.",
                },
            )

        cursor.execute("SELECT NOW() AS now")
        now_row = cursor.fetchone() or {}
        now = now_row.get("now")

        if row.get("locked_until") and now and row["locked_until"] > now:
            raise HTTPException(
                status_code=423,
                detail={
                    "code": "pin_locked",
                    "message": (
                        f"Too many wrong PIN attempts. Try again after "
                        f"{row['locked_until']}."
                    ),
                    "locked_until": row["locked_until"].isoformat(),
                },
            )

        pin_salt = row.get("pin_salt")
        pin_verifier = row.get("pin_verifier")
        iterations = int(row.get("kdf_iterations") or KDF_LEGACY_ITERATIONS)

        if not pin_salt or not pin_verifier:
            raise HTTPException(status_code=400, detail="PIN not initialized")

        key = derive_key(pin, pin_salt, iterations=iterations)
        try:
            valid = decrypt_message(pin_verifier, key) == PIN_VERIFIER_PLAINTEXT
        except Exception:
            valid = False

        if not valid:
            prior_locked_until = row.get("locked_until")
            prior_attempts = 0 if (
                prior_locked_until and now and prior_locked_until < now
            ) else int(row.get("failed_pin_attempts") or 0)
            new_attempts = prior_attempts + 1

            if new_attempts >= MAX_PIN_ATTEMPTS:
                cursor.execute(
                    """
                    UPDATE vaults
                    SET failed_pin_attempts = 0,
                        locked_until = NOW() + (INTERVAL '1 hour' * %s)
                    WHERE vault_id = %s
                    RETURNING locked_until
                    """,
                    (PIN_LOCKOUT_HOURS, vault_id),
                )
                locked_until = (cursor.fetchone() or {}).get("locked_until")
                conn.commit()
                raise HTTPException(
                    status_code=423,
                    detail={
                        "code": "pin_locked",
                        "message": (
                            f"Too many wrong PIN attempts. Locked for "
                            f"{PIN_LOCKOUT_HOURS} hours. Try again after {locked_until}."
                        ),
                        "locked_until": locked_until.isoformat() if locked_until else None,
                    },
                )

            cursor.execute(
                """
                UPDATE vaults
                SET failed_pin_attempts = %s,
                    locked_until = NULL
                WHERE vault_id = %s
                """,
                (new_attempts, vault_id),
            )
            conn.commit()

            attempts_left = max(0, MAX_PIN_ATTEMPTS - new_attempts)
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "invalid_pin",
                    "message": "Invalid PIN.",
                    "attempts_left": attempts_left,
                },
            )

        cursor.execute(
            """
            UPDATE vaults
            SET failed_pin_attempts = 0,
                locked_until = NULL
            WHERE vault_id = %s
            """,
            (vault_id,),
        )
        conn.commit()
        return key
    finally:
        conn.close()


def rotate_vault_kdf_if_needed(
    vault_id: str,
    pin: str,
    old_key: bytes,
) -> dict:


    conn = get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT pin_salt, kdf_iterations
            FROM vaults
            WHERE vault_id = %s
            LIMIT 1
            """,
            (vault_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Vault not found")

        current_iter = int(row.get("kdf_iterations") or KDF_LEGACY_ITERATIONS)
        if current_iter >= KDF_TARGET_ITERATIONS:
            return {
                "rotated": False,
                "pin_salt": row["pin_salt"],
                "kdf_iterations": current_iter,
                "new_key": None,
            }

        new_salt = generate_pin_salt()
        new_iterations = KDF_TARGET_ITERATIONS
        new_key = derive_key(pin, new_salt, iterations=new_iterations)
        new_pin_verifier = encrypt_message(PIN_VERIFIER_PLAINTEXT, new_key)

                                    
        cursor.execute(
            "SELECT id, encrypted_data FROM vault_items WHERE vault_id = %s",
            (vault_id,),
        )
        item_rows = cursor.fetchall() or []
        for item in item_rows:
            plaintext = decrypt_message(item["encrypted_data"], old_key)
            cursor.execute(
                "UPDATE vault_items SET encrypted_data = %s WHERE id = %s",
                (encrypt_message(plaintext, new_key), item["id"]),
            )

                                                             
        cursor.execute(
            """
            SELECT id, encrypted_file_data, extracted_text, extracted_text_encrypted
            FROM uploaded_files
            WHERE vault_id = %s
            """,
            (vault_id,),
        )
        file_rows = cursor.fetchall() or []
        for file_row in file_rows:
            raw_bytes = decrypt_bytes(file_row["encrypted_file_data"], old_key)
            new_file_data = encrypt_bytes(raw_bytes, new_key)

            new_extracted_text = file_row.get("extracted_text")
            if file_row.get("extracted_text_encrypted") and new_extracted_text:
                try:
                    plain_text = decrypt_message(new_extracted_text, old_key)
                    new_extracted_text = encrypt_message(plain_text, new_key)
                except Exception:
                    logger.warning(
                        "Could not re-encrypt extracted_text for file=%s; leaving in place",
                        file_row["id"],
                    )

            cursor.execute(
                """
                UPDATE uploaded_files
                SET encrypted_file_data = %s,
                    extracted_text = %s
                WHERE id = %s
                """,
                (new_file_data, new_extracted_text, file_row["id"]),
            )

        cursor.execute(
            """
            SELECT id, payload_ciphertext
            FROM vault_ai_memory
            WHERE vault_id = %s
              AND payload_ciphertext IS NOT NULL
              AND memory_key IS NULL
              AND memory_value IS NULL
            """,
            (vault_id,),
        )
        memory_rows = cursor.fetchall() or []
        for memory_row in memory_rows:
            raw_blob = memory_row.get("payload_ciphertext")
            if isinstance(raw_blob, memoryview):
                raw_bytes = raw_blob.tobytes()
            elif isinstance(raw_blob, bytes):
                raw_bytes = raw_blob
            else:
                raw_bytes = str(raw_blob).encode("utf-8")

            plaintext = decrypt_message(raw_bytes.decode("utf-8"), old_key)
            payload = json.loads(plaintext)
            canonical_key = (
                payload.get("canonical_key") if isinstance(payload, dict) else None
            )
            if not canonical_key:
                raise ValueError("ciphertext memory payload missing canonical_key")
            new_lookup_hash = hmac.new(
                new_key,
                f"vaultai-personal-memory/v1:{canonical_key}".encode("utf-8"),
                hashlib.sha256,
            ).digest()
            cursor.execute(
                """
                UPDATE vault_ai_memory
                SET payload_ciphertext = %s,
                    memory_lookup_hash = %s
                WHERE id = %s AND vault_id = %s
                """,
                (
                    encrypt_message(plaintext, new_key).encode("utf-8"),
                    new_lookup_hash,
                    memory_row["id"],
                    vault_id,
                ),
            )

        cursor.execute(
            """
            UPDATE vaults
            SET pin_salt = %s,
                pin_verifier = %s,
                kdf_iterations = %s
            WHERE vault_id = %s
            """,
            (new_salt, new_pin_verifier, new_iterations, vault_id),
        )
        conn.commit()

        logger.warning(
            "Rotated KDF for vault_id=%s: %d -> %d iters, "
            "%d items + %d files + %d memories re-encrypted",
            vault_id, current_iter, new_iterations,
            len(item_rows), len(file_rows), len(memory_rows),
        )

        return {
            "rotated": True,
            "pin_salt": new_salt,
            "kdf_iterations": new_iterations,
            "new_key": new_key,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
