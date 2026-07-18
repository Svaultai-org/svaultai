// Inheritance MVK rewrap.
//
// At pairing time, the passer's client wraps a copy of its MVK
// using an X25519 ECDH shared secret with the beneficiary's
// pk_vault_public. The wrapped payload plus the passer's ephemeral
// X25519 public key are uploaded to the beneficiary_links row so the
// beneficiary (on claim) can perform the reverse ECDH with its
// sk_vault_private and unwrap the MVK.
//
// Envelope format: eph_pub(32) || nonce(12) || ct || tag(16)
// (Wire is a single BYTEA blob emitted by wrapMvkForBeneficiary.)
//
// No custom cryptography — this file composes X25519, HKDF, and
// AES-GCM from the audited `cryptography` package.

import 'dart:convert';
import 'dart:math' show Random;
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

const int _nonceBytes = 12;

final AesGcm _aesGcm = AesGcm.with256bits();
final Hkdf _hkdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);

/// Wrap MVK for a beneficiary given only their public X25519 point.
Future<Uint8List> wrapMvkForBeneficiary({
  required SecretKey mvk,
  required Uint8List beneficiaryPkVaultPublic,
}) async {
  if (beneficiaryPkVaultPublic.length != 32) {
    throw ArgumentError('beneficiaryPkVaultPublic must be 32 bytes');
  }
  final algo = X25519();
  final ephSeed = _randomBytes(32);
  final ephPair = await algo.newKeyPairFromSeed(ephSeed);
  final ephPub = await ephPair.extractPublicKey();

  final shared = await algo.sharedSecretKey(
    keyPair: ephPair,
    remotePublicKey: SimplePublicKey(
      beneficiaryPkVaultPublic, type: KeyPairType.x25519,
    ),
  );
  final sharedBytes = await shared.extractBytes();
  final wrapKey = await _hkdf.deriveKey(
    secretKey: SecretKey(sharedBytes),
    nonce: const [],
    info: utf8.encode('vaultai.inherit.rewrap.v1'),
  );

  final mvkBytes = await mvk.extractBytes();
  final nonce = _randomBytes(_nonceBytes);
  final box = await _aesGcm.encrypt(
    mvkBytes, secretKey: wrapKey, nonce: nonce,
  );

  final ephPubBytes = Uint8List.fromList(ephPub.bytes);
  final builder = BytesBuilder();
  builder.add(ephPubBytes);
  builder.add(nonce);
  builder.add(box.cipherText);
  builder.add(box.mac.bytes);
  return builder.toBytes();
}

/// Beneficiary's client, at claim time, unwraps MVK using their own
/// sk_vault_private and the payload's embedded eph_pub.
Future<SecretKey> unwrapMvkAsBeneficiary({
  required SecretKey beneficiarySkVaultPrivate,
  required Uint8List envelope,
}) async {
  if (envelope.length < 32 + _nonceBytes + 16) {
    throw ArgumentError('inheritance envelope too short');
  }
  final ephPub = envelope.sublist(0, 32);
  final nonce = envelope.sublist(32, 32 + _nonceBytes);
  final tagStart = envelope.length - 16;
  final ct = envelope.sublist(32 + _nonceBytes, tagStart);
  final tag = envelope.sublist(tagStart);

  final algo = X25519();
  final sk = await beneficiarySkVaultPrivate.extractBytes();
  final beneficiaryPair = await algo.newKeyPairFromSeed(sk);

  final shared = await algo.sharedSecretKey(
    keyPair: beneficiaryPair,
    remotePublicKey: SimplePublicKey(ephPub, type: KeyPairType.x25519),
  );
  final sharedBytes = await shared.extractBytes();
  final wrapKey = await _hkdf.deriveKey(
    secretKey: SecretKey(sharedBytes),
    nonce: const [],
    info: utf8.encode('vaultai.inherit.rewrap.v1'),
  );

  final box = SecretBox(ct, nonce: nonce, mac: Mac(tag));
  final mvkBytes = await _aesGcm.decrypt(box, secretKey: wrapKey);
  return SecretKey(mvkBytes);
}

Uint8List _randomBytes(int len) {
  final rng = Random.secure();
  final out = Uint8List(len);
  for (var i = 0; i < len; i++) {
    out[i] = rng.nextInt(256);
  }
  return out;
}
