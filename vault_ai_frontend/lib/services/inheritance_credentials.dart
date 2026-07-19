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

Future<DecryptedInheritanceCredentials> decryptInheritanceCredentials({
  required Uint8List beneficiarySkVaultPrivate,
  required InheritanceCredentialPackage package,
}) async {
  final algo = X25519();
  final ephPub = SimplePublicKey(
    _b64UrlDecode(package.wrappingEphemeralPkB64Url),
    type: KeyPairType.x25519,
  );

  final skKeyPair = await algo.newKeyPairFromSeed(beneficiarySkVaultPrivate);
  final shared = await algo.sharedSecretKey(
    keyPair: skKeyPair,
    remotePublicKey: ephPub,
  );
  final kWrap = await _hkdf.deriveKey(
    secretKey: shared,
    nonce: Uint8List.fromList(ephPub.bytes),
    info: utf8.encode(_credentialInfoLabel),
  );

  final wrappedKey = _b64UrlDecode(package.wrappedKeyB64Url);
  final wrapNonce = _b64UrlDecode(package.wrappingNonceB64Url);
  final cek = await _aesGcm.decrypt(
    _splitCiphertextAndMac(wrappedKey, wrapNonce),
    secretKey: kWrap,
  );
  if (cek.length != _cekBytes) {
    throw StateError('unwrapped CEK has wrong length');
  }

  final encryptedPayload = _b64UrlDecode(package.encryptedPayloadB64Url);
  final payloadNonce = _b64UrlDecode(package.payloadNonceB64Url);
  final plainBytes = await _aesGcm.decrypt(
    _splitCiphertextAndMac(encryptedPayload, payloadNonce),
    secretKey: SecretKey(cek),
  );
  final decoded = jsonDecode(utf8.decode(plainBytes));
  if (decoded is! Map) {
    throw StateError('credential payload is not a JSON object');
  }
  return DecryptedInheritanceCredentials(
    version: (decoded['version'] as num).toInt(),
    username: (decoded['username'] ?? '').toString(),
    pin: (decoded['pin'] ?? '').toString(),
    createdAtIso: (decoded['created_at'] ?? '').toString(),
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
