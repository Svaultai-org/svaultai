/// Beneficiary possession check for a staged old-link inheritance upgrade.
///
/// The server encrypts only random bytes to this vault's X25519 key. This
/// checks use of the registered private key without fetching the owner's MVK.
/// A later release ceremony still needs its own safety review.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'inheritance_mvk_v2.dart';

typedef FetchBeneficiaryChallenge = Future<Map<String, dynamic>> Function(
  int linkId,
);
typedef SubmitBeneficiaryKeyCheck = Future<Map<String, dynamic>> Function(
  Map<String, dynamic> body,
);

const _info = 'vaultai.inh-v2-beneficiary-keycheck.v1';
final _aes = AesGcm.with256bits();
final _hkdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);

class LinkedBeneficiaryKeyCheck {
  final int linkId;
  final int stageRevision;
  final String offerCommitment;

  const LinkedBeneficiaryKeyCheck({
    required this.linkId,
    required this.stageRevision,
    required this.offerCommitment,
  });
}

Uint8List _field(Map<String, dynamic> data, String name, int exact) {
  final value = data[name];
  if (value is! String ||
      !RegExp(r'^[A-Za-z0-9_-]+$').hasMatch(value)) {
    throw const FormatException('Invalid beneficiary key challenge');
  }
  final raw = base64Url.decode(base64Url.normalize(value));
  if (raw.length != exact ||
      base64Url.encode(raw).replaceAll('=', '') != value) {
    throw const FormatException('Invalid beneficiary key challenge');
  }
  return Uint8List.fromList(raw);
}

Future<LinkedBeneficiaryKeyCheck> verifyLinkedBeneficiaryKey({
  required int linkId,
  required SecretKey beneficiaryPrivateKey,
  required String zkProofToken,
  required FetchBeneficiaryChallenge fetchChallenge,
  required SubmitBeneficiaryKeyCheck submitResponse,
  required bool Function() accessIsCurrent,
}) async {
  void checkAccess() {
    if (!accessIsCurrent()) throw StateError('Beneficiary vault access changed');
  }

  if (linkId <= 0 || zkProofToken.isEmpty) {
    throw const FormatException('Invalid beneficiary key check');
  }
  checkAccess();
  final challenge = await fetchChallenge(linkId);
  checkAccess();
  final revision = challenge['stage_revision'];
  final commitment = challenge['offer_commitment'];
  final expectedPkHash = challenge['beneficiary_pk_sha256'];
  if (challenge['beneficiary_link_id'] != linkId ||
      revision is! int ||
      revision <= 0 ||
      commitment is! String ||
      !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(commitment) ||
      expectedPkHash is! String ||
      !RegExp(r'^[0-9a-f]{64}$').hasMatch(expectedPkHash)) {
    throw const FormatException('Invalid beneficiary key challenge');
  }
  final expiry = DateTime.tryParse(challenge['expires_at']?.toString() ?? '');
  if (expiry == null || !DateTime.now().toUtc().isBefore(expiry.toUtc())) {
    throw StateError('Beneficiary key challenge expired');
  }
  final localPkHash = await beneficiaryPrivateKeyFingerprint(
    beneficiaryPrivateKey,
  );
  if (!beneficiaryFingerprintMatches(localPkHash, expectedPkHash)) {
    throw StateError('The registered beneficiary key changed');
  }

  final ephemeralPk = _field(challenge, 'challenge_ephemeral_pk', 32);
  final nonce = _field(challenge, 'challenge_nonce', 12);
  final encrypted = _field(challenge, 'challenge_ciphertext', 48);
  final keySeed = await beneficiaryPrivateKey.extractBytes();
  if (keySeed.length != 32) {
    throw const FormatException('Invalid beneficiary private key');
  }
  checkAccess();
  final keyPair = await X25519().newKeyPairFromSeed(keySeed);
  final shared = await X25519().sharedSecretKey(
    keyPair: keyPair,
    remotePublicKey: SimplePublicKey(
      ephemeralPk, type: KeyPairType.x25519,
    ),
  );
  final aesKey = await _hkdf.deriveKey(
    secretKey: shared,
    nonce: ephemeralPk,
    info: utf8.encode(_info),
  );
  final aad = utf8.encode(
    'svaultai:old-link-v2-beneficiary-keycheck:v1:'
    '$linkId:$revision:$commitment',
  );
  final secret = await _aes.decrypt(
    SecretBox(
      encrypted.sublist(0, 32),
      nonce: nonce,
      mac: Mac(encrypted.sublist(32)),
    ),
    secretKey: aesKey,
    aad: aad,
  );
  if (secret.length != 32) {
    throw const FormatException('Invalid beneficiary key challenge');
  }
  checkAccess();
  final response = await submitResponse({
    'beneficiary_link_id': linkId,
    'stage_revision': revision,
    'offer_commitment': commitment,
    'challenge_secret': base64Url.encode(secret).replaceAll('=', ''),
    'expected_beneficiary_pk_sha256': expectedPkHash,
    'zk_proof_token': zkProofToken,
  });
  checkAccess();
  if (response['beneficiary_link_id'] != linkId ||
      response['stage_revision'] != revision ||
      response['offer_commitment'] != commitment ||
      response['beneficiary_key_possession_confirmed'] != true ||
      response['package_decryption_verified'] != false ||
      response['legacy_link_unchanged'] != true) {
    throw StateError('Beneficiary key check response differs');
  }
  return LinkedBeneficiaryKeyCheck(
    linkId: linkId,
    stageRevision: revision,
    offerCommitment: commitment,
  );
}
