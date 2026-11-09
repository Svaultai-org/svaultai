/// Stage-bound, private owner-MVK readback proof for an old linked inheritance.
///
/// The owner registers only a public Ed25519 verifier. After release, the
/// beneficiary derives the matching signing key from the locally decrypted
/// owner MVK and signs a fresh server challenge. No MVK or seed is uploaded.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'linked_inheritance_v2_release_readback.dart';
import 'linked_inheritance_v2_stage.dart';

typedef FetchOwnerStageReadback = Future<Map<String, dynamic>> Function(
  int linkId,
);
typedef SubmitOwnerReadbackVerifier = Future<Map<String, dynamic>> Function(
  Map<String, dynamic> body,
);
typedef FetchReadbackChallenge = Future<Map<String, dynamic>> Function(
  int linkId,
);
typedef SubmitReadbackProof = Future<Map<String, dynamic>> Function(
  Map<String, dynamic> body,
);

const _salt = 'svaultai:linked-old-v2-readback-salt:v1';
final _hkdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);
final _ed25519 = Ed25519();
final _b64Pattern = RegExp(r'^[A-Za-z0-9_-]+$');

String _b64(List<int> bytes) => base64Url.encode(bytes).replaceAll('=', '');

Uint8List _field(Object? raw, int length) {
  if (raw is! String || !_b64Pattern.hasMatch(raw)) {
    throw const FormatException('Invalid readback proof field');
  }
  final bytes = base64Url.decode(base64Url.normalize(raw));
  if (bytes.length != length || _b64(bytes) != raw) {
    throw const FormatException('Invalid readback proof field');
  }
  return Uint8List.fromList(bytes);
}

void _validateContext({
  required int linkId,
  required int stageRevision,
  required String offerCommitment,
  required String ownerVaultId,
  required String beneficiaryVaultId,
}) {
  if (linkId <= 0 ||
      stageRevision <= 0 ||
      !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(offerCommitment) ||
      ownerVaultId.isEmpty ||
      beneficiaryVaultId.isEmpty ||
      ownerVaultId.contains(':') ||
      beneficiaryVaultId.contains(':') ||
      ownerVaultId == beneficiaryVaultId) {
    throw const FormatException('Invalid readback proof context');
  }
}

String _context({
  required int linkId,
  required int stageRevision,
  required String offerCommitment,
  required String ownerVaultId,
  required String beneficiaryVaultId,
}) =>
    '$linkId:$stageRevision:$offerCommitment:$ownerVaultId:$beneficiaryVaultId';

Future<SimpleKeyPair> _readbackKeyPair({
  required SecretKey ownerMvk,
  required int linkId,
  required int stageRevision,
  required String offerCommitment,
  required String ownerVaultId,
  required String beneficiaryVaultId,
}) async {
  _validateContext(
    linkId: linkId,
    stageRevision: stageRevision,
    offerCommitment: offerCommitment,
    ownerVaultId: ownerVaultId,
    beneficiaryVaultId: beneficiaryVaultId,
  );
  if ((await ownerMvk.extractBytes()).length != 32) {
    throw const FormatException('Invalid owner private vault key');
  }
  final seed = await _hkdf.deriveKey(
    secretKey: ownerMvk,
    nonce: utf8.encode(_salt),
    info: utf8.encode(
      'svaultai:linked-old-v2-readback-seed:v1:'
      '${_context(linkId: linkId, stageRevision: stageRevision, offerCommitment: offerCommitment, ownerVaultId: ownerVaultId, beneficiaryVaultId: beneficiaryVaultId)}',
    ),
  );
  return _ed25519.newKeyPairFromSeed(await seed.extractBytes());
}

String _challengeMessage({
  required int linkId,
  required int stageRevision,
  required String offerCommitment,
  required String ownerVaultId,
  required String beneficiaryVaultId,
  required String challengeNonce,
}) =>
    'svaultai:linked-old-v2-readback:v1:'
    '${_context(linkId: linkId, stageRevision: stageRevision, offerCommitment: offerCommitment, ownerVaultId: ownerVaultId, beneficiaryVaultId: beneficiaryVaultId)}:'
    '$challengeNonce';

class LinkedReadbackVerifier {
  final int linkId;
  final int stageRevision;
  final String offerCommitment;

  const LinkedReadbackVerifier({
    required this.linkId,
    required this.stageRevision,
    required this.offerCommitment,
  });
}

class LinkedReadbackReceipt {
  final int linkId;
  final int stageRevision;
  final String offerCommitment;
  final DateTime readbackAt;

  const LinkedReadbackReceipt({
    required this.linkId,
    required this.stageRevision,
    required this.offerCommitment,
    required this.readbackAt,
  });
}

Future<LinkedReadbackVerifier> registerLinkedReadbackVerifier({
  required StagedLinkedInheritanceV2 staged,
  required String ownerVaultId,
  required SecretKey ownerMvk,
  required String zkProofToken,
  required FetchOwnerStageReadback fetchReadback,
  required SubmitOwnerReadbackVerifier submitVerifier,
  required bool Function() accessIsCurrent,
}) async {
  void checkAccess() {
    if (!accessIsCurrent()) throw StateError('Owner vault access changed');
  }

  if (zkProofToken.isEmpty) {
    throw const FormatException('Missing owner proof token');
  }
  checkAccess();
  final stored = await fetchReadback(staged.linkId);
  checkAccess();
  final beneficiaryId = stored['beneficiary_vault_id'];
  final commitment = stored['offer_commitment'];
  if (stored['beneficiary_link_id'] != staged.linkId ||
      stored['stage_revision'] != staged.stageRevision ||
      stored['old_source_snapshot'] != staged.oldSourceSnapshot ||
      stored['owner_vault_id'] != ownerVaultId ||
      beneficiaryId is! String ||
      commitment is! String ||
      stored['state'] != 'staged' ||
      stored['beneficiary_pk_sha256'] !=
          staged.beneficiaryFingerprint.replaceAll('-', '').toLowerCase()) {
    throw StateError('Linked inheritance stage changed');
  }
  final keyPair = await _readbackKeyPair(
    ownerMvk: ownerMvk,
    linkId: staged.linkId,
    stageRevision: staged.stageRevision,
    offerCommitment: commitment,
    ownerVaultId: ownerVaultId,
    beneficiaryVaultId: beneficiaryId,
  );
  checkAccess();
  final publicKey = await keyPair.extractPublicKey();
  final result = await submitVerifier({
    'beneficiary_link_id': staged.linkId,
    'stage_revision': staged.stageRevision,
    'offer_commitment': commitment,
    'expected_beneficiary_pk_sha256':
        staged.beneficiaryFingerprint.replaceAll('-', '').toLowerCase(),
    'readback_public_key': _b64(publicKey.bytes),
    'zk_proof_token': zkProofToken,
  });
  checkAccess();
  if (result['beneficiary_link_id'] != staged.linkId ||
      result['stage_revision'] != staged.stageRevision ||
      result['offer_commitment'] != commitment ||
      result['owner_readback_verifier_registered'] != true ||
      result['package_decryption_verified'] != false ||
      result['legacy_link_unchanged'] != true) {
    throw StateError('Linked readback verifier response differs');
  }
  return LinkedReadbackVerifier(
    linkId: staged.linkId,
    stageRevision: staged.stageRevision,
    offerCommitment: commitment,
  );
}

Future<LinkedReadbackReceipt> proveLinkedReadback({
  required ReleasedLinkedInheritanceV2 released,
  required String beneficiaryVaultId,
  required String zkProofToken,
  required FetchReadbackChallenge fetchChallenge,
  required SubmitReadbackProof submitProof,
  required bool Function() accessIsCurrent,
}) async {
  void checkAccess() {
    if (!accessIsCurrent()) {
      throw StateError('Beneficiary vault access changed');
    }
  }

  if (zkProofToken.isEmpty) {
    throw const FormatException('Missing beneficiary proof token');
  }
  checkAccess();
  final challenge = await fetchChallenge(released.linkId);
  checkAccess();
  final nonceRaw = challenge['challenge_nonce'];
  final publicKeyRaw = challenge['readback_public_key'];
  final expiry = DateTime.tryParse(challenge['expires_at']?.toString() ?? '');
  if (challenge['beneficiary_link_id'] != released.linkId ||
      challenge['stage_revision'] != released.stageRevision ||
      challenge['offer_commitment'] != released.offerCommitment ||
      challenge['owner_vault_id'] != released.ownerVaultId ||
      challenge['beneficiary_vault_id'] != beneficiaryVaultId ||
      challenge['package_decryption_verified'] != false ||
      expiry == null ||
      !DateTime.now().toUtc().isBefore(expiry.toUtc())) {
    throw StateError('Readback challenge changed or expired');
  }
  _field(nonceRaw, 32);
  final serverPublicKey = _field(publicKeyRaw, 32);
  final keyPair = await _readbackKeyPair(
    ownerMvk: released.ownerMvk,
    linkId: released.linkId,
    stageRevision: released.stageRevision,
    offerCommitment: released.offerCommitment,
    ownerVaultId: released.ownerVaultId,
    beneficiaryVaultId: beneficiaryVaultId,
  );
  final localPublicKey = await keyPair.extractPublicKey();
  if (!_sameBytes(localPublicKey.bytes, serverPublicKey)) {
    throw StateError('Owner readback verifier differs from decrypted key');
  }
  checkAccess();
  final signature = await _ed25519.sign(
    utf8.encode(_challengeMessage(
      linkId: released.linkId,
      stageRevision: released.stageRevision,
      offerCommitment: released.offerCommitment,
      ownerVaultId: released.ownerVaultId,
      beneficiaryVaultId: beneficiaryVaultId,
      challengeNonce: nonceRaw as String,
    )),
    keyPair: keyPair,
  );
  checkAccess();
  final result = await submitProof({
    'beneficiary_link_id': released.linkId,
    'stage_revision': released.stageRevision,
    'offer_commitment': released.offerCommitment,
    'challenge_nonce': nonceRaw,
    'signature': _b64(signature.bytes),
    'zk_proof_token': zkProofToken,
  });
  checkAccess();
  final readbackAt = DateTime.tryParse(result['readback_at']?.toString() ?? '');
  if (result['beneficiary_link_id'] != released.linkId ||
      result['stage_revision'] != released.stageRevision ||
      result['offer_commitment'] != released.offerCommitment ||
      result['package_decryption_verified'] != true ||
      result['legacy_package_preserved'] != true ||
      readbackAt == null) {
    throw StateError('Readback receipt differs');
  }
  return LinkedReadbackReceipt(
    linkId: released.linkId,
    stageRevision: released.stageRevision,
    offerCommitment: released.offerCommitment,
    readbackAt: readbackAt.toUtc(),
  );
}

bool _sameBytes(List<int> left, List<int> right) {
  if (left.length != right.length) return false;
  var difference = 0;
  for (var index = 0; index < left.length; index++) {
    difference |= left[index] ^ right[index];
  }
  return difference == 0;
}
