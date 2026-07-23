// Inheritance credential escrow — client-side crypto.
//
// The owner generates a random Credential Encryption Key (CEK),
// encrypts the versioned JSON payload {version, username, pin,
// created_at} under it with AES-GCM-256, then wraps the CEK for
// the beneficiary using X25519-ECDH → HKDF-SHA256 → AES-GCM-256.
//
// The server stores only opaque bytes (payload ciphertext, nonces,
// wrapped CEK, ephemeral public key, crypto_version). It has no
// route by which it can decrypt any of this material.
//
// Composition (audited primitives only, from `cryptography`):
//
//   CEK              = 32 random bytes
//   payload_nonce    = 12 random bytes
//   encrypted_payload = AES-GCM-256(CEK, payload_nonce, JSON)
//
//   eph              = X25519 keypair
//   shared_secret    = X25519(eph.sk, beneficiary.pk_vault_public)
//   K_wrap           = HKDF-SHA256(shared_secret,
//                                  salt=eph.pub,
//                                  info="vaultai.inh-cred.v1",
//                                  32)
//   wrapping_nonce   = 12 random bytes
//   wrapped_key      = AES-GCM-256(K_wrap, wrapping_nonce, CEK)
//
// Wire encoding: base64url without padding on every byte-valued
// field.
//
// Version 1 is the only version defined. Future versions bump
// `crypto_version` and change info-string.

import 'dart:convert';
import 'dart:math' show Random;
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

const int credentialsCryptoVersion = 1;
const String _credentialInfoLabel = 'vaultai.inh-cred.v1';

const int _nonceBytes = 12;
const int _cekBytes = 32;
const int _x25519PubBytes = 32;

final Hkdf _hkdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);
final AesGcm _aesGcm = AesGcm.with256bits();

/// Bag of bytes ready to be POSTed to the backend. Every field is
/// base64url-encoded (no padding).
class InheritanceCredentialPackage {
  final int cryptoVersion;
  final String encryptedPayloadB64Url;
  final String payloadNonceB64Url;
  final String wrappedKeyB64Url;
  final String wrappingEphemeralPkB64Url;
  final String wrappingNonceB64Url;

  const InheritanceCredentialPackage({
    required this.cryptoVersion,
    required this.encryptedPayloadB64Url,
    required this.payloadNonceB64Url,
    required this.wrappedKeyB64Url,
    required this.wrappingEphemeralPkB64Url,
    required this.wrappingNonceB64Url,
  });

  Map<String, dynamic> toRequestBody({required int beneficiaryLinkId}) => {
        'beneficiary_link_id': beneficiaryLinkId,
        'crypto_version': cryptoVersion,
        'encrypted_payload': encryptedPayloadB64Url,
        'payload_nonce': payloadNonceB64Url,
        'wrapped_key': wrappedKeyB64Url,
        'wrapping_ephemeral_pk': wrappingEphemeralPkB64Url,
        'wrapping_nonce': wrappingNonceB64Url,
      };
}

/// Owner-side encryption entry point.
///
/// Inputs are the plaintext to escrow (username + pin) and the
/// beneficiary's stored X25519 public key (fetched from
/// `/inheritance/beneficiary/{link_id}/pubkey`).
///
/// The plaintext arguments are held on the local stack only for
/// the duration of this call; the returned package contains no
/// recoverable form of them without the beneficiary's private key.
Future<InheritanceCredentialPackage> encryptInheritanceCredentials({
  required String username,
  required String pin,
  required Uint8List beneficiaryPkVaultPublic,
  DateTime? nowUtc,
  Random? randomForTest,
}) async {
  if (beneficiaryPkVaultPublic.length != _x25519PubBytes) {
    throw ArgumentError(
      'beneficiaryPkVaultPublic must be 32 bytes (X25519 public key)',
    );
  }
  final rng = randomForTest ?? Random.secure();

  final payloadJson = jsonEncode({
    'version': credentialsCryptoVersion,
    'username': username,
    'pin': pin,
    'created_at': (nowUtc ?? DateTime.now().toUtc()).toIso8601String(),
  });
  final payloadBytes = utf8.encode(payloadJson);

  // 1. CEK + AES-GCM(payload)
  final cek = _randomBytes(rng, _cekBytes);
  final payloadNonce = _randomBytes(rng, _nonceBytes);
  final cekKey = SecretKey(cek);
  final payloadBox = await _aesGcm.encrypt(
    payloadBytes,
    secretKey: cekKey,
    nonce: payloadNonce,
  );
  final encryptedPayload = Uint8List.fromList(
    <int>[...payloadBox.cipherText, ...payloadBox.mac.bytes],
  );

  // 2. X25519 ephemeral keypair + ECDH
  final algo = X25519();
  final eph = await algo.newKeyPair();
  final ephPub = await eph.extractPublicKey();
  final ephPubBytes = Uint8List.fromList(ephPub.bytes);
  final shared = await algo.sharedSecretKey(
    keyPair: eph,
    remotePublicKey: SimplePublicKey(
      beneficiaryPkVaultPublic,
      type: KeyPairType.x25519,
    ),
  );

  // 3. HKDF-SHA256 → K_wrap
  final kWrap = await _hkdf.deriveKey(
    secretKey: shared,
    nonce: ephPubBytes,
    info: utf8.encode(_credentialInfoLabel),
  );

  // 4. AES-GCM(K_wrap, wrapping_nonce, CEK)
  final wrapNonce = _randomBytes(rng, _nonceBytes);
  final wrapBox = await _aesGcm.encrypt(
    cek,
    secretKey: kWrap,
    nonce: wrapNonce,
  );
  final wrappedKey = Uint8List.fromList(
    <int>[...wrapBox.cipherText, ...wrapBox.mac.bytes],
  );

  return InheritanceCredentialPackage(
    cryptoVersion: credentialsCryptoVersion,
    encryptedPayloadB64Url: _b64UrlNoPad(encryptedPayload),
    payloadNonceB64Url: _b64UrlNoPad(payloadNonce),
    wrappedKeyB64Url: _b64UrlNoPad(wrappedKey),
    wrappingEphemeralPkB64Url: _b64UrlNoPad(ephPubBytes),
    wrappingNonceB64Url: _b64UrlNoPad(wrapNonce),
  );
}

/// Beneficiary-side decryption. Kept in this file (not in
/// `services/inheritance_rewrap.dart`) so the owner and beneficiary
/// paths use the exact same info-label + envelope layout.
///
/// This is exposed for round-trip testing today. Phase 2 will call
/// it from the beneficiary reveal path once the release endpoints
/// exist.
class DecryptedInheritanceCredentials {
  final int version;
  final String username;
  final String pin;
  final String createdAtIso;

  const DecryptedInheritanceCredentials({
    required this.version,
    required this.username,
    required this.pin,
    required this.createdAtIso,
  });
}

// ---------------------------------------------------------------------
// Beneficiary reveal — stage-complete decrypt pipeline
// ---------------------------------------------------------------------
//
// Stage naming (2026-07-22 revision): ONE stable convention —
// UPPER_SNAKE. The prior lowercase constants ("eph_pub_decode",
// "cek_unwrap", …) are removed; the backend allowlist accepts only
// the tags below. Fire-and-forget diagnostics from browsers still
// running the previous bundle will be rejected server-side (400
// INH-CRED-004) but this has no user-visible impact — the failure
// classification / snack reference tag on the beneficiary device
// is unchanged, only the diagnostic ingest is stricter.
//
// The nine stages match the user-spec exactly. ``UNSTAGED_UNKNOWN``
// is a defensive fallback that should never fire in production — its
// presence in the ``[INH-CLIENT-DIAG]`` log is itself an operator
// signal that the wrapper has a hole.
const String kRevealStageLoadSecretKey            = 'LOAD_SECRET_KEY';
const String kRevealStageParseEphemeralPublicKey  = 'PARSE_EPHEMERAL_PUBLIC_KEY';
const String kRevealStageDeriveSharedSecret       = 'DERIVE_SHARED_SECRET';
const String kRevealStageDeriveWrapKey            = 'DERIVE_WRAP_KEY';
const String kRevealStageUnwrapDataKey            = 'UNWRAP_DATA_KEY';
const String kRevealStageDecryptPayload           = 'DECRYPT_PAYLOAD';
const String kRevealStageUtf8Decode               = 'UTF8_DECODE';
const String kRevealStageJsonParse                = 'JSON_PARSE';
const String kRevealStageMapCredential            = 'MAP_CREDENTIAL';
const String kRevealStageUnstagedUnknown          = 'UNSTAGED_UNKNOWN';

/// Every reveal stage as an unordered set — used by the frontend
/// diagnostic and by the backend allowlist regression test to keep
/// the two sides in lockstep.
const Set<String> kRevealStagesAll = <String>{
  kRevealStageLoadSecretKey,
  kRevealStageParseEphemeralPublicKey,
  kRevealStageDeriveSharedSecret,
  kRevealStageDeriveWrapKey,
  kRevealStageUnwrapDataKey,
  kRevealStageDecryptPayload,
  kRevealStageUtf8Decode,
  kRevealStageJsonParse,
  kRevealStageMapCredential,
  kRevealStageUnstagedUnknown,
};

/// Fixed on-wire byte lengths per crypto_version 1. Sent alongside
/// the actual measured length in the diagnostic body so an operator
/// can see the mismatch at a glance without having to look up the
/// spec.
const int kExpectedPayloadNonceLen         = 12;
const int kExpectedWrappingEphemeralPkLen  = 32;
const int kExpectedWrappingNonceLen        = 12;
const int kExpectedWrappedKeyLen           = 48;  // 32B CEK + 16B GCM tag
const int kExpectedSkVaultLen              = 32;  // X25519 seed

/// Wraps any exception thrown inside the reveal pipeline with the
/// STAGE at which it occurred. The classifier
/// (``inheritance_reveal_classify.dart``) unwraps this and reports
/// the stage in the client-diagnostic payload, so an operator can
/// tell "AES-GCM tag mismatch on the CEK unwrap" apart from
/// "AES-GCM tag mismatch on the payload decrypt" — both would
/// otherwise surface as an identical ``SecretBoxAuthenticationError``.
///
/// ``cause`` is the original exception; ``causeStackTrace`` is the
/// stack captured at the failing await. Neither is placed on the
/// wire — they exist only for local vlog / diagnostic emission.
class InheritanceRevealStageException implements Exception {
  final String stage;
  final Object cause;
  final StackTrace causeStackTrace;

  const InheritanceRevealStageException({
    required this.stage,
    required this.cause,
    required this.causeStackTrace,
  });

  @override
  String toString() =>
      'InheritanceRevealStageException(stage: $stage, '
      'cause: ${cause.runtimeType})';
}

Future<T> _stage<T>(String stage, Future<T> Function() body) async {
  try {
    return await body();
  } catch (e, st) {
    if (e is InheritanceRevealStageException) rethrow;
    throw InheritanceRevealStageException(
      stage: stage, cause: e, causeStackTrace: st,
    );
  }
}

T _stageSync<T>(String stage, T Function() body) {
  try {
    return body();
  } catch (e, st) {
    if (e is InheritanceRevealStageException) rethrow;
    throw InheritanceRevealStageException(
      stage: stage, cause: e, causeStackTrace: st,
    );
  }
}

/// Stage-complete beneficiary reveal.
///
/// This is the ONLY correct entry point for the reveal button on
/// the beneficiary side. Contract: **any exception this function
/// throws is an ``InheritanceRevealStageException``** — the caller's
/// diagnostic will therefore never see ``stage=None``. If a caller
/// wraps this in a further try/catch, it MUST re-throw a wrapped
/// ``InheritanceRevealStageException(stage: UNSTAGED_UNKNOWN, ...)``
/// for anything that escapes.
///
/// Every one of the nine stages is separately wrapped so a byte-
/// shape failure at UNWRAP_DATA_KEY is distinguishable from a tag-
/// authentication failure at DECRYPT_PAYLOAD.
///
/// ``rawPackage`` is the wire response from
/// ``GET /inheritance/credentials/retrieve``. All fields are
/// base64url. No decryption happens on the server; the pipeline
/// verifies every field length against the crypto_version 1 spec
/// before touching any key material.
Future<DecryptedInheritanceCredentials> revealInheritanceCredentialsStaged({
  required SecretKey beneficiarySkVault,
  required Map<String, dynamic> rawPackage,
}) async {
  // ---- Stage 1 · LOAD_SECRET_KEY ------------------------------
  // sk.extractBytes() -> Uint8List. Also length-check the 32-byte
  // X25519 seed invariant before feeding it to newKeyPairFromSeed
  // (which would otherwise throw an unstaged ArgumentError from
  // BEFORE the first stage wrapper covers it).
  final Uint8List skBytes = await _stage(kRevealStageLoadSecretKey, () async {
    final raw = await beneficiarySkVault.extractBytes();
    final bytes = raw is Uint8List ? raw : Uint8List.fromList(raw);
    if (bytes.length != kExpectedSkVaultLen) {
      throw StateError(
        'beneficiary sk_vault seed has wrong length '
        '(got ${bytes.length}, expected $kExpectedSkVaultLen)',
      );
    }
    return bytes;
  });

  // ---- Stage 2 · PARSE_EPHEMERAL_PUBLIC_KEY --------------------
  // Base64url-decode the ephemeral public key AND construct the
  // SimplePublicKey object. cryptography 2.9.0's SimplePublicKey
  // constructor length-checks the bytes so a wrong-length input
  // throws here rather than at DERIVE_SHARED_SECRET.
  final SimplePublicKey ephPub =
      await _stage(kRevealStageParseEphemeralPublicKey, () async {
    final ephPubB64 = (rawPackage['wrapping_ephemeral_pk'] ?? '').toString();
    final bytes = _b64UrlDecode(ephPubB64);
    if (bytes.length != kExpectedWrappingEphemeralPkLen) {
      throw StateError(
        'ephemeral pk has wrong length '
        '(got ${bytes.length}, expected $kExpectedWrappingEphemeralPkLen)',
      );
    }
    return SimplePublicKey(bytes, type: KeyPairType.x25519);
  });

  // ---- Stage 3 · DERIVE_SHARED_SECRET --------------------------
  // Import seed as X25519 keypair, then ECDH with the ephemeral pk.
  // Both operations live in the same stage — they represent one
  // conceptual failure mode (agreement between our sk and the
  // owner's ephemeral pk) and neither returns a useful intermediate
  // value the operator would want to distinguish.
  final SecretKey shared =
      await _stage(kRevealStageDeriveSharedSecret, () async {
    final algo = X25519();
    final skKeyPair = await algo.newKeyPairFromSeed(skBytes);
    return algo.sharedSecretKey(
      keyPair: skKeyPair, remotePublicKey: ephPub,
    );
  });

  // ---- Stage 4 · DERIVE_WRAP_KEY -------------------------------
  // HKDF-SHA256 with the ephemeral pk as salt and the fixed
  // ``vaultai.inh-cred.v1`` info label. Output is the 32-byte AES
  // key that unwraps the CEK.
  final SecretKey kWrap = await _stage(kRevealStageDeriveWrapKey, () async {
    return _hkdf.deriveKey(
      secretKey: shared,
      nonce: Uint8List.fromList(ephPub.bytes),
      info: utf8.encode(_credentialInfoLabel),
    );
  });

  // ---- Stage 5 · UNWRAP_DATA_KEY -------------------------------
  // AES-GCM decrypt the wrapped CEK. Combines the wrapped-key
  // + wrapping-nonce decode, ct/tag split, decrypt, and 32-byte
  // CEK length assertion — they collectively represent "recover
  // the credential encryption key". A tag mismatch here means
  // ``kWrap`` doesn't match what the owner used to wrap (typically
  // the wrong beneficiary sk).
  final List<int> cek = await _stage(kRevealStageUnwrapDataKey, () async {
    final wrappedKeyB64 = (rawPackage['wrapped_key'] ?? '').toString();
    final wrapNonceB64  = (rawPackage['wrapping_nonce'] ?? '').toString();
    final wrappedKey = _b64UrlDecode(wrappedKeyB64);
    final wrapNonce  = _b64UrlDecode(wrapNonceB64);
    if (wrappedKey.length != kExpectedWrappedKeyLen) {
      throw StateError(
        'wrapped_key has wrong length '
        '(got ${wrappedKey.length}, expected $kExpectedWrappedKeyLen)',
      );
    }
    if (wrapNonce.length != kExpectedWrappingNonceLen) {
      throw StateError(
        'wrapping_nonce has wrong length '
        '(got ${wrapNonce.length}, expected $kExpectedWrappingNonceLen)',
      );
    }
    final unwrapped = await _aesGcm.decrypt(
      _splitCiphertextAndMac(wrappedKey, wrapNonce),
      secretKey: kWrap,
    );
    if (unwrapped.length != _cekBytes) {
      throw StateError(
        'unwrapped CEK has wrong length '
        '(got ${unwrapped.length}, expected $_cekBytes)',
      );
    }
    return unwrapped;
  });

  // ---- Stage 6 · DECRYPT_PAYLOAD -------------------------------
  // AES-GCM decrypt the credential payload using the CEK. A tag
  // mismatch here means the credential ciphertext was tampered
  // with — or (much more likely) that a subtle envelope format
  // change happened between owner-encrypt and beneficiary-decrypt.
  final List<int> plainBytes =
      await _stage(kRevealStageDecryptPayload, () async {
    final encPayloadB64 = (rawPackage['encrypted_payload'] ?? '').toString();
    final payloadNonceB64 = (rawPackage['payload_nonce'] ?? '').toString();
    final encryptedPayload = _b64UrlDecode(encPayloadB64);
    final payloadNonce     = _b64UrlDecode(payloadNonceB64);
    if (payloadNonce.length != kExpectedPayloadNonceLen) {
      throw StateError(
        'payload_nonce has wrong length '
        '(got ${payloadNonce.length}, expected $kExpectedPayloadNonceLen)',
      );
    }
    return _aesGcm.decrypt(
      _splitCiphertextAndMac(encryptedPayload, payloadNonce),
      // Wrap the CEK in a FRESH SecretKey object — do not reuse a
      // reference from another zone. cryptography 2.9.0 accepts
      // both SecretKey and SecretKeyData; SecretKey(cek) is the
      // documented owner-encrypt shape.
      secretKey: SecretKey(cek),
    );
  });

  // ---- Stage 7 · UTF8_DECODE -----------------------------------
  // Convert plaintext bytes to a Dart string. Any malformed UTF-8
  // surface as a FormatException with 'utf' in the message; the
  // classifier maps this to PAYLOAD.
  final String plainText = await _stage(kRevealStageUtf8Decode, () async {
    return utf8.decode(plainBytes);
  });

  // ---- Stage 8 · JSON_PARSE ------------------------------------
  // Parse the plaintext string as a JSON object. If it isn't a
  // Map (e.g. an array or a scalar sneaked through), we throw
  // StateError with 'not a JSON object' — the classifier maps
  // this to PAYLOAD.
  final Map decoded = await _stage(kRevealStageJsonParse, () async {
    final j = jsonDecode(plainText);
    if (j is! Map) {
      throw StateError('credential payload is not a JSON object');
    }
    return j;
  });

  // ---- Stage 9 · MAP_CREDENTIAL --------------------------------
  // Extract the four fields into a strongly-typed record. Missing
  // ``version`` throws a TypeError → classified as SHAPE.
  return _stage(kRevealStageMapCredential, () async {
    return DecryptedInheritanceCredentials(
      version:      (decoded['version'] as num).toInt(),
      username:     (decoded['username'] ?? '').toString(),
      pin:          (decoded['pin'] ?? '').toString(),
      createdAtIso: (decoded['created_at'] ?? '').toString(),
    );
  });
}

/// Legacy round-trip entry point retained for the existing
/// ``inheritance_credentials_test.dart`` round-trip test that
/// operates on a raw seed instead of a SecretKey. Delegates to the
/// stage-complete pipeline so BOTH paths get the same coverage.
///
/// New callers should prefer ``revealInheritanceCredentialsStaged``.
Future<DecryptedInheritanceCredentials> decryptInheritanceCredentials({
  required Uint8List beneficiarySkVaultPrivate,
  required InheritanceCredentialPackage package,
}) async {
  final rawPackage = <String, dynamic>{
    'crypto_version':          package.cryptoVersion,
    'encrypted_payload':       package.encryptedPayloadB64Url,
    'payload_nonce':           package.payloadNonceB64Url,
    'wrapped_key':             package.wrappedKeyB64Url,
    'wrapping_ephemeral_pk':   package.wrappingEphemeralPkB64Url,
    'wrapping_nonce':          package.wrappingNonceB64Url,
  };
  return revealInheritanceCredentialsStaged(
    beneficiarySkVault: SecretKey(beneficiarySkVaultPrivate),
    rawPackage: rawPackage,
  );
}

// ---------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------

Uint8List _randomBytes(Random rng, int n) {
  final out = Uint8List(n);
  for (int i = 0; i < n; i++) {
    out[i] = rng.nextInt(256);
  }
  return out;
}

String _b64UrlNoPad(List<int> raw) =>
    base64Url.encode(raw).replaceAll('=', '');

Uint8List _b64UrlDecode(String s) {
  final padded = s + '=' * ((4 - s.length % 4) % 4);
  return base64Url.decode(padded);
}

/// The `cryptography` package's AES-GCM decrypt takes a `SecretBox`
/// containing ciphertext + mac + nonce. Our on-wire representation
/// keeps ciphertext‖mac contiguous and stores the nonce separately.
/// Recombine here.
SecretBox _splitCiphertextAndMac(Uint8List body, Uint8List nonce) {
  const int macLen = 16;
  if (body.length < macLen) {
    throw StateError('ciphertext is shorter than the AES-GCM tag');
  }
  final ct = body.sublist(0, body.length - macLen);
  final mac = body.sublist(body.length - macLen);
  return SecretBox(ct, nonce: nonce, mac: Mac(mac));
}
