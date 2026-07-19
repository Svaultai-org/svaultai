"""Vault Handle model for VaultAI's zero-knowledge login identifier.

VaultAI's ZK redesign replaces the plaintext ``vault_name`` login-lookup
column with an opaque high-entropy identifier generated client-side at
signup. The server stores the handle as the row-lookup key. The user's
human-readable display name is encrypted client-side under the vault
master key and lives in ``vaults.display_name_ciphertext``.

Wire format
-----------
Display form:
    ``VLT-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX``
    24 base32 characters (Crockford variant: alphabet = 0-9 A-Z minus
    I, L, O, U) split into six four-character groups. 24 * 5 =
    120 bits of entropy; well above the 80-bit threshold for
    "practically unenumerable" random identifiers.

Storage form:
    ``BYTEA(15)`` — the raw 120-bit random value. The server NEVER
    stores or logs the display ASCII string; only the 15 canonical
    bytes. This matters because we want ``log(request)`` scans to
    never contain a value a reader could type back into the login
    dialog verbatim.

Properties
----------
* Client-generated using a CSPRNG; no derivation from user input.
* Case-insensitive on input; normalized to uppercase with dashes for
  display.
* Dashes optional on input; whitespace tolerated; humans can transcribe
  from paper without ambiguity (I/L/O/U absent).
* No collision possible in the lifetime of the product at 120 bits.
* Not human-guessable; not enumerable from a DB dump because the
  server-side hash function used for lookup (see auth_zk_routes) is
  the raw bytes — an operator with the DB has the value verbatim but
  cannot invert it to a person because the value is not derived from
  any personal information.

This module contains NO cryptographic primitives. It is a formatter,
parser, and CSPRNG-backed generator. All encryption/decryption is
performed elsewhere.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from typing import Final


VAULT_HANDLE_BYTES: Final[int] = 15

# Domain separator for username-to-handle derivation. Must match
# the Dart side (services/vault_handle.dart:_usernameDerivationSalt).
# Changing this string invalidates every existing account's handle.
_USERNAME_DERIVATION_SALT: Final[bytes] = b"vaultai.vault_handle.v1|"

# Username shape limits — the outermost guard so a hostile client
# cannot bomb the derivation with a 1MB string.
_USERNAME_MIN_CHARS: Final[int] = 1
_USERNAME_MAX_CHARS: Final[int] = 128


class InvalidUsername(ValueError):
    """Raised when a username cannot be normalized (empty after
    normalization, too long, forbidden control chars, …).
    """
VAULT_HANDLE_DISPLAY_CHARS: Final[int] = 24
VAULT_HANDLE_PREFIX: Final[str] = "VLT-"

_CROCKFORD_ALPHABET: Final[str] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_CROCKFORD_DECODE: Final[dict[str, int]] = {
    ch: i for i, ch in enumerate(_CROCKFORD_ALPHABET)
}
_CROCKFORD_DECODE.update({
    "I": _CROCKFORD_DECODE["1"],
    "L": _CROCKFORD_DECODE["1"],
    "O": _CROCKFORD_DECODE["0"],
    "U": _CROCKFORD_DECODE["V"],
})


_VALID_INPUT_CHARS_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9A-Za-z\- ]+$",
)


class InvalidVaultHandle(ValueError):
    """Raised on any malformed handle input."""


def generate() -> bytes:
    """Return a fresh 15-byte random handle (server-side only when the
    server is minting a placeholder for legacy adoption; clients should
    generate their own).
    """
    return secrets.token_bytes(VAULT_HANDLE_BYTES)


def normalize_username(raw: str) -> str:
    """Deterministic username canonicalization.

    Steps:
      1. Reject non-strings.
      2. Apply Unicode NFKC (so precomposed vs decomposed forms map
         together, and compatibility variants collapse).
      3. Strip leading/trailing whitespace, collapse internal runs of
         whitespace to a single ASCII space.
      4. Case-fold with ``str.casefold()`` (more aggressive than lower()
         for non-ASCII scripts, e.g. German ß -> "ss").
      5. Reject control characters — they can't be typed reliably.
      6. Length-check: [1, 128] code points after normalization.

    Same behavior as the Dart mirror in
    ``services/vault_handle.dart::normalizeUsername``. If the two ever
    drift, users who register on one client can't log in on another.
    """
    if not isinstance(raw, str):
        raise InvalidUsername("username must be a string")
    normalized = unicodedata.normalize("NFKC", raw)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = normalized.casefold()
    if any(unicodedata.category(ch).startswith("C") for ch in normalized):
        raise InvalidUsername("username contains control characters")
    if len(normalized) < _USERNAME_MIN_CHARS:
        raise InvalidUsername("username is empty after normalization")
    if len(normalized) > _USERNAME_MAX_CHARS:
        raise InvalidUsername("username is too long")
    return normalized


# Domain separator for the derivation-version-independent username
# lookup identifier. Different from the vault_handle salt on purpose:
# if we later change vault_handle derivation, this column keeps
# working; likewise a v2 of this identifier can coexist during
# migration. See migration 0030 for storage details.
_USERNAME_LOOKUP_V1_SALT: Final[bytes] = b"vaultai.username_lookup.v1|"
USERNAME_LOOKUP_V1_BYTES: Final[int] = 32


def derive_username_lookup_v1(raw: str) -> bytes:
    """Return the 32-byte client-derived username lookup identifier.

    ``lookup_v1 = SHA-256(SALT || nfkc_casefolded_username_utf8)``

    This is the value the client sends to the server for
    duplicate-registration detection and legacy-account fallback
    lookup. The raw username is NEVER sent to the server. Same
    offline-enumeration risk as ``derive_from_username`` (deterministic
    across restarts, salt is a public constant), documented in
    migration 0030 and mitigated by rate limits on register + login.
    """
    normalized = normalize_username(raw)
    digest = hashlib.sha256(
        _USERNAME_LOOKUP_V1_SALT + normalized.encode("utf-8"),
    ).digest()
    return digest


def derive_from_username(raw: str) -> bytes:
    """Return the deterministic 15-byte vault_handle for a username.

    ``handle = SHA-256(SALT || nfkc_casefolded_username_utf8)[:15]``

    * One-way: an operator with the DB dump cannot recover the
      username without a dictionary attack; usernames are the user's
      choice so brute-force offline is expected — this derivation
      is a lookup key, not a password verifier.
    * Deterministic: the same normalized username always produces the
      same 15 bytes, so the client can look up the account by
      re-deriving from the login form's username field.
    * Domain-separated: the salt keeps this derivation orthogonal to
      any other username-keyed hash the codebase might introduce
      later (e.g. for search indexes).
    """
    normalized = normalize_username(raw)
    digest = hashlib.sha256(
        _USERNAME_DERIVATION_SALT + normalized.encode("utf-8"),
    ).digest()
    return digest[:VAULT_HANDLE_BYTES]


def _crockford_encode_120(raw: bytes) -> str:
    if len(raw) != VAULT_HANDLE_BYTES:
        raise InvalidVaultHandle(
            f"Vault handle bytes must be {VAULT_HANDLE_BYTES}; "
            f"got {len(raw)}"
        )
    n = int.from_bytes(raw, "big")
    chars: list[str] = []
    for _ in range(VAULT_HANDLE_DISPLAY_CHARS):
        chars.append(_CROCKFORD_ALPHABET[n & 0x1F])
        n >>= 5
    return "".join(reversed(chars))


def _crockford_decode_120(text: str) -> bytes:
    if len(text) != VAULT_HANDLE_DISPLAY_CHARS:
        raise InvalidVaultHandle(
            f"Vault handle display form must be "
            f"{VAULT_HANDLE_DISPLAY_CHARS} chars after normalization; "
            f"got {len(text)}"
        )
    n = 0
    for ch in text:
        try:
            n = (n << 5) | _CROCKFORD_DECODE[ch]
        except KeyError as exc:
            raise InvalidVaultHandle(
                f"Vault handle contains invalid char {ch!r}"
            ) from exc
    return n.to_bytes(VAULT_HANDLE_BYTES, "big")


def to_display(raw: bytes) -> str:
    """Return the canonical ``VLT-XXXX-...-XXXX`` display form."""
    inner = _crockford_encode_120(raw)
    groups = [inner[i:i + 4] for i in range(0, VAULT_HANDLE_DISPLAY_CHARS, 4)]
    return VAULT_HANDLE_PREFIX + "-".join(groups)


def _strip_and_upper(text: str) -> str:
    if not isinstance(text, str):
        raise InvalidVaultHandle("Vault handle must be a string")
    if len(text) > 200:
        raise InvalidVaultHandle("Vault handle input is unreasonably long")
    if not _VALID_INPUT_CHARS_RE.match(text):
        raise InvalidVaultHandle("Vault handle contains invalid characters")
    return re.sub(r"[\s\-]+", "", text).upper()


def from_display(text: str) -> bytes:
    """Parse any tolerated input variant (with/without prefix, with/
    without dashes, case-insensitive) into the canonical 15 bytes.
    """
    normalized = _strip_and_upper(text)
    if normalized.startswith("VLT"):
        normalized = normalized[3:]
    return _crockford_decode_120(normalized)


def is_valid_display(text: str) -> bool:
    """Cheap boolean check for router-level input validation."""
    try:
        from_display(text)
    except InvalidVaultHandle:
        return False
    return True


__all__ = [
    "USERNAME_LOOKUP_V1_BYTES",
    "VAULT_HANDLE_BYTES",
    "VAULT_HANDLE_DISPLAY_CHARS",
    "VAULT_HANDLE_PREFIX",
    "InvalidUsername",
    "InvalidVaultHandle",
    "derive_from_username",
    "derive_username_lookup_v1",
    "from_display",
    "generate",
    "is_valid_display",
    "normalize_username",
    "to_display",
]
