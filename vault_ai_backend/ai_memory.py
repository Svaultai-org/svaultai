

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from vault_core import get_db
                                                                     
                                                      
from taxonomy import ALLOWED_MEMORY_TYPES as _TAXONOMY_ALLOWED_MEMORY_TYPES


logger = logging.getLogger(__name__)


MAX_MEMORY_VALUE_LEN = 500
MAX_MEMORY_KEY_LEN = 100

                                                          
ALLOWED_MEMORY_TYPES = _TAXONOMY_ALLOWED_MEMORY_TYPES


_SECRET_KEYWORDS: tuple[str, ...] = (
    "password", "passcode", "pin:", "cvv", "ssn", "social security",
    "seed phrase", "private key", "secret key", "api key",
    "authentication code", "2fa code", "mfa code", "otp",
    "credit card", "card number", "account number",
                                      
    "mnemonic phrase", "recovery phrase", "wallet address",
    "private wallet", "keystore", "auth token", "session token",
    "refresh token",
)
_TWELVE_DIGITS_RE = re.compile(r"\d{12,}")
_LONG_HEX_RE = re.compile(r"^[0-9a-fA-F]{32,}$")
_PEM_RE = re.compile(r"-----BEGIN [A-Z ]+-----")
_JWT_RE = re.compile(
    r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)
_ETH_ADDR_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_BEARER_RE = re.compile(r"\bbearer\s+\S{8,}", re.IGNORECASE)
_API_KEY_PREFIX_RE = re.compile(r"\b(?:sk|pk)[-_][A-Za-z0-9_-]{16,}\b")
                                                                 
                                                               
_MNEMONIC_RE = re.compile(
    r"^\s*(?:[a-z]{3,8}\s+){11,23}[a-z]{3,8}\s*$"
)
                                                                   
                                                   
_BASE58_RUN_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{30,}")


def _looks_like_base58_address(s: str) -> bool:
    for m in _BASE58_RUN_RE.finditer(s):
        chunk = m.group(0)
        if any(c.isdigit() for c in chunk):
            return True
    return False


def is_enabled() -> bool:


    return os.getenv("VAULTAI_AI_MEMORY_ENABLED", "true").lower() == "true"


def is_forbidden_memory_value(text: Optional[str]) -> bool:


    if not text:
        return True
    s = text.strip()
    if not s or len(s) > MAX_MEMORY_VALUE_LEN:
        return True
    low = s.lower()
                                                              
    for kw in _SECRET_KEYWORDS:
        if kw in low:
            return True
                                                                    
    if _TWELVE_DIGITS_RE.search(s):
        return True
                                                                      
    if (len(s) >= 10 and " " not in s
            and re.search(r"[a-z]", s)
            and re.search(r"[A-Z]", s)
            and re.search(r"\d", s)
            and re.search(r"[^A-Za-z0-9]", s)):
        return True
                                                      
    if _LONG_HEX_RE.match(s):
        return True
                                                   
    if _PEM_RE.search(s):
        return True
                                                         
    if _JWT_RE.search(s):
        return True
                                                    
    if _ETH_ADDR_RE.search(s):
        return True
                             
    if _BEARER_RE.search(s):
        return True
                                                            
    if _API_KEY_PREFIX_RE.search(s):
        return True
                                                                
    if _MNEMONIC_RE.match(s):
        return True
                                                    
    if _looks_like_base58_address(s):
        return True
    return False


def slugify_memory_key(s: Optional[str]) -> str:


    if not s:
        return ""
    s = s.strip().lower()
                                                                  
                                                             
    s = re.sub(r"[\W]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:MAX_MEMORY_KEY_LEN]


_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def tokenize_text(text: Optional[str]) -> list[str]:


    if not text:
        return []
    out = []
    for tok in _TOKEN_RE.findall(text):
        t = tok.lower()
        if len(t) >= 2:
            out.append(t)
    return out


def _derive_h5_memory_fields(
    key: str, val: str,
) -> tuple[Optional[str], Optional[str], Optional[str]]:


    try:
        from vault_language_engine import detect_language, normalize_for_cluster
        from locales import detect_script
                                                                  
                                                                
        lang = detect_language(val, user_preferred="en")
        script = detect_script(val) or "other"
        norm = normalize_for_cluster(key)
        return (lang, script, norm or None)
    except Exception:
        return (None, None, None)


def _parse_event_date(value) -> Optional[str]:


    if not value:
        return None
    try:
        s = str(value).strip()
        if len(s) < 10:
            return None
                             
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s[:10])
        if not m:
            return None
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1900 <= y <= 2100):
            return None
        if not (1 <= mo <= 12):
            return None
        if not (1 <= d <= 31):
            return None
        return f"{y:04d}-{mo:02d}-{d:02d}"
    except Exception:
        return None


def get_active_memory(
    vault_id: str, memory_type: str, memory_key: str,
) -> Optional[dict]:


    if not is_enabled():
        return None
    try:
        key = slugify_memory_key(memory_key)
        if not key or memory_type not in ALLOWED_MEMORY_TYPES:
            return None
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, memory_value, event_date,
                              confidence, created_at, updated_at
                       FROM vault_ai_memory
                       WHERE vault_id=%s
                         AND memory_type=%s AND memory_key=%s
                         AND superseded_at IS NULL""",
                    (vault_id, memory_type, key),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id":           row[0],
                    "memory_value": row[1],
                    "event_date":   row[2].isoformat() if row[2] else None,
                    "confidence":   float(row[3] or 1.0),
                    "created_at":   row[4],
                    "updated_at":   row[5],
                }
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "get_active_memory failed vault=%s type=%s key=%s: %s",
            vault_id, memory_type, memory_key, e,
        )
        return None


def upsert_memory_safe(
    vault_id: str,
    memory_type: str,
    memory_key: str,
    memory_value: str,
    *,
    event_date: Optional[str] = None,
) -> bool:


    result = update_memory_safe(
        vault_id, memory_type, memory_key, memory_value,
        event_date=event_date,
    )
    return result.get("ok", False) if result else False


def _update_memory_zk_ciphertext(
    *,
    vault_id: str,
    memory_type: str,
    lookup_hash: bytes,
    payload_ciphertext: bytes,
) -> Optional[dict]:
    """Ciphertext-first memory write for a ZK/adopted vault.

    Inserts a new memory row with only:
      * vault_id, memory_type            (structural)
      * payload_ciphertext               (opaque body)
      * memory_lookup_hash               (32-byte HMAC for supersede)
    Every readable legacy column (memory_key, memory_value,
    memory_normalized_key, event_date, memory_language,
    memory_script) is NULL from the outset.

    Supersede runs against ``memory_lookup_hash`` — replaces any
    active row for the same (vault_id, memory_lookup_hash).
    """
    if memory_type not in ALLOWED_MEMORY_TYPES:
        return None
    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id FROM vault_ai_memory
                          WHERE vault_id = %s
                            AND memory_type = %s
                            AND memory_lookup_hash = %s
                            AND superseded_at IS NULL""",
                    (vault_id, memory_type, lookup_hash),
                )
                prior = cur.fetchone()

                cur.execute(
                    """INSERT INTO vault_ai_memory
                          (vault_id, memory_type,
                           memory_key, memory_value, event_date,
                           confidence, source,
                           memory_language, memory_script,
                           memory_normalized_key,
                           payload_ciphertext, memory_lookup_hash)
                       VALUES (%s, %s,
                               NULL, NULL, NULL,
                               1.0, 'chat',
                               NULL, NULL,
                               NULL,
                               %s, %s)
                       RETURNING id""",
                    (vault_id, memory_type,
                     payload_ciphertext, lookup_hash),
                )
                new_id = cur.fetchone()[0]

                if prior is not None:
                    prior_id = prior[0]
                    cur.execute(
                        """UPDATE vault_ai_memory
                              SET superseded_at    = NOW(),
                                  superseded_by_id = %s
                            WHERE id = %s""",
                        (new_id, prior_id),
                    )
                    conn.commit()
                    return {
                        "ok":     True,
                        "status": "updated",
                        "new_id": new_id,
                    }
                conn.commit()
                return {
                    "ok":     True,
                    "status": "inserted",
                    "new_id": new_id,
                }
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "[AI-MEMORY][ZK] insert failed vault=%s type=%s: %s",
            vault_id, memory_type, e,
        )
        return None


def update_memory_safe(
    vault_id: str,
    memory_type: str,
    memory_key: str,
    memory_value: str,
    *,
    event_date: Optional[str] = None,
    # ZK ciphertext-first mode: when both are supplied, the row is
    # INSERTed with payload_ciphertext + memory_lookup_hash and
    # every readable legacy column (memory_key, memory_value,
    # memory_normalized_key) as NULL from the outset. Supersede /
    # dedup runs against memory_lookup_hash instead of the plaintext
    # (vault_id, memory_type, memory_key) tuple.
    zk_lookup_hash: Optional[bytes] = None,
    zk_payload_ciphertext: Optional[bytes] = None,
) -> Optional[dict]:


    if not is_enabled():
        return None
    if (zk_lookup_hash is None) != (zk_payload_ciphertext is None):
        # Mixed shape — refuse.
        return None
    if zk_lookup_hash is not None:
        if len(zk_lookup_hash) != 32:
            return None
        return _update_memory_zk_ciphertext(
            vault_id=vault_id,
            memory_type=memory_type,
            lookup_hash=zk_lookup_hash,
            payload_ciphertext=zk_payload_ciphertext,
        )
    try:
        if memory_type not in ALLOWED_MEMORY_TYPES:
            return None
        key = slugify_memory_key(memory_key)
        val = (memory_value or "").strip()
        if not key or not val:
            return None
        if len(val) > MAX_MEMORY_VALUE_LEN:
            return None
        if is_forbidden_memory_value(val):
            return None
        ev = _parse_event_date(event_date)

        conn = get_db()
        try:
            with conn.cursor() as cur:
                                                         
                cur.execute(
                    """SELECT id, memory_value FROM vault_ai_memory
                       WHERE vault_id=%s
                         AND memory_type=%s AND memory_key=%s
                         AND superseded_at IS NULL""",
                    (vault_id, memory_type, key),
                )
                prior = cur.fetchone()

                                                                     
                mem_lang, mem_script, norm_key = _derive_h5_memory_fields(
                    key, val,
                )

                if prior is None:
                                                 
                    cur.execute(
                        """INSERT INTO vault_ai_memory
                              (vault_id, memory_type,
                               memory_key, memory_value, event_date,
                               confidence, source,
                               memory_language, memory_script,
                               memory_normalized_key)
                           VALUES (%s, %s, %s, %s, %s, %s, 'chat',
                                   %s, %s, %s)""",
                        (vault_id, memory_type, key, val, ev,
                         1.0, mem_lang, mem_script, norm_key),
                    )
                    conn.commit()
                    return {
                        "ok":          True,
                        "status":      "inserted",
                        "prior_value": None,
                        "new_value":   val,
                        "key":         key,
                    }

                prior_id, prior_value = prior
                if (prior_value or "").strip() == val:
                                               
                    cur.execute(
                        """UPDATE vault_ai_memory
                           SET event_date = COALESCE(%s, event_date),
                               updated_at = NOW()
                           WHERE id=%s""",
                        (ev, prior_id),
                    )
                    conn.commit()
                    return {
                        "ok":          True,
                        "status":      "unchanged",
                        "prior_value": None,
                        "new_value":   val,
                        "key":         key,
                    }

                                                                  
                cur.execute(
                    """UPDATE vault_ai_memory
                       SET superseded_at = NOW()
                       WHERE id=%s""",
                    (prior_id,),
                )
                cur.execute(
                    """INSERT INTO vault_ai_memory
                          (vault_id, memory_type,
                           memory_key, memory_value, event_date,
                           confidence, source,
                           memory_language, memory_script,
                           memory_normalized_key)
                       VALUES (%s, %s, %s, %s, %s, %s, 'chat',
                               %s, %s, %s)
                       RETURNING id""",
                    (vault_id, memory_type, key, val, ev,
                     1.0, mem_lang, mem_script, norm_key),
                )
                new_id = cur.fetchone()[0]
                cur.execute(
                    """UPDATE vault_ai_memory
                       SET superseded_by_id = %s
                       WHERE id = %s""",
                    (new_id, prior_id),
                )
                conn.commit()
                return {
                    "ok":          True,
                    "status":      "updated",
                    "prior_value": prior_value,
                    "new_value":   val,
                    "key":         key,
                }
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "update_memory_safe failed vault=%s type=%s key=%s: %s",
            vault_id, memory_type, memory_key, e,
        )
        return None
