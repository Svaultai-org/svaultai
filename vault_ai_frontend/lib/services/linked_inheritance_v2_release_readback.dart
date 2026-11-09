/// Release-only beneficiary readback of an old link's staged V2 package.
///
/// The server keeps the old package intact. Decryption of the owner's MVK
/// happens only on this unlocked beneficiary device after the existing
/// approval/cooldown state reaches released.
library;

import 'package:cryptography/cryptography.dart';

import 'inheritance_mvk_v2.dart';

typedef FetchReleasedLinkedPackage = Future<Map<String, dynamic>> Function(
  int linkId,
);

class ReleasedLinkedInheritanceV2 {
  final int linkId;
  final int stageRevision;
  final String offerCommitment;
  final String ownerVaultId;
  final SecretKey ownerMvk;
  final SecretKey? ownerLegacyKey;

  const ReleasedLinkedInheritanceV2({
    required this.linkId,
    required this.stageRevision,
    required this.offerCommitment,
    required this.ownerVaultId,
    required this.ownerMvk,
    this.ownerLegacyKey,
  });
}

Future<ReleasedLinkedInheritanceV2> readReleasedLinkedInheritanceV2({
  required int linkId,
  required SecretKey beneficiaryPrivateKey,
  required FetchReleasedLinkedPackage fetchReleased,
  required bool Function() accessIsCurrent,
}) async {
  void checkAccess() {
    if (!accessIsCurrent()) {
      throw StateError('Beneficiary vault access changed');
    }
  }

  if (linkId <= 0) throw const FormatException('Invalid inheritance link');
  checkAccess();
  final raw = await fetchReleased(linkId);
  checkAccess();
  final revision = raw['stage_revision'];
  final commitment = raw['offer_commitment'];
  final ownerId = raw['owner_vault_id'];
  final releasedAt = DateTime.tryParse(raw['released_at']?.toString() ?? '');
  if (raw['beneficiary_link_id'] != linkId ||
      raw['crypto_version'] != inheritanceMvkCryptoVersion ||
      raw['pairing_state'] != 'released' ||
      releasedAt == null ||
      revision is! int ||
      revision <= 0 ||
      commitment is! String ||
      !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(commitment) ||
      ownerId is! String ||
      ownerId.isEmpty ||
      raw['legacy_package_preserved'] != true ||
      raw['package_decryption_verified'] != false) {
    throw const FormatException('Invalid released inheritance package');
  }
  final decoded = await decryptInheritanceMvk(
    expectedLinkId: linkId,
    beneficiaryPrivateKey: beneficiaryPrivateKey,
    rawPackage: raw,
  );
  checkAccess();
  if (decoded.ownerVaultId != ownerId) {
    throw StateError('Inheritance owner identity changed');
  }
  return ReleasedLinkedInheritanceV2(
    linkId: linkId,
    stageRevision: revision,
    offerCommitment: commitment,
    ownerVaultId: ownerId,
    ownerMvk: decoded.ownerMvk,
    ownerLegacyKey: decoded.ownerLegacyKey,
  );
}
