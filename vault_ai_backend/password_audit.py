

from __future__ import annotations

import hashlib
import logging
import unicodedata
from typing import Optional

from vault_core import get_db


logger = logging.getLogger(__name__)


WEAK_THRESHOLD = 45
MODERATE_THRESHOLD = 70


_COMMON_SUBSTRINGS_BASE: tuple[str, ...] = (
    "password", "qwerty", "letmein", "iloveyou", "admin",
    "welcome", "monkey", "1234567", "123456", "abc123",
)

                                                             
_COMMON_SUBSTRINGS_BY_LOCALE: dict[str, tuple[str, ...]] = {
    "ar": ("كلمةالمرور", "كلمة المرور"),
    "fr": ("motdepasse", "motdepass"),
    "es": ("contrasena", "contraseña"),
    "pt": ("senha",),
    "ru": ("пароль",),
    "zh": ("密码",),
    "ja": ("パスワード",),
    "ko": ("비밀번호",),
}

                                                                       
_COMMON_SUBSTRINGS: tuple[str, ...] = tuple(sorted({
    s.lower() for s in _COMMON_SUBSTRINGS_BASE
} | {
    s.lower()
    for tup in _COMMON_SUBSTRINGS_BY_LOCALE.values()
    for s in tup
}))


_KEYBOARD_LAYOUTS: dict[str, tuple[str, ...]] = {
    "qwerty": (
        "qwerty", "asdfgh", "zxcvbn",
        "qwertyuiop", "asdfghjkl", "zxcvbnm",
        "1qaz", "2wsx", "3edc", "4rfv", "5tgb", "6yhn", "7ujm",
        "qaz", "wsx", "edc", "rfv", "tgb", "yhn", "ujm",
    ),
    "azerty": (
        "azerty", "qsdfgh", "wxcvbn",
        "azertyuiop", "qsdfghjklm",
        "1aq", "2zs", "aze", "qsd",
    ),
    "qwertz": (
        "qwertz", "yxcvbn",
        "qwertzuiop", "yxcvbnm",
        "1qay", "qay",
    ),
    "dvorak": (
        "aoeu", "htns", "aoeuidhtns",
        "pyfgcrl", "qjkxbm",
    ),
    "jis": (
                                                                   
                                                                       
    ),
    "numeric": (
        "147", "258", "369", "789", "456",
        "1470", "2580", "159", "357",
    ),
    "mobile": (
        "1q2w", "qwer", "asdf", "sdfg", "zxcv",
                                                    
        "13579", "1235789",
    ),
    "alphabetic": (
        "abcdef", "abcdefg",
    ),
    "legacy": (
                                                                    
                                           
        "1234",
    ),
}


_KEYBOARD_WALKS: tuple[str, ...] = tuple(sorted({
    w.lower()
    for layout in _KEYBOARD_LAYOUTS.values()
    for w in layout
}))


def _char_class(ch: str) -> str:


    cat = unicodedata.category(ch)
    if cat == "Lu":
        return "upper"
    if cat == "Ll":
        return "lower"
    if cat in ("Lt", "Lo", "Lm", "Nl"):
        return "other_letter"
    if cat.startswith("N"):
        return "digit"
    return "symbol"


def _diversity_classes(pw: str) -> int:


    classes: set[str] = set()
    for ch in pw:
        classes.add(_char_class(ch))
        if len(classes) == 5:
            break
    return len(classes)


def score_password(pw: str) -> int:


    if not pw:
        return 0
    score = 0
    score += min(int(2.5 * len(pw)), 45)
    diversity = _diversity_classes(pw)
                                                                
                                                
    score += min(diversity * 7, 28)
    score += min(len(set(pw)), 27)

    p = pw.lower()
    if any(c in p for c in _COMMON_SUBSTRINGS):
        score -= 30
    if any(w in p for w in _KEYBOARD_WALKS):
        score -= 15
    if any(pw[i] == pw[i + 1] == pw[i + 2] for i in range(len(pw) - 2)):
        score -= 10
    if pw.isdigit():
        score -= 20
    if len(pw) < 6:
        score -= 30
    return max(0, min(score, 100))


def band_for(score: int) -> str:

    if score < WEAK_THRESHOLD:
        return "weak"
    if score < MODERATE_THRESHOLD:
        return "moderate"
    return "strong"


def hash_password(vault_id: str, password: str) -> bytes:


    h = hashlib.sha256()
    h.update(vault_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(password.encode("utf-8"))
    return h.digest()


def upsert_password_audit_safe(
    vault_id: str,
    vault_item_id: int,
    password: Optional[str],
    *,
    generated: bool = False,
) -> None:


    try:
        if not password:
            return
        h = hash_password(vault_id, password)
        s = score_password(password)
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO vault_password_audit
                        (vault_id, vault_item_id, password_hash_sha256,
                         password_strength_score, generated_by_vaultai)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (vault_id, vault_item_id) DO UPDATE SET
                        password_hash_sha256    = EXCLUDED.password_hash_sha256,
                        password_strength_score = EXCLUDED.password_strength_score,
                        -- Preserve generated=TRUE across manual edits:
                        -- only explicit generate paths may flip TRUE on.
                        generated_by_vaultai    = vault_password_audit.generated_by_vaultai
                                                  OR EXCLUDED.generated_by_vaultai,
                        updated_at              = NOW()
                    """,
                    (vault_id, vault_item_id, h, s, generated),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "upsert_password_audit_safe failed vault=%s item=%s: %s",
            vault_id, vault_item_id, e,
        )
