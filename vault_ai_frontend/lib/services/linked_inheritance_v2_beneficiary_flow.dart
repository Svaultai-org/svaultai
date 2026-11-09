/// Explicit beneficiary action for copying released old-link saved items.
/// The release proof and copied ciphertext are bound to the same stage.
library;

import 'linked_inheritance_v2_item_import.dart';
import 'linked_inheritance_v2_readback_proof.dart';
import 'linked_inheritance_v2_release_readback.dart';
import 'zk_proof_token_guard.dart';

typedef ProveReleasedLinkedReadback =
    Future<LinkedReadbackReceipt> Function(String proofToken);
typedef ReadReleasedLinkedPackage =
    Future<ReleasedLinkedInheritanceV2> Function();
typedef ImportReleasedLinkedItems =
    Future<LinkedV2SavedItemImport> Function(
      ReleasedLinkedInheritanceV2 released,
      LinkedReadbackReceipt receipt,
    );

Future<LinkedV2SavedItemImport> importReleasedLinkedOldItemsExplicitly({
  required int linkId,
  required Future<String> Function() freshProof,
  required ProveReleasedLinkedReadback proveReadback,
  required ReadReleasedLinkedPackage readReleased,
  required ImportReleasedLinkedItems importItems,
  required bool Function() accessIsCurrent,
}) async {
  void checkAccess() {
    if (!accessIsCurrent()) {
      throw StateError('Beneficiary vault access changed');
    }
  }

  if (linkId <= 0) throw const FormatException('Invalid inheritance link');
  checkAccess();
  final proof = rejectPinShapedZkProof(await freshProof());
  checkAccess();
  if (proof.isEmpty) throw StateError('Beneficiary proof unavailable');
  final receipt = await proveReadback(proof);
  checkAccess();
  if (receipt.linkId != linkId ||
      receipt.stageRevision <= 0 ||
      receipt.offerCommitment.isEmpty) {
    throw StateError('Inheritance readback proof changed');
  }
  final released = await readReleased();
  checkAccess();
  if (released.linkId != linkId ||
      released.stageRevision != receipt.stageRevision ||
      released.offerCommitment != receipt.offerCommitment) {
    throw StateError('Inheritance release changed after proof');
  }
  final result = await importItems(released, receipt);
  checkAccess();
  return result;
}
