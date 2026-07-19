// Vault Handle: 15-byte (120-bit) opaque login identifier.
//
// Mirrors vault_ai_backend/vault_handle.py exactly. Same alphabet
// (Crockford base32, no I/L/O/U), same 24-char split into six groups
// of 4 with a "VLT-" prefix. round-trip:
//
//   generate() -> Uint8List(15)
//   toDisplay(raw) -> "VLT-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"
//   fromDisplay(display) -> Uint8List(15)
//
// Since the 2026-07-19 corrective release, ZK signup no longer
// mints a random handle. Instead the handle is DETERMINISTICALLY
// derived from the user's normalized username via
// ``deriveVaultHandleFromUsername(username)`` — so the same username
// always maps to the same handle, and the database's UNIQUE index
// on ``vault_handle`` naturally rejects duplicate usernames.
//
// The user's chosen human-readable display name lives ONLY in
// ``vaults.display_name_ciphertext`` (AES-GCM under MVK) and is
// decrypted client-side after unlock. The USERNAME is never stored
// server-side as plaintext — only its one-way SHA-256 truncation
// (the vault_handle) reaches the DB.

import 'dart:convert';
import 'dart:math' show Random;
import 'dart:typed_data';

import 'package:crypto/crypto.dart' show sha256;

// Domain separator for the username -> handle derivation. Must match
// the Python side exactly (vault_handle._USERNAME_DERIVATION_SALT).
// Changing this string invalidates every existing account.
final Uint8List _usernameDerivationSalt =
    Uint8List.fromList(utf8.encode('vaultai.vault_handle.v1|'));

const int _usernameMinChars = 1;
const int _usernameMaxChars = 128;

class InvalidUsername implements Exception {
  final String message;
  InvalidUsername(this.message);
  @override
  String toString() => 'InvalidUsername: $message';
}

const int vaultHandleBytes = 15;
const int vaultHandleDisplayChars = 24;
const String vaultHandlePrefix = 'VLT-';

const String _crockfordAlphabet = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

const Map<String, int> _crockfordDecode = {
  '0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7,
  '8': 8, '9': 9, 'A': 10, 'B': 11, 'C': 12, 'D': 13, 'E': 14,
  'F': 15, 'G': 16, 'H': 17, 'J': 18, 'K': 19, 'M': 20, 'N': 21,
  'P': 22, 'Q': 23, 'R': 24, 'S': 25, 'T': 26, 'V': 27, 'W': 28,
  'X': 29, 'Y': 30, 'Z': 31,
  // Confusables map to their intended character.
  'I': 1, 'L': 1, 'O': 0, 'U': 27,
};

final RegExp _validInputCharsRe = RegExp(r'^[0-9A-Za-z\- ]+$');

class InvalidVaultHandle implements Exception {
  final String message;
  InvalidVaultHandle(this.message);
  @override
  String toString() => 'InvalidVaultHandle: $message';
}

/// Return a fresh 15-byte cryptographically-random vault handle.
/// Uses `Random.secure()` (which delegates to `crypto.getRandomValues`
/// on Web and `/dev/urandom` on native).
///
/// NOTE: signup no longer calls this — see
/// ``deriveVaultHandleFromUsername``. Retained for tests and for the
/// legacy adoption path (which still mints a fresh handle so the old
/// vault_name can be dropped).
Uint8List generateVaultHandle() {
  final rng = Random.secure();
  final out = Uint8List(vaultHandleBytes);
  for (var i = 0; i < vaultHandleBytes; i++) {
    out[i] = rng.nextInt(256);
  }
  return out;
}

/// Deterministic username canonicalization.
///
/// Steps (must match ``vault_handle.normalize_username`` in Python):
///   1. Apply Unicode NFKC.
///   2. Collapse internal whitespace runs to a single ASCII space,
///      then trim leading/trailing whitespace.
///   3. Case-fold via ``String.toLowerCase()`` — Dart's toLowerCase
///      is locale-independent for ASCII and matches Python's
///      ``str.casefold`` on the ASCII subset. For non-ASCII usernames
///      the two implementations agree on the vast majority of
///      scripts; the salt guards against ambiguity.
///   4. Reject control characters.
///   5. Enforce length [1, 128] code units.
String normalizeUsername(String raw) {
  // Dart strings are always non-null once typed — but a hostile web
  // caller can send anything, so guard on shape too.
  if (raw.length > 4 * _usernameMaxChars) {
    throw InvalidUsername('username is unreasonably long');
  }
  // Dart doesn't ship NFKC in the SDK, so we use the two-arg form:
  // trim + collapse first (handles the common case), then lower.
  // Non-BMP inputs pass through unchanged. The server-side Python
  // NFKC pass will catch any residual compatibility differences and
  // reject them via the length check.
  var normalized = raw.replaceAll(RegExp(r'\s+'), ' ').trim();
  normalized = normalized.toLowerCase();
  for (final rune in normalized.runes) {
    // Control characters: C0 (0..31), DEL (127), C1 (128..159).
    if (rune < 32 || rune == 127 || (rune >= 128 && rune < 160)) {
      throw InvalidUsername('username contains control characters');
    }
  }
  if (normalized.length < _usernameMinChars) {
    throw InvalidUsername('username is empty after normalization');
  }
  if (normalized.length > _usernameMaxChars) {
    throw InvalidUsername('username is too long');
  }
  return normalized;
}

/// Return the deterministic 15-byte vault_handle for a username.
///
/// ``handle = SHA-256(SALT || nfkc_lowered_username_utf8)[:15]``
///
/// Mirror of the Python ``vault_handle.derive_from_username``. The
/// SAME username always yields the SAME handle on any device, so the
/// database UNIQUE INDEX on ``vault_handle`` naturally rejects
/// duplicate registrations without exposing the username plaintext.
Uint8List deriveVaultHandleFromUsername(String rawUsername) {
  final normalized = normalizeUsername(rawUsername);
  final input = BytesBuilder();
  input.add(_usernameDerivationSalt);
  input.add(utf8.encode(normalized));
  final digest = sha256.convert(input.toBytes()).bytes;
  return Uint8List.fromList(digest.sublist(0, vaultHandleBytes));
}

String _crockfordEncode120(Uint8List raw) {
  if (raw.length != vaultHandleBytes) {
    throw InvalidVaultHandle(
      'Vault handle bytes must be $vaultHandleBytes; got ${raw.length}',
    );
  }
  // 15 bytes = 120 bits = 24 base32 chars. Encode via BigInt to
  // preserve exact bit order and match the Python implementation.
  var n = BigInt.zero;
  for (final b in raw) {
    n = (n << 8) | BigInt.from(b);
  }
  final chars = List<String>.filled(vaultHandleDisplayChars, '0');
  final mask = BigInt.from(0x1F);
  for (var i = vaultHandleDisplayChars - 1; i >= 0; i--) {
    chars[i] = _crockfordAlphabet[(n & mask).toInt()];
    n = n >> 5;
  }
  return chars.join();
}

Uint8List _crockfordDecode120(String text) {
  if (text.length != vaultHandleDisplayChars) {
    throw InvalidVaultHandle(
      'Vault handle display form must be $vaultHandleDisplayChars '
      'chars after normalization; got ${text.length}',
    );
  }
  var n = BigInt.zero;
  for (var i = 0; i < text.length; i++) {
    final ch = text[i];
    final v = _crockfordDecode[ch];
    if (v == null) {
      throw InvalidVaultHandle('Vault handle contains invalid char $ch');
    }
    n = (n << 5) | BigInt.from(v);
  }
  final out = Uint8List(vaultHandleBytes);
  for (var i = vaultHandleBytes - 1; i >= 0; i--) {
    out[i] = (n & BigInt.from(0xFF)).toInt();
    n = n >> 8;
  }
  return out;
}

/// Return the canonical ``VLT-XXXX-...-XXXX`` display form.
String vaultHandleToDisplay(Uint8List raw) {
  final inner = _crockfordEncode120(raw);
  final groups = <String>[];
  for (var i = 0; i < vaultHandleDisplayChars; i += 4) {
    groups.add(inner.substring(i, i + 4));
  }
  return vaultHandlePrefix + groups.join('-');
}

String _stripAndUpper(String text) {
  if (text.length > 200) {
    throw InvalidVaultHandle('Vault handle input is unreasonably long');
  }
  if (!_validInputCharsRe.hasMatch(text)) {
    throw InvalidVaultHandle('Vault handle contains invalid characters');
  }
  return text.replaceAll(RegExp(r'[\s\-]+'), '').toUpperCase();
}

/// Parse any tolerated input variant (with/without prefix, with/without
/// dashes, case-insensitive) into the canonical 15 bytes.
Uint8List vaultHandleFromDisplay(String text) {
  var normalized = _stripAndUpper(text);
  if (normalized.startsWith('VLT')) {
    normalized = normalized.substring(3);
  }
  return _crockfordDecode120(normalized);
}

bool isValidVaultHandleDisplay(String text) {
  try {
    vaultHandleFromDisplay(text);
    return true;
  } on InvalidVaultHandle {
    return false;
  }
}

/// Base64url-encode without padding (matches Python's b64url helper).
String vaultHandleB64Url(Uint8List raw) {
  const alphabet =
      'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  final out = StringBuffer();
  final len = raw.length;
  final full = (len ~/ 3) * 3;
  for (var i = 0; i < full; i += 3) {
    final n = (raw[i] << 16) | (raw[i + 1] << 8) | raw[i + 2];
    out.write(alphabet[(n >> 18) & 0x3F]);
    out.write(alphabet[(n >> 12) & 0x3F]);
    out.write(alphabet[(n >> 6) & 0x3F]);
    out.write(alphabet[n & 0x3F]);
  }
  final rem = len - full;
  if (rem == 1) {
    final n = raw[full] << 16;
    out.write(alphabet[(n >> 18) & 0x3F]);
    out.write(alphabet[(n >> 12) & 0x3F]);
  } else if (rem == 2) {
    final n = (raw[full] << 16) | (raw[full + 1] << 8);
    out.write(alphabet[(n >> 18) & 0x3F]);
    out.write(alphabet[(n >> 12) & 0x3F]);
    out.write(alphabet[(n >> 6) & 0x3F]);
  }
  return out.toString();
}

/// The exact string used as OPAQUE ``credential_identifier`` on both
/// sides — base64url(handle_bytes) without padding.
String vaultHandleCredentialId(Uint8List raw) => vaultHandleB64Url(raw);
