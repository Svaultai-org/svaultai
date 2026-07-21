// Client-side exception classifier for the inheritance-credential
// reveal path.
//
// The reveal catch block used to emit a single generic reference
// (``INH-RETRIEVE-003``) for every failure mode — a malformed
// response, a base64 error, a bad key length, an AES-GCM
// authentication failure, and a post-decrypt JSON parse error all
// looked identical to the operator. On iOS Safari where the
// browser console is not practical to inspect, that opacity made
// the incident undebuggable.
//
// This file provides two pure functions:
//
//   * ``classifyRevealException(e)`` returns a specific reference
//     tag (``INH-RETRIEVE-003-AUTH``, ``INH-RETRIEVE-003-B64``, …)
//     naming exactly which stage of the decrypt pipeline failed.
//   * ``safeLengthsFromRawPkg(pkg)`` reads the retrieve-response
//     map and computes decoded byte lengths for each wire field,
//     tolerating null / wrong-type / malformed-base64 values. The
//     lengths are the only per-request data that leaves the device
//     — no ciphertext, no wrapped-key bytes, no nonces, no
//     credential material.
//
// Both functions are pure so the classifier can be unit-tested
// against synthetic exceptions without spinning up a widget tree.

library;

import 'dart:convert' show base64Url;

import 'package:cryptography/cryptography.dart'
    show SecretBoxAuthenticationError;


/// Reference tags surfaced in the UI. Each corresponds to a
/// distinct failure mode of the decrypt pipeline. Operators grep
/// backend logs for these strings via the ``[INH-CLIENT-DIAG]``
/// tag on the diagnostic ingest endpoint.
const String kRefRevealAuth    = 'INH-RETRIEVE-003-AUTH';
const String kRefRevealShape   = 'INH-RETRIEVE-003-SHAPE';
const String kRefRevealB64     = 'INH-RETRIEVE-003-B64';
const String kRefRevealKeyLen  = 'INH-RETRIEVE-003-KEYLEN';
const String kRefRevealPayload = 'INH-RETRIEVE-003-PAYLOAD';
const String kRefRevealOther   = 'INH-RETRIEVE-003-OTHER';


/// Coarse category derived from the reference tag. Sent to the
/// backend as a fixed short string so operator dashboards can
/// group without having to parse the full reference.
String revealCategoryFor(String referenceCode) {
  switch (referenceCode) {
    case kRefRevealAuth:    return 'auth';
    case kRefRevealShape:   return 'shape';
    case kRefRevealB64:     return 'b64';
    case kRefRevealKeyLen:  return 'keylen';
    case kRefRevealPayload: return 'payload';
    default:                return 'other';
  }
}


/// Classify a caught exception into one of the reveal reference
/// codes. The ordering is deliberate: more specific matches come
/// first (e.g. an AES-GCM authentication error is more specific
/// than "any StateError"), and the final fallback is OTHER.
///
/// Pure function — no I/O, no clock, no random. Tests exercise
/// every branch with synthesized exceptions.
String classifyRevealException(Object e) {
  // Stage 5: AES-GCM authentication tag mismatch. This is the
  // canonical "wrong key" outcome — the beneficiary's local sk
  // does not correspond to the pk the owner wrapped for. Highest
  // priority so a StateError-wrapping SecretBox failure never
  // gets miscategorised as KEYLEN.
  if (e is SecretBoxAuthenticationError) {
    return kRefRevealAuth;
  }

  // Stage 4: TypeError / NoSuchMethodError on the response-map
  // shape — e.g. `pkg['crypto_version'] as num` when the field
  // is missing / null / a string. Comes before FormatException
  // because `null.toString()` followed by base64 decode ends up
  // as a FormatException that we'd otherwise mis-attribute to B64.
  if (e is TypeError || e is NoSuchMethodError) {
    return kRefRevealShape;
  }

  // Stage 3: base64url decode failure on one of the wire fields.
  // FormatException with a base64-shaped message: "Invalid
  // character" / "Invalid length". Post-decrypt JSON parse is
  // handled below (PAYLOAD) before the generic B64 fallback.
  if (e is FormatException) {
    final msg = e.message.toLowerCase();
    // Post-decrypt json / utf8 errors travel as FormatException;
    // route them to PAYLOAD, not B64.
    if (msg.contains('unexpected character')
        || msg.contains('unexpected end of')
        || msg.contains('utf')
        || msg.contains('missing')
        || msg.contains('json')) {
      return kRefRevealPayload;
    }
    return kRefRevealB64;
  }

  // Stage 2b: post-decrypt state errors — the wrapped CEK unwrap
  // succeeded but its plaintext is not the expected 32-byte CEK,
  // OR the JSON payload is not a Map. These live inside
  // decryptInheritanceCredentials and are thrown as StateError.
  if (e is StateError) {
    final msg = e.message.toLowerCase();
    if (msg.contains('cek')
        || msg.contains('not a json object')
        || msg.contains('credential payload')) {
      return kRefRevealPayload;
    }
    // Stage 2a: byte-length invariants that surface before decrypt
    // (e.g. "ciphertext is shorter than the AES-GCM tag").
    return kRefRevealKeyLen;
  }

  // Stage 1: seed / public key length mismatch feeding into
  // newKeyPairFromSeed or SimplePublicKey. cryptography throws
  // ArgumentError with a length-related message.
  if (e is ArgumentError) {
    return kRefRevealKeyLen;
  }

  return kRefRevealOther;
}


/// Sanitised byte-length probe over the retrieve-response map.
/// Each length is computed defensively — a null / missing / wrong-
/// type / malformed base64 value yields null for that field so the
/// caller can still emit a diagnostic even if the response is
/// partially garbled.
///
/// No field VALUES appear in the returned map. Only integer
/// lengths (payload / nonces / wrapped key / ephemeral pk) plus
/// the (integer) crypto_version.
Map<String, int?> safeLengthsFromRawPkg(Map<String, dynamic>? pkg) {
  int? cryptoVersion;
  try {
    final v = pkg?['crypto_version'];
    if (v is num) {
      cryptoVersion = v.toInt();
    }
  } catch (_) {
    cryptoVersion = null;
  }

  int? decodeLen(dynamic v) {
    if (v is! String || v.isEmpty) return null;
    try {
      final padded = v + '=' * ((4 - v.length % 4) % 4);
      return base64Url.decode(padded).length;
    } catch (_) {
      return null;
    }
  }

  return <String, int?>{
    'crypto_version':           cryptoVersion,
    'encrypted_payload_len':    decodeLen(pkg?['encrypted_payload']),
    'payload_nonce_len':        decodeLen(pkg?['payload_nonce']),
    'wrapped_key_len':          decodeLen(pkg?['wrapped_key']),
    'wrapping_ephemeral_pk_len':
        decodeLen(pkg?['wrapping_ephemeral_pk']),
    'wrapping_nonce_len':       decodeLen(pkg?['wrapping_nonce']),
  };
}


/// User-facing message accompanying the reference tag. Kept short
/// and free of technical detail so it renders cleanly in a
/// SnackBar without leaking implementation hints.
String userMessageForReveal(String referenceCode) {
  switch (referenceCode) {
    case kRefRevealAuth:
      return "This device can't unlock these credentials. "
          "Sign out and sign back in with your PIN, then try again.";
    case kRefRevealShape:
    case kRefRevealB64:
    case kRefRevealKeyLen:
    case kRefRevealPayload:
      return "Could not read these credentials right now. "
          "Please try again in a moment.";
    default:
      return "Could not decrypt these credentials on this device.";
  }
}
