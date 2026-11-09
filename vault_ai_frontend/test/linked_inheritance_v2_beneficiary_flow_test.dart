import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_beneficiary_flow.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_item_import.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_readback_proof.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_release_readback.dart';

void main() {
  const commitment = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
  LinkedReadbackReceipt receipt([int revision = 3]) => LinkedReadbackReceipt(
    linkId: 19,
    stageRevision: revision,
    offerCommitment: commitment,
    readbackAt: DateTime.utc(2026, 11, 9),
  );
  ReleasedLinkedInheritanceV2 released([int revision = 3]) =>
      ReleasedLinkedInheritanceV2(
        linkId: 19,
        stageRevision: revision,
        offerCommitment: commitment,
        ownerVaultId: 'synthetic-owner',
        ownerMvk: SecretKey(List<int>.filled(32, 7)),
      );

  test(
    'explicit import obtains proof before copying one bound release',
    () async {
      final calls = <String>[];
      final result = await importReleasedLinkedOldItemsExplicitly(
        linkId: 19,
        accessIsCurrent: () => true,
        freshProof: () async {
          calls.add('proof');
          return 'synthetic-opaque-proof';
        },
        proveReadback: (proof) async {
          expect(proof, 'synthetic-opaque-proof');
          calls.add('prove');
          return receipt();
        },
        readReleased: () async {
          calls.add('read');
          return released();
        },
        importItems: (package, proof) async {
          calls.add('copy');
          expect(package.stageRevision, proof.stageRevision);
          return const LinkedV2SavedItemImport(
            itemCount: 2,
            newItems: 2,
            sourceInventorySha256: commitment,
          );
        },
      );
      expect(result.newItems, 2);
      expect(calls, ['proof', 'prove', 'read', 'copy']);
    },
  );

  test('PIN substitute and changed release never reach item copy', () async {
    var calls = 0;
    Future<LinkedV2SavedItemImport> copy(
      ReleasedLinkedInheritanceV2 package,
      LinkedReadbackReceipt proof,
    ) async {
      calls++;
      throw StateError('Must not copy');
    }

    await expectLater(
      importReleasedLinkedOldItemsExplicitly(
        linkId: 19,
        accessIsCurrent: () => true,
        freshProof: () async => '123456',
        proveReadback: (_) async => receipt(),
        readReleased: () async => released(),
        importItems: copy,
      ),
      throwsArgumentError,
    );
    await expectLater(
      importReleasedLinkedOldItemsExplicitly(
        linkId: 19,
        accessIsCurrent: () => true,
        freshProof: () async => 'synthetic-opaque-proof',
        proveReadback: (_) async => receipt(),
        readReleased: () async => released(4),
        importItems: copy,
      ),
      throwsStateError,
    );
    expect(calls, 0);
  });

  test('vault lock after proof stops before fetching release', () async {
    var current = true;
    var fetched = false;
    await expectLater(
      importReleasedLinkedOldItemsExplicitly(
        linkId: 19,
        accessIsCurrent: () => current,
        freshProof: () async => 'synthetic-opaque-proof',
        proveReadback: (_) async {
          current = false;
          return receipt();
        },
        readReleased: () async {
          fetched = true;
          return released();
        },
        importItems: (_, __) async => throw StateError('Must not copy'),
      ),
      throwsStateError,
    );
    expect(fetched, isFalse);
  });
}
