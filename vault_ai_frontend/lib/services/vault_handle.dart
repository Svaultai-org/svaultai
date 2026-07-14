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
// The handle is what the SERVER stores as the vault's login lookup
// key. It is high-entropy and not derived from any user-supplied
// string, so a DB dump cannot be enumerated by candidate-name
// guessing.
//
// The user's chosen human-readable display name lives ONLY in
// ``vaults.display_name_ciphertext`` (AES-GCM under MVK) and is
// decrypted client-side after unlock.
//
// This file contains no cryptography. It is a random-byte generator
// plus a base32 formatter/parser.

import 'dart:math' show Random;
import 'dart:typed_data';

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
Uint8List generateVaultHandle() {
  final rng = Random.secure();
  final out = Uint8List(vaultHandleBytes);
  for (var i = 0; i < vaultHandleBytes; i++) {
    out[i] = rng.nextInt(256);
  }
  return out;
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
