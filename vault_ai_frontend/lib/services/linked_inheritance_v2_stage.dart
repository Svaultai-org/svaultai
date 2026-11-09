/// Owner-side preparation of a private inheritance package for an old link.
///
/// The owner must already be unlocked with its MVK and must independently
/// confirm the beneficiary public-key fingerprint. This stages a new package
/// beside the old link; it never switches, releases, or retires that link.
library;

import 'package:cryptography/cryptography.dart';

import 'inheritance_mvk_v2.dart';
import 'vault_key_hierarchy.dart';

typedef FetchLinkedBeneficiaryPubkey = Future<Map<String, dynamic>> Function(
  int linkId,
);
typedef StageLinkedPackage = Future<Map<String, dynamic>> Function(
  Map<String, dynamic> body,
);
typedef ReadbackLinkedPackage = Future<Map<String, dynamic>> Function(
  int linkId,
);

class StagedLinkedInheritanceV2 {
  final int linkId;
  final int stageRevision;
  final String oldSourceSnapshot;
  final String beneficiaryFingerprint;

  const StagedLinkedInheritanceV2({
    required this.linkId,
    required this.stageRevision,
    required this.oldSourceSnapshot,
    required this.beneficiaryFingerprint,
  });
}

Future<StagedLinkedInheritanceV2> stageLinkedOldInheritanceV2({
  required int linkId,
  required String ownerVaultId,
  required SecretKey ownerMvk,
  SecretKey? ownerLegacyKey,
  required String confirmedBeneficiaryFingerprint,
  required String zkProofToken,
  int? expectedStageRevision,
  required FetchLinkedBeneficiaryPubkey fetchPubkey,
  required StageLinkedPackage stage,
  required ReadbackLinkedPackage readback,
  required bool Function() accessIsCurrent,
}) async {
  void checkAccess() {
    if (!accessIsCurrent()) throw StateError('Vault access changed');
  }

  if (linkId <= 0 ||
      ownerVaultId.isEmpty ||
      zkProofToken.isEmpty ||
      (expectedStageRevision != null && expectedStageRevision <= 0)) {
    throw const FormatException('Invalid linked inheritance stage');
  }
  checkAccess();
  final keyResponse = await fetchPubkey(linkId);
  checkAccess();
  if (keyResponse['beneficiary_link_id'] != linkId ||
      keyResponse['crypto_version_hint'] != 1 ||
      keyResponse['pk_vault_public_b64url'] is! String) {
    throw const FormatException('Old linked beneficiary key unavailable');
  }
  final publicKey = b64urlDecode(
    keyResponse['pk_vault_public_b64url'] as String,
  );
  final fingerprint = await beneficiaryPublicKeyFingerprint(publicKey);
  if (!beneficiaryFingerprintMatches(
    fingerprint,
    confirmedBeneficiaryFingerprint,
  )) {
    throw const FormatException('Beneficiary key fingerprint differs');
  }
  checkAccess();
  final envelope = await encryptInheritanceMvk(
    beneficiaryLinkId: linkId,
    ownerVaultId: ownerVaultId,
    ownerMvk: ownerMvk,
    ownerLegacyKey: ownerLegacyKey,
    beneficiaryPublicKey: publicKey,
  );
  checkAccess();
  final body = envelope.toRequestBody(linkId);
  body['expected_beneficiary_pk_sha256'] =
      fingerprint.replaceAll('-', '').toLowerCase();
  body['zk_proof_token'] = zkProofToken;
  if (expectedStageRevision != null) {
    body['expected_stage_revision'] = expectedStageRevision;
  }
  final staged = await stage(body);
  checkAccess();
  final stored = await readback(linkId);
  checkAccess();
  final revision = staged['stage_revision'];
  final snapshot = staged['old_source_snapshot'];
  if (staged['beneficiary_link_id'] != linkId ||
      staged['crypto_version'] != inheritanceMvkCryptoVersion ||
      staged['state'] != 'staged' ||
      staged['legacy_link_unchanged'] != true ||
      staged['beneficiary_pk_sha256'] !=
          body['expected_beneficiary_pk_sha256'] ||
      revision is! int ||
      revision <= 0 ||
      snapshot is! String ||
      !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(snapshot) ||
      stored['beneficiary_link_id'] != linkId ||
      stored['crypto_version'] != inheritanceMvkCryptoVersion ||
      stored['state'] != 'staged' ||
      stored['legacy_link_unchanged'] != true ||
      stored['stage_revision'] != revision ||
      stored['old_source_snapshot'] != snapshot ||
      stored['beneficiary_pk_sha256'] !=
          body['expected_beneficiary_pk_sha256'] ||
      stored['encrypted_payload'] != body['encrypted_payload'] ||
      stored['payload_nonce'] != body['payload_nonce'] ||
      stored['wrapped_key'] != body['wrapped_key'] ||
      stored['wrapping_ephemeral_pk'] != body['wrapping_ephemeral_pk'] ||
      stored['wrapping_nonce'] != body['wrapping_nonce']) {
    throw StateError('Linked inheritance stage readback differs');
  }
  return StagedLinkedInheritanceV2(
    linkId: linkId,
    stageRevision: revision,
    oldSourceSnapshot: snapshot,
    beneficiaryFingerprint: fingerprint,
  );
}
